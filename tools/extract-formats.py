#! /usr/bin/python3
# Simple script to parse specs and produce CSV files.
# Released by Rusty Russell under CC0:
# https://creativecommons.org/publicdomain/zero/1.0/

from optparse import OptionParser
import sys
import re
import fileinput


def main(options, args=None, output=sys.stdout, lines=None):
    # Example inputs:
    # 1. type: 17 (`error`) (`optionXXX`)
    # 2. data:
    #    * [`8`:`channel_id`]
    #    * [`4`:`len`]
    #    * [`len`:`data`] (optionXXX)
    #
    # 1. type: PERM|NODE|3 (`required_node_feature_missing`)
    message = None
    havedata = None
    typeline = re.compile(
        '1\. type: (?P<value>[-0-9A-Za-z_|]+) \(`(?P<name>[A-Za-z_]+)`\)( \(`?(?P<option>[^)`]*)`?\))?')
    dataline = re.compile(
        '\s+\* \[`(?P<size>[_a-z0-9*+]+)`:`(?P<name>[_a-z0-9]+)`\]( \(`?(?P<option>[^)`]*)`?\))?')

    if lines is None:
        lines = fileinput.input(args)

    for i, line in enumerate(lines):
        line = line.rstrip()
        linenum = i+1

        match = typeline.fullmatch(line)
        if match:
            if message is not None:
                raise ValueError('{}:Found a message while I was already in a '
                                 'message'.format(linenum))
            message = match.group('name')
            if options.output_types:
                print("{},{}".format(
                    match.group('name'),
                    match.group('value')), file=output)
            havedata = None
        elif message is not None and havedata is None:
            if line != '2. data:':
                message = None
            havedata = True
            dataoff = 0
            off_extraterms = ""
        elif message is not None and havedata is not None:
            match = dataline.fullmatch(line)
            if match:
                if options.output_fields:
                    print("{},{}{},{},{}".format(
                        message,
                        dataoff,
                        off_extraterms,
                        match.group('name'),
                        match.group('size')), file=output, end='')
                    if match.group('option'):
                        print(",{}".format(match.group('option')), file=output)
                    else:
                        print('', file=output)

                # Size can be variable.
                try:
                    dataoff += int(match.group('size'))
                except ValueError:
                    # Offset has variable component.
                    off_extraterms = off_extraterms + "+" + match.group('size')
            else:
                message = None


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option(
        "--message-types",
        action="store_true",
        dest="output_types",
        default=False,
        help="Output MESSAGENAME,VALUE for every message"
    )
    parser.add_option(
        "--message-fields",
        action="store_true",
        dest="output_fields",
        default=False,
        help="Output MESSAGENAME,OFFSET,FIELDNAME,SIZE for every message"
    )

    (options, args) = parser.parse_args()

    main(options, args)
