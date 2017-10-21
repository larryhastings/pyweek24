import sys
from xml.etree.ElementTree import parse

FIX_ATTRS = ('x', 'y', 'rotation')


def walk(element):
    updates = {}
    for k, v in element.attrib.items():
        if k in FIX_ATTRS:
            try:
                v = int(v)
            except ValueError:
                v = str(int(float(v)))
                updates[k] = v
    element.attrib.update(updates)
    for child in element:
        walk(child)


def fix(filename):
    with open(filename) as f:
        doc = parse(f)
    walk(doc.getroot())

    with open(filename + '.new', 'wb') as f:
        doc.write(f)


if __name__ == '__main__':
    fix(sys.argv[1])
