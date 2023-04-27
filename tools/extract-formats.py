#! /usr/bin/python3
# Simple script to parse specs and produce CSV files.
# Released by Rusty Russell under CC0:
# https://creativecommons.org/publicdomain/zero/1.0/

# Outputs:
#
# Standard message types:
#   msgtype,<msgname>,<value>
#   msgdata,<msgname>,<fieldname>,<typename>,[<count>]
#
# TLV types:
#   tlvtype,<tlvstreamname>,<tlvname>,<value>
#   tlvdata,<tlvstreamname>,<tlvname>,<fieldname>,<typename>,[<count>]
#
# Subtypes:
#   subtype,<msgname>
#   subtypedata,<msgname>,<fieldname>,<typename>,[<count>]

from optparse import OptionParser
import sys
import re
import fileinput

# We allow either ordered or unordered lists.
typeline = re.compile(
    '(1\.|\*) type: (?P<value>[-0-9A-Za-z_|]+) \(`(?P<name>[A-Za-z0-9_]+)`\)( \(`?(?P<option>[^)`]*)`\))?')
tlvline = re.compile(
    '(1\.|\*) `tlv_stream`: `(?P<name>[A-Za-z0-9_]+)`')
subtypeline = re.compile(
    '(1\.|\*) subtype: `(?P<name>[A-Za-z0-9_]+)`')
dataline = re.compile(
    '\s+([0-9]+\.|\*) \[`(?P<typefield>[-._a-zA-Z0-9*+]+)`:`(?P<name>[_a-z0-9]+)`\]')
datastartline = re.compile(
    '(2\.|\*) data:')
tlvtypesline = re.compile(
    '(2\.|\*) types:')

# Generator to give us one line at a time.
def next_line(args, lines):
    if lines is None:
        lines = fileinput.input(args)

    for i, line in enumerate(lines):
        yield i, line.rstrip()


# Helper to print a line to output
def print_csv(output, fmt):
    print(fmt, file=output)


# 1. type: 17 (`error`) (`optionXXX`)
# 2. data:
#    * [`short_channel_id`:`channel_id`]
#    * [`u16`:`num_inputs`]
#    * [`num_inputs*sha256`:`input_info`]
#    * [`u32`:`len`]
#    * [`len*byte`:`data`]
#
# output:
#   msgtype,error,17,optionXXX
#   msgdata,error,channel_id,short_channel_id,
#   msgdata,error,num_inputs,u16,
#   msgdata,error,input_info,sha256,num_inputs
#   msgdata,error,len,u32,
#   msgdata,error,data,byte,len
#
# 1. type: PERM|NODE|3 (`required_node_feature_missing`)
#
# output:
#   msgtype,required_node_feature_missing,PERM|NODE|3
#
# 1. type: 261 (`query_short_channel_ids`) (`gossip_queries`)
# 2. data:
#     * [`chain_hash`:`chain_hash`]
#     * [`u16`:`len`]
#     * [`len*byte`:`encoded_short_ids`]
#     * [`query_short_channel_ids_tlvs`:`tlvs`]
#
# output:
#   msgtype,query_short_channel_ids,261,gossip_queries
#   msgdata,query_short_channel_ids,chain_hash,chain_hash,
#   msgdata,query_short_channel_ids,len,u16,
#   msgdata,query_short_channel_ids,encoded_short_ids,byte,len
#   msgdata,query_short_channel_ids,tlvs,query_short_channel_ids_tlvs,
def parse_type(genline, output, name, value, in_tlv=None):
    _, line = next(genline)

    if in_tlv:
        type_prefix='tlvtype,{}'.format(in_tlv)
        data_prefix='tlvdata,{}'.format(in_tlv)
    else:
        type_prefix='msgtype'
        data_prefix='msgdata'

    print_csv(output, '{},{},{}'.format(type_prefix, name, value))

    # Expect a data: line before values, if any
    if not datastartline.fullmatch(line.lstrip()):
        return _, line

    while True:
        i, line = next(genline)
        match = dataline.fullmatch(line)
        if not match:
            return _, line

        if '*' in match.group('typefield'):
            num,typename = match.group('typefield').split('*')
        else:
            num,typename = ("", match.group('typefield'))

        print_csv(output,
                  "{},{},{},{},{}"
                  .format(data_prefix, name, match.group('name'), typename, num))

    
# 1. tlvs: `query_short_channel_ids_tlvs`
# 2. types:
#    1. type: 1 (`query_flags`)
#    2. data:
#      * [`byte`:`encoding_type`]
#      * [`...*byte`:`encoded_query_flags`]
#
# output:
#  tlvtype,query_short_channel_ids_tlvs,query_flags,1
#  tlvdata,query_short_channel_ids_tlvs,query_flags,encoding_type,byte,
#  tlvdata,query_short_channel_ids_tlvs,query_flags,encoded_query_flags,byte,...
def parse_tlv(genline, output, name):
    i, line = next(genline)

    # Expect a types: line after tlvs.
    if not tlvtypesline.fullmatch(line):
        raise ValueError('{}: Expected "2. types:" line'.format(i))

    _, line = next(genline)
    while True:
        # Inside tlv, types are indented.
        match = typeline.fullmatch(line.lstrip())
        if not match:
            break

        _, line = parse_type(genline, output, match.group('name'), match.group('value'), name)

    
# 1. subtype: `input_info`
# 2. data:
#    * [`u64`:`satoshis`]
#    * [`sha256`:`prevtx_txid`]
#
# output:
#  subtype,input_info
#  subtypedata,input_info,satoshis,u64,
#  subtypedata,input_info,prevtx_txid,sha256,

def parse_subtype(genline, output, name):
    i, line = next(genline)

    # Expect a data: line after subtype.
    if not datastartline.fullmatch(line):
        raise ValueError('{}: Expected "2. data:" line'.format(i))

    print_csv(output, 'subtype,{}'.format(name))

    while True:
        i, line = next(genline)
        match = dataline.fullmatch(line)
        if not match:
            break

        if '*' in match.group('typefield'):
            num,typename = match.group('typefield').split('*')
        else:
            num,typename = ("", match.group('typefield'))

        print_csv(output,
                  "{},{},{},{},{}"
                  .format('subtypedata', name, match.group('name'), typename, num))

    
def main(options, args=None, output=sys.stdout, lines=None):
    genline = next_line(args, lines)
    try:
        while True:
            _, line = next(genline)

            match = typeline.fullmatch(line)
            if match:
                parse_type(genline, output, match.group('name'), match.group('value'))
                continue
            match = tlvline.fullmatch(line)
            if match:
                parse_tlv(genline, output, match.group('name'))
                continue
            match = subtypeline.fullmatch(line)
            if match:
                parse_subtype(genline, output, match.group('name'))
                continue
    except StopIteration:
        pass

if __name__ == "__main__":
    parser = OptionParser()
    (options, args) = parser.parse_args()

    main(options, args)
