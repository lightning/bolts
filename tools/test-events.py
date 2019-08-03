#! /usr/bin/python3
# This script exercises a lightning implementation using a JSON test case.

# Released by Rusty Russell under CC0:
# https://creativecommons.org/publicdomain/zero/1.0/

import argparse
from copy import copy
import fileinput
import networkx as nx
from os import path
import re
import string
import struct
import sys
import matplotlib.pyplot as plt

# Populated by read_csv
messages = []

# From 01-messaging.md#fundamental-types:
name2size = {'byte': 1,
             'u16': 2,
             'u32': 4,
             'u64': 8,
             'short_channel_id': 8,
             'chain_hash': 32,
             'channel_id': 32,
             'sha256': 32,
             'preimage': 32,
             'secret': 32,
             'point': 33,
             'pubkey': 33,
             'signature': 64}

name2structfmt = {'byte': 'B',
                  'u16': '>H',
                  'u32': '>I',
                  'u64': '>Q',
                  'short_channel_id': '>Q'}


def setup_cmdline_options():
    """Create an argparse.ArgumentParser for standard cmdline options"""
    class OptionAction(argparse._AppendAction):
        def __call__(self, parser, namespace, values, option_string=None):
            if not values.endswith('/even') and not values.endswith('/odd'):
                raise argparse.ArgumentTypeError("{} must end in /odd or /even"
                                                 .format(option_string))
            super().__call__(parser, namespace, values, option_string)

    parser = argparse.ArgumentParser()
    parser.add_argument('csv_file', help='CSV file describing packet formats)')
    parser.add_argument('input', nargs='*', default=[None],
                        help='Files to read in (or stdin)')
    parser.add_argument('-v', '--verbose', help='Show working',
                        action="store_true")
    parser.add_argument('--draw-events', help='Output "<input>.png"',
                        action="store_true")
    parser.add_argument('--exhaustive', help='Try all possible paths',
                        action="store_true")
    parser.add_argument('--via', type=str,
                        help='Test shortest path via this specific [file:]line')
    parser.add_argument('--flatten-failpath', help='Output a valid input file for the failing path',
                        action="store_true")
    parser.add_argument('-o', '--option', action=OptionAction, default=[],
                        help='Indicate supported option')

    return parser


class Line(object):
    """Line of input from the testfile (could be multiple if they continue)"""
    def __init__(self, filename, linestart, lineend, indentlevel, line):
        self.filename = filename
        self.linestart = linestart
        self.lineend = lineend
        self.indentlevel = indentlevel
        self.line = line[:]

    def __copy__(self):
        return Line(self.filename, self.linestart, self.lineend,
                    self.indentlevel, self.line)

    def __iadd__(self, other):
        """+= two Lines: assumes they are adjacent."""
        if type(other) != Line:
            return NotImplemented
        # Tokens across filesystem boundaries (ie. include) don't add.
        if other.filename == self.filename:
            self.linestart = min(self.linestart, other.linestart)
            self.lineend = max(self.lineend, other.lineend)
        self.line += '\n' + other.line
        return self

    def __str__(self):
        # Human-readable line numbers are 1-based
        if self.linestart == self.lineend:
            return "{}:{}".format(self.filename, self.linestart + 1)
        else:
            return "{}:{}-{}".format(self.filename, self.linestart + 1,
                                     self.lineend + 1)

    def __repr__(self):
        return "Line " + self.__str__()

    def flatten(self, index, stopline, prefix):
        print("{}# {}".format(prefix, self))
        parts = self.line.partition('.')
        print("{}{}.{}".format(prefix, index, parts[2]))
        return self == stopline, index + 1


def pack(typename, v):
    """Pack this value as this type"""
    if typename in name2structfmt:
        return struct.pack(name2structfmt[typename], v)

    # FIXME: This is our non-TLV code
    if typename.endswith('_tlvs'):
        return v

    if typename in Subtype.objs:
        return Subtype.objs[typename].pack(v)

    # Pack directly as bytes
    assert len(v) == name2size[typename]
    return bytes(v)


def unpack_from(typename, bytestream, offset):
    """Unpack from bytestream as this type.  Returns len, value, or None, None"""
    if typename in name2structfmt:
        size = struct.calcsize(name2structfmt[typename])
        if size + offset > len(bytestream):
            return None, None
        return (size, struct.unpack_from(name2structfmt[typename],
                                         bytestream, offset)[0])

    # FIXME: This is our non-TLV code
    if typename.endswith('_tlvs'):
        return len(bytestream) - offset, bytestream[offset:]

    if typename in Subtype.objs:
        subtype = Subtype.objs[typename]
        return subtype.unpack(bytestream, offset)

    # Unpack directly as bytes
    size = name2size[typename]
    if size + offset > len(bytestream):
        return None, None
    return size, bytestream[offset:offset + size]


class ValidationError(Exception):
    def __init__(self, line, message):
        self.line = line
        # Call the base class constructor with the parameters it needs
        super().__init__(str(line) + ": Validation failed: " + message)


class LineError(Exception):
    def __init__(self, line, message):
        # Call the base class constructor with the parameters it needs
        super().__init__(str(line) + ": Parsing failed:" + message)


# #### Dummy runner which you should replace with real one. ####
class DummyRunner(object):
    def __init__(self, args):
        self.verbose = args.verbose
        pass

    def restart(self):
        if self.verbose:
            print("[RESTART]")
        self.blockheight = 102

    def connect(self, id, line):
        if self.verbose:
            print("[CONNECT {}]".format(line))

    def getblockheight(self):
        return self.blockheight

    def trim_blocks(self, newheight):
        if self.verbose:
            print("[TRIMBLOCK TO HEIGHT {}]".format(newheight))
        self.blockheight = newheight

    def add_blocks(self, txs, n, line):
        if self.verbose:
            print("[ADDBLOCKS {} WITH {} TXS]".format(n, len(txs)))
        self.blockheight += n

    def disconnect(self, conn, line):
        if self.verbose:
            print("[DISCONNECT {}]".format(line))

    def wait_for_finalmsg(self, conn):
        if self.verbose:
            print("[WAIT-FOR-FINAL]")
        return None

    def recv(self, conn, outbuf, line):
        if self.verbose:
            print("[RECV {} {}]".format(line, outbuf.hex()))

    def fundchannel(self, conn, amount, txid, outnum, line):
        if self.verbose:
            print("[FUNDCHANNEL TO {} for {} with UTXO {}/{} {}]"
                  .format(conn, amount, txid, outnum, line))

    def invoice(self, amount, preimage, line):
        if self.verbose:
            print("[INVOICE for {} with PREIMAGE {} {}]"
                  .format(amount, preimage, line))

    def expect_send(self, conn, line):
        if self.verbose:
            print("[EXPECT-SEND {}]".format(line))
        # return bytes.fromhex(input("{}? ".format(line)))

    def expect_tx(self, tx, line):
        if self.verbose:
            print("[EXPECT-TX {} {}]".format(tx.hex(), line))

    def expect_error(self, conn, line):
        if self.verbose:
            print("[EXPECT-ERROR {}]", line)

    def final_error(self):
        if self.verbose:
            print("[EXPECT NO ERROR]")
        return None

# #### End dummy runner which you should replace with real one. ####


class Field(object):
    def __init__(self, message, name, typename, count, options):
        self.message = message
        self.name = name
        self.typename = typename
        self.options = options
        self.islenvar = False
        # This contains all the integer types: otherwise it's a hexstring
        self.isinteger = typename in name2structfmt

        # This is set for static-sized array.
        self.arraylen = None
        # This is set for variable-sized array.
        self.arrayvar = None

        if count:
            # If array is a variable, must be prior field.
            try:
                self.arraylen = int(count)
            except ValueError:
                self.arrayvar = message.findField(count)
                self.arrayvar.islenvar = True

    @staticmethod
    def field_from_str(line, typename, isinteger, s):
        if typename == "short_channel_id":
            parts = s.split('x')
            if len(parts) != 3:
                raise LineError(line, "short_channel_id should be NxNxN")
            try:
                return ((int(parts[0]) << 40)
                        | (int(parts[1]) << 16) | (int(parts[2])))
            except ValueError:
                raise LineError(line, "short_channel_id should be <int>x<int>x<int>")
        # Int variants
        if isinteger:
            try:
                v = int(s)
            except ValueError:
                raise LineError(line, "{} should be integer".format(typename))

            if v >= (1 << (name2size[typename] * 8)):
                raise LineError(line, "{} must be < {} bytes"
                                .format(typename, name2size[typename]))
            return v

        # Everything else is a hex string.
        try:
            v = bytes.fromhex(s)
        except ValueError:
            raise LineError(line, "Non-hex value for {}: '{}'"
                            .format(typename, s))
        if len(v) != name2size[typename]:
            raise LineError(line, "{} must be {} bytes long not {}"
                            .format(typename, name2size[typename], len(v)))
        return v

    def field_value(self, line, value):
        """Decodes a value for this field: returns (fieldvalue, arrsize)
        or (fieldvalue, None) if not an array"""
        # If it's an array, expect a JSON array unless it's a byte array.
        if self.arraylen or self.arrayvar:
            if self.typename == 'byte':
                try:
                    v = bytes.fromhex(value)
                except ValueError:
                    raise LineError(line,
                                    "Non-hex value for {} byte array: '{}'"
                                    .format(self.name, value))
                # Known length?  Check
                if self.arraylen and len(v) != self.arraylen:
                    raise LineError(line,
                                    "{} byte array should be length {} not {}"
                                    .format(self.name, self.arraylen, len(v)))
                return v, len(v)
            elif self.typename in Subtype.objs:  # Subtypes
                subtype = Subtype.objs[self.typename]
                return subtype.parse(line, value)
            else:
                arr = []
                # Empty string doesn't quite do what we want with split.
                if value == '':
                    values = []
                else:
                    values = value.split(',')
                for v in values:
                    arr += [self.field_from_str(line, self.typename,
                                                self.isinteger, v)]
                # Known length?  Check
                if self.arraylen and len(arr) != self.arraylen:
                    raise LineError(line,
                                    "{} array should be length {} not {}"
                                    .format(self.name, self.arraylen, len(v)))
                return arr, len(arr)
        else:
            return (self.field_from_str(line,
                                        self.typename, self.isinteger, value),
                    None)

    def __repr__(self):
        s = "{}:{}".format(self.name, self.typename)
        if self.arraylen:
            s += "[{}]".format(self.arraylen)
        elif self.arrayvar:
            s += "[{}]".format(self.arrayvar.name)
        return s


class Message(object):
    # * 0x8000 (BADONION): unparsable onion encrypted by sending peer
    # * 0x4000 (PERM): permanent failure (otherwise transient)
    # * 0x2000 (NODE): node failure (otherwise channel)
    # * 0x1000 (UPDATE): new channel update enclosed
    onion_types = {'BADONION': 0x8000,
                   'PERM': 0x4000,
                   'NODE': 0x2000,
                   'UPDATE': 0x1000}

    def __init__(self, name, value):
        self.name = name
        self.value = self.parse_value(value)
        self.fields = []

    def parse_value(self, value):
        result = 0
        for token in value.split('|'):
            if token in self.onion_types.keys():
                result |= self.onion_types[token]
            else:
                result |= int(token)

        return result

    def findField(self, fieldname):
        for f in self.fields:
            if f.name == fieldname:
                return f
        return None

    def addField(self, field):
        self.fields.append(field)

    def __repr__(self):
        return "{}:{}:{}".format(self.name, self.value, self.fields)


def find_message(messages, name):
    for m in messages:
        if m.name == name:
            return m

    return None


class Subtype(Message):
    objs = {}

    def __init__(self, name):
        Message.__init__(self, name, '0')

    def parse(self, line, s):
        """ Given an input line for a subtype, parse it into a dict
            of fields for that subtype """
        if len(s) == 0:
            return b'', 0

        if s[0] == '[':
            i = 1
            arr = []
            while i < len(s) and s[i] != ']':
                end, obj = self._parse_obj(line, s[i:])
                arr.append(obj)
                i += end
                if i < len(s) and s[i] == ',':
                    i += 1
            return arr, len(arr)
        else:
            _, obj = self.parse_obj(line, s)
            return obj, None

    def _parse_obj(self, line, s):
        if s[0] != '{':
            raise LineError(line, "Subtype formatted incorrectly. got {} when expecting an open bracket ({},{})"
                            .format(s[0], self.name, s))

        end, fields = self.find_fields(s)
        if end < 0:
            raise LineError(line, "Subtype formatted incorrectly. No end bracket found ({}, {})"
                            .format(self.name, s))

        val = {}
        for f_name, f_val in fields:
            sub_field = self.findField(f_name)

            if not sub_field:
                raise LineError(line, "{} subtype error. Unable to find field {}"
                                .format(self.name, f_name))

            val[f_name], vararrlen = sub_field.field_value(line, f_val)
            if vararrlen is not None:
                val[sub_field.arrayvar.name] = vararrlen

        return end + 1, val

    def find_fields(self, s):
        """ Handle nested arrays + objects. Returns set of fields for
            the upper most object and the 'end' count of where this object ends.
            {abc=[{},{}],bcd=[{},{}],...],abc=[]},{abc=[{},{}]}... """
        arr_count = 0
        bracket_count = 0
        end = len(s)
        field_set = []
        i = 0
        field = ''
        tok = None
        while i < end:
            if s[i] == '[':
                arr_count += 1
                field += s[i]
            elif s[i] == ']':
                arr_count -= 1
                field += s[i]
            elif s[i] == '{':
                bracket_count += 1
                if i != 0:
                    field += s[i]
            elif s[i] == '}':
                bracket_count -= 1
                if bracket_count == 0:
                    field_set.append((tok, field))
                    return i, field_set
                else:
                    field += s[i]
            elif s[i] == ',':
                if bracket_count == 1 and arr_count == 0:
                    field_set.append((tok, field))
                    field = ''
                    tok = None
                else:
                    field += s[i]
            elif s[i] == '=':
                if not tok:
                    tok = field
                    field = ''
                else:
                    field += s[i]
            else:
                field += s[i]

            i += 1
        return -1, None

    def pack(self, values):
        """ We need to return bytes for each field """
        bites = bytes([])
        for f in self.fields:
            if f.name in values:
                val = values[f.name]
                if f.arrayvar or f.arraylen:
                    for a in val:
                        bites += pack(f.typename, a)
                else:
                    bites += pack(f.typename, val)
        return bites

    def unpack(self, bytestream, offset):
        """ For every field, unpack it"""
        result = {}
        lenfields = {}
        offset_start = offset
        for f in self.fields:
            offset, v = unpack_field(f, lenfields, bytestream, offset)
            result[f.name] = v

        return offset - offset_start, result

    def compare(self, msgname, vals, expected):
        if not bool(expected):
            if bool(vals):
                return ("Nothing expected for {}.{} but returned {}"
                        .format(msgname, self.name, vals))
            return None
        for name, exp_val in expected.items():
            if name not in vals:
                return ("Expected field {}.{}.{} "
                        "not present in values"
                        .format(msgname, self.name, name))

            f = self.findField(name)
            if not f:
                return ("Field {} is not known for subtype {}({})"
                        .format(name, self.name, msgname))

            val = vals[name]
            err = compare_results(msgname + "." + self.name, f, val, exp_val)
            if err is not None:
                return err

        return None


def unpack_field(field, lenfields, bytestream, offset):
    # If it's an array, we need the whole thing.
    if field.arrayvar or field.arraylen:
        if field.arrayvar:
            num = lenfields[field.arrayvar.name]
        else:
            num = field.arraylen
        # Array of bytes is special: treat raw.
        if field.typename == 'byte':
            v = bytestream[offset:offset + num]
            offset += num
        else:
            v = []
            for i in range(0, num):
                size, var = unpack_from(field.typename, bytestream, offset)
                if size is None:
                    raise ValueError('Response too short to extract {}[{}]: {}'
                                     .format(field.name, i, bytestream.hex()))
                offset += size
                v += [var]
    else:
        size, v = unpack_from(field.typename, bytestream, offset)
        if size is None:
            # Optional fields might not exist
            if field.options != []:
                v = None
                size = 0
            else:
                raise ValueError('Response too short to extract {} {} ({}): {}'
                                 .format(field.name, field.typename, offset, v))
        offset += size

    # If it's used as a length, save it.
    if field.islenvar:
        lenfields[field.name] = int(v)

    return offset, v


def read_csv(args):
    for line in fileinput.input(args.csv_file):
        parts = line.rstrip().split(',')

        if parts[0] == 'msgtype':
            # eg msgtype,commit_sig,132
            messages.append(Message(parts[1], parts[2]))
        elif parts[0] == 'msgdata':
            m = find_message(messages, parts[1])
            if m is None:
                raise ValueError('Unknown message {}'.format(parts[1]))

            # eg. msgdata,channel_reestablish,your_last_per_commitment_secret
            #     ,secret,,1option209
            m.addField(Field(m, parts[2], parts[3], parts[4], parts[5:]))
        elif parts[0] == 'subtype':
            Subtype.objs[parts[1]] = Subtype(parts[1])
        elif parts[0] == 'subtypedata':
            if parts[1] not in Subtype.objs:
                raise ValueError('Unknown subtype {}'.format(parts[1]))
            # Insert fields into dict for subtype
            subtype = Subtype.objs[parts[1]]
            subtype.addField(Field(subtype, parts[2], parts[3], parts[4], parts[5:]))


def parse_params(line, parts, compulsorykeys, optionalkeys=[]):
    """Given an array of <key>=<val> make a dict, checking we have all compulsory
# keys."""
    ret = {}
    for i in parts:
        p = i.partition('=')
        if p[1] != '=':
            raise LineError(line, "Malformed key {} does not contain '='"
                            .format(i))
        if p[0] in ret.keys():
            raise LineError(line, "Duplicate key {}".format(p[0]))
        if p[0] in compulsorykeys:
            compulsorykeys.remove(p[0])
        elif p[0] in optionalkeys:
            optionalkeys.remove(p[0])
        else:
            raise LineError(line, "Unknown key {}".format(p[0]))
        ret[p[0]] = p[2]

    if compulsorykeys != []:
        raise LineError(line, "No specification for key {}"
                        .format(compulsorykeys[0]))
    return ret


def check_hex(line, val, digits):
    if not all(c in string.hexdigits for c in val):
        raise LineError(line, "{} is not valid hex".format(val))
    if len(val) != digits:
        raise LineError(line, "{} not {} characters long".format(val, digits))


class Connection(object):
    """Trivial class to represent a connection: often decorated by others"""
    def __init__(self, connkey):
        self.connkey = connkey
        self.maybe_sends = []
        self.must_not_sends = []

    def __str__(self):
        return str(self.connkey)


def optional_connection(line, params):
    """Trivial helper to return & remove conn=key if specified, None if not"""
    ret = params.pop('conn', None)
    if ret is not None:
        check_hex(line, ret, 64)
    return ret


def which_connection(line, runner, connkey):
    """Helper to get the conn they asked for, or default if connkey=None"""
    if connkey is None:
        if len(runner.connections) == 0:
            raise LineError(line, "No active 'connect'")
        return runner.connections[-1]
    for c in runner.connections:
        if c.connkey == connkey:
            return c
    raise LineError(line, "No active 'connect' {}".format(connkey))


def end_connection(runner, conn, line):
    """Helper to wait to see if any must-not-send are triggered at end"""
    if conn.must_not_sends == []:
        return

    # We assume we don't get an infinite stream of msgs!
    while True:
        msg = runner.wait_for_finalmsg(conn)
        if msg is None:
            return
        for m in conn.must_not_sends:
            if message_match(m.expectmsg, m.expectfields, msg) is None:
                raise ValidationError(line, "must-not-send at {} violated by {}"
                                      .format(m.line, msg.hex()))

        # If it was an (unexpected) error, we've failed.
        if not runner.expected_error and struct.unpack('>H', msg[0:2]) == (17,):
            raise ValidationError(line,
                                  "Unexpected error occurred: {}".format(msg.hex()))


class NothingEvent(object):
    def __init__(self, line, parts):
        parse_params(line, parts, [])

    def action(self, runner, line):
        pass


class ConnectEvent(object):
    def __init__(self, line, parts):
        self.privkey = parse_params(line, parts, ['privkey'])['privkey']
        check_hex(line, self.privkey, 64)

    def action(self, runner, line):
        conn = Connection(self.privkey)
        if conn.connkey in [c.connkey for c in runner.connections]:
            raise LineError(line,
                            "Already have connection to {}".format(conn.connkey))
        runner.connections.append(conn)
        runner.connect(conn, line)


class DisconnectEvent(object):
    def __init__(self, line, parts):
        d = parse_params(line, parts, [], ['conn'])
        self.connkey = optional_connection(line, d)

    def action(self, runner, line):
        conn = which_connection(line, runner, self.connkey)

        end_connection(runner, conn, line)
        runner.disconnect(conn, line)
        runner.connections.remove(conn)


class RecvEvent(object):
    def __init__(self, line, parts):
        if len(parts) < 1:
            raise LineError(line, "Missing type=")
        t = parts[0].partition('=')
        if t[1] != '=':
            raise LineError(line, "Expected type=")

        msg = find_message(messages, t[2])
        if not msg:
            # Allow raw integers.
            msg = Message('unknown', t[2])

        # See what fields are allowed.
        fields = []
        optfields = ['conn', 'extra']
        for f in msg.fields:
            # Lengths are implied
            if f.islenvar:
                continue
            # Optional fields are, um, optional.
            if f.options:
                optfields.append(f.name)
            else:
                fields.append(f.name)

        # This fails if non-optional fields aren't specified.
        d = parse_params(line, parts[1:], fields, optfields)
        self.connkey = optional_connection(line, d)

        # Now get values for assembling the message.
        values = {}
        for f in msg.fields:
            # Lengths are implied
            if f.islenvar:
                continue
            if f.name not in d:
                continue
            value, vararrlen = f.field_value(line, d[f.name])
            values[f.name] = value
            if f.arrayvar:
                values[f.arrayvar.name] = vararrlen

        # BOLT #1:
        # After decryption, all Lightning messages are of the form:
        #
        # 1. `type`: a 2-byte big-endian field indicating the type of message
        # 2. `payload`: a variable-length payload that comprises the remainder
        #    of the message and that conforms to a format matching the `type`
        self.b = struct.pack(">H", msg.value)
        for f in msg.fields:
            if f.name not in values:
                continue

            v = values[f.name]
            if f.arrayvar or f.arraylen:
                for a in v:
                    self.b += pack(f.typename, a)
            else:
                self.b += pack(f.typename, v)

        if 'extra' in d:
            self.b += bytes.fromhex(d['extra'])

    def action(self, runner, line):
        runner.recv(which_connection(line, runner, self.connkey),
                    self.b, line)

def compare_results(msgname, f, v, exp):
    """ f -> field; v -> value; exp -> expected value """

    # If they specify field=absent, it must not be there.
    if exp is None:
        if v is not None:
            return "Field {} is present"
        else:
            return None

    if v is None:
        return ("Optional field {} is not present"
                .format(f.name))
    if isinstance(exp, tuple):
        # Out-of-range bitmaps are considered 0 (eg. feature tests)
        if len(v) < len(exp[0]):
            cmpv = b'\x00' * (len(exp[0]) - len(v)) + v
        elif len(v) > len(exp[0]):
            cmpv = v[-len(exp[0]):]
        else:
            cmpv = v

        for i in range(0, len(exp[0])):
            if cmpv[i] & exp[1][i] != exp[0][i]:
                return ("Expected {}.{} mask 0x{}"
                        " value 0x{} but got 0x{}"
                        " (offset {} different)"
                        .format(msgname, f.name,
                                exp[1].hex(), exp[0].hex(),
                                v.hex(), len(exp[0]) - 1 - i))
    # Use subtype comparer
    elif f.typename in Subtype.objs:
        return Subtype.objs[f.typename].compare(msgname, v[0], exp[0])

    # Simple comparison
    elif v != exp:
        if f.isinteger:
            valstr = str(v)
            expectstr = str(exp)
        else:
            valstr = v.hex()
            expectstr = exp.hex()
        return ("Expected {}.{} {} but got {}"
                .format(msgname,
                        f.name, expectstr, valstr))
    return None


def compare_results(msgname, f, v, exp):
    """ f -> field; v -> value; exp -> expected value """

    # If they specify field=absent, it must not be there.
    if exp is None:
        if v is not None:
            return "Field {} is present"
        else:
            return None

    if v is None:
        return ("Optional field {} is not present"
                .format(f.name))
    if isinstance(exp, tuple):
        # Out-of-range bitmaps are considered 0 (eg. feature tests)
        if len(v) < len(exp[0]):
            cmpv = b'\x00' * (len(exp[0]) - len(v)) + v
        elif len(v) > len(exp[0]):
            cmpv = v[-len(exp[0]):]
        else:
            cmpv = v

        for i in range(0, len(exp[0])):
            if cmpv[i] & exp[1][i] != exp[0][i]:
                return ("Expected {}.{} mask 0x{}"
                        " value 0x{} but got 0x{}"
                        " (offset {} different)"
                        .format(msgname, f.name,
                                exp[1].hex(), exp[0].hex(),
                                v.hex(), len(exp[0]) - 1 - i))
    # Use subtype comparer
    elif f.typename in Subtype.objs:
        return Subtype.objs[f.typename].compare(msgname, v, exp)

    # Simple comparison
    elif v != exp:
        if f.isinteger:
            valstr = str(v)
            expectstr = str(exp)
        else:
            valstr = v.hex()
            expectstr = exp.hex()
        return ("Expected {}.{} {} but got {}"
                .format(msgname,
                        f.name, expectstr, valstr))
    return None


def message_match(expectmsg, expectfields, b):
    """Internal helper to see if b matches expectmsg & expectfields.

    Returns explanation string if it didn't match, otherwise None."""
    msgtype = struct.unpack_from(">H", b)[0]
    off = 2

    if msgtype != expectmsg.value:
        return "Expected msg {} but got {}: {}".format(expectmsg.name,
                                                       msgtype, b.hex())
    # Keep length fields
    lenfields = {}
    for f in expectmsg.fields:
        off, v = unpack_field(f, lenfields, b, off)

        # They expect a value from this.
        if f.name in expectfields:
            exp = expectfields[f.name]
            err = compare_results(expectmsg.name, f, v, exp)
            if err is not None:
                return err + ": {}".format(b.hex())

    return None


def maybesend_match(conn, msg):
    """Internal helper to see if msg matches one of the previous maybe-sends"""
    for m in conn.maybe_sends:
        failreason = message_match(m.expectmsg, m.expectfields, msg)
        if failreason is None:
            conn.maybe_sends.remove(m)
            return True

    return False


class ExpectSendEvent(object):
    def __init__(self, line, parts, maybe=False, mustnot=False):
        self.line = line
        self.maybe = maybe
        self.mustnot = mustnot
        if len(parts) < 1:
            raise LineError(line, "Missing type=")
        t = parts[0].partition('=')
        if t[1] != '=':
            raise LineError(line, "Expected type=")

        self.expectmsg = find_message(messages, t[2])
        if not self.expectmsg:
            raise LineError(line, "Unknown message type")
        self.expectfields = {}

        optfields = ['conn']
        for f in self.expectmsg.fields:
            # Lengths are implied
            if f.islenvar:
                continue
            optfields.append(f.name)

        # All fields are optional
        d = parse_params(line, parts[1:], [], optfields)
        self.connkey = optional_connection(line, d)

        for v in d.keys():
            # IDENTIFIER`=`FIELDVALUE | IDENTIFIER`=`HEX/HEX | `absent`
            f = self.expectmsg.findField(v)

            parts = d[v].partition('/')
            if parts[1] == '/':
                self.expectfields[v] = (bytes.fromhex(parts[0]),
                                        bytes.fromhex(parts[2]))
                if len(self.expectfields[v][0]) != len(self.expectfields[v][1]):
                    raise LineError(line, "Unequal value/mask lengths")
            else:
                if parts[0] == 'absent':
                    if f.options == []:
                        raise LineError(line, "Field is not optional")
                    self.expectfields[v] = None
                else:
                    self.expectfields[v], _ = f.field_value(line, parts[0])

    def __repr__(self):
        if self.mustnot:
            return "must-not-send:{}:{}".format(self.expectmsg.name, self.line)
        if self.maybe:
            return "maybe-send:{}:{}".format(self.expectmsg.name, self.line)
        return "expect-send:{}:{}".format(self.expectmsg.name, self.line)

    def action(self, runner, line):
        conn = which_connection(line, runner, self.connkey)
        # If this is 'maybe-send' then just add it to maybe list.
        if self.maybe:
            conn.maybe_sends.append(self)
            return
        # If this is 'must-not-send' then just add it to maybe list.
        elif self.mustnot:
            conn.must_not_sends.append(self)
            return

        msg = runner.expect_send(conn, line)

        # We let the dummy runner "pass" always.
        if type(runner) == DummyRunner:
            return

        while True:
            failreason = message_match(self.expectmsg, self.expectfields, msg)
            if failreason is None:
                return

            if maybesend_match(conn, msg):
                msg = runner.expect_send(conn, line)
            else:
                break

        if conn.maybe_sends != []:
            raise ValidationError(line,
                                  failreason
                                  + " (and none of {})".format(conn.maybe_sends))
        raise ValidationError(line, failreason)


class BlockEvent(object):
    def __init__(self, line, parts):
        # Since parse_params doesn't allow dups, feed it one part at a time
        self.blockheight = int(parse_params(line, [parts[0]], ['height'])['height'])
        self.txs = []
        self.n = 1

        # Since parse_params doesn't allow dups, feed it one part at a time
        for i in range(1, len(parts)):
            # n is only valid as first arg.
            if i == 1:
                d = parse_params(line, [parts[i]], [], ['n', 'tx'])
                if 'n' in d:
                    if self.n != 1:
                        raise LineError(line, "Can't specify n more than once")
                    self.n = int(d['n'])
                    continue
            else:
                d = parse_params(line, [parts[i]], ['tx'])
            self.txs.append(d['tx'])

    def action(self, runner, line):
        # Oops, did they ask us to produce a block with no predecessor?
        if runner.getblockheight() + 1 < self.blockheight:
            raise LineError(line, "Cannot generate block #{} at height {}".
                            format(self.blockheight, runner.getblockheight()))

        # Throw away blocks we're replacing.
        if runner.getblockheight() >= self.blockheight:
            runner.trim_blocks(self.blockheight - 1)

        # Add new one
        runner.add_blocks(self.txs, self.n, line)
        assert runner.getblockheight() == self.blockheight - 1 + self.n


class ExpectTxEvent(object):
    def __init__(self, line, parts):
        self.tx = bytes.fromhex(parse_params(line, parts, ['tx'])['tx'])

    def action(self, runner, line):
        runner.expect_tx(self.tx, line)


class FundChannelEvent(object):
    def __init__(self, line, parts):
        d = parse_params(line, parts, ['amount', 'utxo'], ['conn'])
        self.connkey = optional_connection(line, d)
        self.amount = int(d['amount'])
        parts = d['utxo'].partition('/')
        check_hex(line, parts[0], 66)
        self.utxo = (parts[0], int(parts[2]))

    def action(self, runner, line):
        runner.fundchannel(which_connection(line, runner, self.connkey),
                           self.amount, self.utxo[0],
                           self.utxo[1], line)


class InvoiceEvent(object):
    def __init__(self, line, parts):
        d = parse_params(line, parts, ['amount', 'preimage'])
        self.preimage = d['preimage']
        check_hex(line, self.preimage, 64)
        self.amount = int(d['amount'])

    def action(self, runner, line):
        runner.invoice(self.amount, self.preimage, line)


class ExpectErrorEvent(object):
    def __init__(self, line, parts):
        d = parse_params(line, parts, [], ['conn'])
        self.connkey = optional_connection(line, d)

    def action(self, runner, line):
        runner.expected_error = True
        runner.expect_error(which_connection(line, runner, self.connkey), line)


class Event(object):
    def __init__(self, args, desc, line):
        self.args = args
        self.line = copy(line)

        parts = desc.split()
        self.event = parts[0]

        if parts[0] == 'connect:':
            self.actor = ConnectEvent(line, parts[1:])
        elif parts[0] == 'disconnect:':
            self.actor = DisconnectEvent(line, parts[1:])
        elif parts[0] == 'recv:':
            self.actor = RecvEvent(line, parts[1:])
        elif parts[0] == 'expect-send:':
            self.actor = ExpectSendEvent(line, parts[1:])
        elif parts[0] == 'maybe-send:':
            self.actor = ExpectSendEvent(line, parts[1:], maybe=True)
        elif parts[0] == 'must-not-send:':
            self.actor = ExpectSendEvent(line, parts[1:], mustnot=True)
        elif parts[0] == 'block:':
            self.actor = BlockEvent(line, parts[1:])
        elif parts[0] == 'expect-tx:':
            self.actor = ExpectTxEvent(line, parts[1:])
        elif parts[0] == 'fundchannel:':
            self.actor = FundChannelEvent(line, parts[1:])
        elif parts[0] == 'invoice:':
            self.actor = InvoiceEvent(line, parts[1:])
        elif parts[0] == 'expect-error:':
            self.actor = ExpectErrorEvent(line, parts[1:])
        elif parts[0] == 'nothing':
            self.actor = NothingEvent(line, parts[1:])
        else:
            raise ValueError("Unknown event type {}".format(parts[0]))

    def __repr__(self):
        return "Event({}, {})".format(self.event, str(self.line))

    def flatten(self, number, stopline, prefix=''):
        # Nothing doesn't even need outputting
        if type(self.actor) == NothingEvent:
            return False, number
        return self.line.flatten(number, stopline, prefix)

    def num_steps(self):
        return 1

    def act(self, runner):
        if self.args.verbose:
            print("# running {}".format(self))
        self.actor.action(runner, self.line)


class Sequence(object):
    """Ordered sequence of Events"""
    def __init__(self, args):
        self.args = args
        self.events = []
        self.line = None

    def add_event(self, e):
        self.events.append(e)
        if self.line is None:
            self.line = copy(e.line)
        else:
            self.line += e.line

    def flatten(self, number, stopline, prefix=''):
        stop = False
        for e in self.events:
            stop, number = e.flatten(number, stopline, prefix)
            if stop:
                break
        return stop, number

    def num_steps(self):
        return sum([e.num_steps() for e in self.events])

    def __str__(self):
        return "{}".format(self.line)

    def __repr__(self):
        return "Sequence:{}".format(self)

    def run(self, runner, start=0):
        if self.args.verbose:
            print("# running {}:".format(self))
        for e in self.events[start:]:
            e.act(runner)


class OneOfEvent(object):
    """Event representing multiple possible sequences"""
    def __init__(self, args, line):
        self.line = line
        self.args = args
        self.sequences = []

    def __str__(self):
        return str(self.line)

    def flatten(self, number, stopline, prefix):
        # FIXME: if stopline is in here, we ignore it
        _, number = self.line.flatten(number, stopline, prefix)
        i = 1
        for s in self.sequences:
            _, i = s.flatten(i, stopline, '    ')
        return False, number

    def num_steps(self):
        # Use the mean of the separate sequences as a guesstimate.
        return sum([s.num_steps() for s in self.sequences]) / len(self.sequences)

    def add_sequence(self, seq):
        actor = seq.events[0].actor
        if type(actor) != ExpectSendEvent:
            # We could relax this a bit if necessary, eg 'expect-error' or
            # 'expect-tx' would be possible.
            raise LineError(seq.events[0].line,
                            "First sequence event in One Of must be expect-send")
        # They have to match on what conn the specify, too.
        if len(self.sequences) != 0:
            if actor.connkey != self.connkey:
                raise LineError(seq.events[0].line,
                                "All first sequence event in One Of must same conn=")
        else:
            self.connkey = actor.connkey
        self.sequences.append(seq)

    def act(self, runner):
        if self.args.verbose:
            print("# running {}".format(self))

        # For DummyRunner, we assume the first.
        if type(runner) == DummyRunner:
            return self.sequences[0].run(runner)

        conn = which_connection(self.line, runner, self.connkey)
        while True:
            msg = runner.expect_send(conn, self.line)
            for s in self.sequences:
                failreason = message_match(s.events[0].actor.expectmsg,
                                           s.events[0].actor.expectfields, msg)
                if failreason is None:
                    # We found the sequence, run the rest of it.
                    s.run(runner, start=1)
                    return

            if maybesend_match(conn, msg):
                continue

            raise ValidationError(self.line,
                                  "None of the sequences matched {}"
                                  .format(msg.hex()))


# Loads a Sequence at this indent level (and any children embedded in
# it, if allow_children).  Returns the initial Sequence, a list of
# Sequence leaves, and the next linenum.
def load_sequence(args, lines, linenum, indentlevel, graph):
    count = 1
    init_seq = Sequence(args)

    seq = init_seq
    terminals = [seq]

    if graph is not None:
        graph.add_node(seq)

    # We always parse one child.
    if lines[linenum].indentlevel != indentlevel:
        raise LineError(lines[linenum], "Expected {} indents.", indentlevel)
    if not lines[linenum].line.startswith('1.'):
        raise LineError(lines[linenum], "Expected 1.")

    while linenum < len(lines):
        # Unindent?  We're done.
        if lines[linenum].indentlevel < indentlevel:
            return init_seq, terminals, linenum

        # Indent?  Parse children.
        if lines[linenum].indentlevel == indentlevel + 1:
            if graph is None:
                raise LineError(lines[linenum],
                                "Cannot have indentations inside 'One of'")
            child, childterms, linenum = load_sequence(args,
                                                       lines, linenum,
                                                       indentlevel + 1, graph)

            # Attach this child to our current seq.
            if args.verbose:
                print("# child {} -> {}".format(seq, child))

            graph.add_edge(seq, child)

            # Seq is no longer terminal
            if seq in terminals:
                terminals.remove(seq)

            # These will bet attached onto the next sequence.
            terminals += childterms
            continue
        elif lines[linenum].indentlevel != indentlevel:
            raise LineError(lines[linenum], "Unexpected indent.")

        # Same level.
        parts = lines[linenum].line.partition('.')
        if parts[1] != '.':
            raise LineError(lines[linenum],
                            "Expected '{}.' or '1.'".format(count))

        # Unexpected 1. means a new start.
        if parts[0] != str(count):
            return init_seq, terminals, linenum

        if parts[2].split() == ['One', 'of:']:
            event = OneOfEvent(args, lines[linenum])

            # We expect indented sequences
            linenum += 1
            while lines[linenum].indentlevel == indentlevel + 1:
                # We don't allow sub-nodes here, so terminals will be [child]
                child, _, linenum = load_sequence(args, lines, linenum,
                                                  indentlevel + 1,
                                                  None)
                event.add_sequence(child)

            if event.sequences == []:
                raise LineError(lines[linenum],
                                "Expected indented sequences after 'One of:'")
        else:
            event = Event(args, parts[2], lines[linenum])
            linenum += 1

        # Any children from last step, start new Sequence for them to connect.
        if terminals != [seq]:
            seq = Sequence(args)
            seq.add_event(event)
            graph.add_node(seq)
            for c in terminals:
                if args.verbose:
                    print("# {} -> {}".format(c, seq))
                graph.add_edge(c, seq)
            terminals = [seq]
        else:
            seq.add_event(event)
        count += 1

    # Any children will continue from our last event(s).
    return init_seq, terminals, linenum


def run_test(args, path, runner):
    if args.verbose:
        print("## RESTART")
    runner.restart()
    runner.connections = []
    runner.expected_error = False
    for seq in path:
        seq.run(runner)

    # Make sure they didn't send any must-not-sends at the end.
    for conn in runner.connections:
        end_connection(runner, conn, path[-1].line)

    if not runner.expected_error:
        error = runner.final_error()
        if error is not None:
            raise ValidationError(None,
                                  "Unexpected error occurred: {}".format(error))


def line_minus_comments(verbose, line, linenum):
    """Strips any comment from a line, and trailing whitespace."""
    # Get the line.
    arr = line.rstrip().partition('#')
    if arr[1] == '#' and verbose:
        if arr[2] != '':
            print("# {}: {}".format(linenum, arr[2]))
    return arr[0].rstrip()


def filter_out(args, line, filename, linenum):
        """Trim options: we discard the line if it doesn't qualify."""
        while True:
            m = re.search("(?P<invert>!?)"
                          "(?P<optname>opt[A-Za-z_]*)"
                          r"(?P<oddoreven>(/(odd|even))?)\s*$", line)
            if m is None:
                return line

            if m.group('oddoreven') != '':
                present = m.group('optname') + m.group('oddoreven') in args.option
            else:
                present = (m.group('optname') + '/odd' in args.option
                           or m.group('optname') + '/even' in args.option)

            # If option was specified as --option, invert must be set.
            wanted = m.group('invert') != '!'
            if present != wanted:
                if args.verbose:
                    print("# Removing line {}: requires {}{}{}"
                          .format(Line(filename, linenum, linenum, 0, line),
                                  m.group('invert'),
                                  m.group('optname'),
                                  m.group('oddoreven')))
                return ''
            line = line[:m.start()]


def indentation(s):
    """Returns str with indent stripped, and effective indentation amount"""
    level = 0
    consumed = 0
    for i in range(len(s)):
        if s[i] == ' ':
            level += 1
        elif s[i] == '\t':
            # I keep puttiing in tabs by mistake.  Make them got to next 8.
            level = (level + 8) // 8 * 8
        else:
            break
        consumed = i + 1
    return s[consumed:], level


def parse_file(args, f, filename, variables):
    """Get non-comment lines, as [(linenums,indentlevel,line)], grab vars"""
    content = []
    lines = f.readlines()
    i = 0
    while i < len(lines):
        line_start = i

        line = line_minus_comments(args.verbose, lines[i], line_start)
        line = filter_out(args, line, filename, line_start)
        if line == '':
            i += 1
            continue

        # Store indentation level, remove it.
        line, indent = indentation(line)
        if indent % 4 != 0:
            raise LineError(Line(filename, line_start, line_start, 0, line),
                            "Indent is not a multiple of 4!")
        indentlevel = indent // 4

        i += 1
        line_end = line_start

        # Grab any continuation lines
        while i < len(lines):
            lookahead = line_minus_comments(False, lines[i], i)
            if lookahead == '':
                i += 1
                continue
            lookahead, indent = indentation(lookahead)
            # Line continuations are non-4 indent, but must be greater.
            if indent % 4 == 0:
                break
            if indent < indentlevel * 4:
                raise LineError(Line(filename, i, i, indentlevel, lines[i]),
                                "Indent is not a multiple of 4!")
            line += ' ' + filter_out(args, lookahead, filename, i)
            line_end = i
            i += 1

        # Expand variables.
        while True:
            m = re.search(r"\$(?P<varname>[A-Za-z_0-9]+)", line)
            if m is None:
                break

            if not m.group('varname') in variables:
                raise LineError(Line(filename, i, i, indentlevel, lines[i]),
                                "Unknown variable {}".format(m.group('varname')))

            line = (line[:m.start()]
                    + variables[m.group('varname')]
                    + line[m.end():])

        # Check if we're merely setting a variable; we do this now so
        # we can expand inside parse_file itself.
        parts = line.partition('=')
        if parts[1] == '=' and re.fullmatch('[A-Za-z0-9_]+', parts[0]):
            if parts[0] in variables:
                raise LineError(Line(filename, line_start, line_end,
                                     indentlevel, lines[i]),
                                "Re-setting var {}".format(parts[0]))
            variables[parts[0]] = parts[2]
        # Similarly, do include directives immediately.
        elif line.startswith('include '):
            # Filenames are assumed to be relative.
            subfilename = path.join(path.dirname(filename), line[8:])
            subf = open(subfilename)
            # This can set, and use, variables.
            sublines, variables = parse_file(args, subf, subfilename, variables)
            # Indent entire file as per this include line.
            for l in sublines:
                l.indentlevel += indentlevel
            content += sublines
        else:
            content.append(Line(filename, line_start, line_end, indentlevel,
                                line))

    return content, variables


def main(args, runner):
    read_csv(args)
    if args.verbose:
        print("# loaded {} message types".format(len(messages)))

    lines = []
    for filename in args.input:
        if filename is None:
            filename = '<stdin>'
            f = sys.stdin
        else:
            f = open(filename)

        lines, _ = parse_file(args, f, filename, {})
        f.close()

        graph = nx.DiGraph()
        root, terminals, linenum = load_sequence(args, lines, 0, 0, graph)

        # We only support one root sequence for now.
        if linenum != len(lines):
            raise LineError(lines[linenum],
                            "Unexpected lines after end of first sequence")

        if args.draw_events:
            labels = {}
            for seq in graph.nodes():
                labels[seq] = str(seq)

            nx.draw_circular(graph, labels=labels, node_size=50, font_size=4)
            plt.savefig(filename + ".png", dpi=300)

        # Edge weight == ops in sequence it leads to.  Since we walk
        # most-expensive-first, this gives maximum testing coverage to
        # first run.
        for e in graph.edges():
            graph.edges[e]['weight'] = e[1].num_steps()

        # Get all paths
        paths = []
        if args.via:
            parts = args.via.partition(':')
            if parts[1] == ':':
                filename = parts[0]
                linenum = int(parts[2])
            else:
                filename = None
                linenum = int(parts[0])
            via = None
            for seq in graph.nodes():
                if filename and seq.line.filename != filename:
                    continue
                if linenum < seq.line.linestart:
                    continue
                if linenum > seq.line.lineend:
                    continue
                via = seq
                break

            if not via:
                raise ValueError("{} not found".format(args.destination))

            path1 = nx.shortest_path(graph, root, via, 'weight')

            # Now get to any terminal.
            for t in terminals:
                try:
                    path2 = nx.shortest_path(graph, via, t, 'weight')
                    break
                except nx.exception.NetworkXNoPath:
                    pass
            paths = [path1 + path2]
        elif args.exhaustive:
            # This does the simple ones first, which is usually what
            # you want.
            for t in terminals:
                paths += nx.shortest_simple_paths(graph, root, t, 'weight')
        else:
            while any([graph.edges[e]['weight'] != 0 for e in graph.edges()]):
                for t in terminals:
                    # Start with "longest" first.  This is a super slow way
                    # to calc this!
                    path = list(nx.shortest_simple_paths(graph, root, t, 'weight'))[-1]
                    new_edge = False
                    for e in nx.utils.misc.pairwise(path):
                        if graph.edges[e]['weight'] > 0:
                            new_edge = True
                            graph.edges[e]['weight'] = 0

                    if new_edge:
                        if args.verbose:
                            print("PATH: {}".format(path))
                        paths.append(path)
                        break

        # Special case of a single sequence
        if graph.number_of_nodes() == 1:
            paths = [[root]]

        if not args.verbose:
            print("{}:{} paths: ".format(filename, len(paths)), end='', flush=True)
        for path in paths:
            try:
                run_test(args, path, runner)
            except ValidationError as v:
                print("ERROR during {}".format([p.line for p in path]), file=sys.stderr)
                if args.flatten_failpath:
                    index = 1
                    print("FAILPATH to {}:".format(v.line))
                    for p in path:
                        stop, index = p.flatten(index, v.line)
                        if stop:
                            break
                raise
            if not args.verbose:
                print('.', end='', flush=True)
        print("OK")


if __name__ == "__main__":
    parser = setup_cmdline_options()
    args = parser.parse_args()

    main(args, DummyRunner(args))
