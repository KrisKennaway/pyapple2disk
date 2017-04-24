import disk
import dos33disk
import os
import sys

def main():
    disks = {}
    for root, dirs, files in os.walk(sys.argv[1]):
        for f in files:
            if not f.lower().endswith('.dsk') and not f.lower().endswith('.do'):
                continue

            print f

            b = bytearray(open(os.path.join(root, f), 'r').read())
            try:
                img = disk.Disk(f, b)
            except IOError:
                continue
            except AssertionError:
                continue

            # See if this is a DOS 3.3 disk
            try:
                img = dos33disk.Dos33Disk.Taste(img)
                print "%s is a DOS 3.3 disk, volume %d" % (f, img.volume)

                for fn in img.filenames:
                    f = img.files[fn]

                    print f.catalog_entry
                    if f.parsed_contents:
                        print f.parsed_contents

            except IOError:
                pass
            except AssertionError:
                pass

            disks[f] = img

            for ts, data in sorted(img.sectors.iteritems()):
                print data


    # Group disks by hash of boot1 sector
    boot1_hashes = {}
    for f, d in disks.iteritems():
        boot1_hash = d.Boot1.hash
        boot1_hashes.setdefault(boot1_hash, []).append(f)

    for h, disks in boot1_hashes.iteritems():
        print h
        for d in sorted(disks):
            print "  %s" % d

if __name__ == "__main__":
    main()
