import string

PRINTABLE = set(string.letters + string.digits + string.punctuation + ' ')

def HexDump(data):
    line = []
    for idx, b in enumerate(data):
        if idx % 8 == 0:
            print '$%02x:  ' % idx,
        print "%02x" % ord(b),
        if b in PRINTABLE:
            line.append(b)
        else:
            line.append('.')
        if (idx + 1) % 8 == 0:
            print "    %s" % ''.join(line)
            line = []
