from io import StringIO
import glob
import collections
import json

formats = __import__("extract-formats")


class Options(object):
    output_types = True
    output_fields = True
    check_alignment = False


options = Options()
csv = []

output = StringIO()
for i in sorted(glob.glob("../??-*.md")):
    with open(i) as f:
        formats.main(options, output=output, lines=f.readlines())
        csvstr = output.getvalue().strip()
        if csvstr == "":
            continue
        csv += csvstr.split("\n")

resmap = collections.OrderedDict()

currentmsgname = None
currentmsgfields = {}
typenum = None
for line in csv:
    parts = line.split(",")
    if len(parts) == 2:
        if currentmsgname is not None:
            resmap[currentmsgname] = collections.OrderedDict(
                [("type", typenum), ("payload", currentmsgfields)])
        currentmsgfields = collections.OrderedDict()
        currentmsgname = parts[0]
        typenum = parts[1]
        continue
    assert currentmsgname == parts[0], line
    assert len(parts) == 4, line
    position = parts[1]
    length = parts[3]
    fieldname = parts[2]
    currentmsgfields[fieldname] = {"position": position, "length": length}

if __name__ == "__main__":
    print(json.dumps(resmap, indent=True))
