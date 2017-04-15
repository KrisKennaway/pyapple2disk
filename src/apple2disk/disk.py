import bitstring
import hashlib
import os
import sys
import zlib

SECTOR_SIZE = 256
SECTORS_PER_TRACK = 16
# TODO: support larger disks
TRACKS_PER_DISK = 35

TRACK_SIZE = SECTORS_PER_TRACK * SECTOR_SIZE

class IOError(Exception):
    pass

class Disk(object):
    def __init__(self, name, data):
        self.name = name
        self.data = data
        # TODO: support larger disk sizes
        assert len(data) == 140 * 1024

        self.hash = hashlib.sha1(data).hexdigest()

        self.sectors = {}
        for track in xrange(TRACKS_PER_DISK):
            for sector in xrange(SECTORS_PER_TRACK):
                self.sectors[(track, sector)] = self._ReadSector(track, sector)

    def _ReadSector(self, track, sector):
        offset = track * TRACK_SIZE + sector * SECTOR_SIZE
        if sector >= SECTORS_PER_TRACK or offset > len(self.data):
            raise IOError("Track $%02x sector $%02x out of bounds" % (track, sector))

        data = bitstring.BitString(self.data[offset:offset + SECTOR_SIZE])
        return Sector(self, track, sector, data)

    def ReadSector(self, track, sector):
        try:
            return self.sectors[(track, sector)]
        except KeyError:
            raise IOError("Track $%02x sector $%02x out of bounds" % (track, sector))

    def RWTS(self):
        return self.sectors[(0,0)]


class Sector(object):
    def __init__(self, disk, track, sector, data):
        # Reference back to parent disk
        self.disk = disk

        self.track = track
        self.sector = sector

        self.data = data
        self.hash = hashlib.sha1(data.tobytes()).hexdigest()

        # Estimate entropy of disk sector
        compressed_data = zlib.compress(data.tobytes())
        self.compress_ratio = len(compressed_data) * 100 / len(data.tobytes())

    KNOWN_HASHES = {
        'b376885ac8452b6cbf9ced81b1080bfd570d9b91': 'Zero sector',
        '90e6b1a0689974743cb92ca0b833ff1e683f4a73': 'RWTS (DOS 3.3 August 1980)',
        '7ab36247fdf62e87f98d2964dd74d6572d17fff0': 'RWTS (DOS 3.3 January 1983)',
        '16e4c17a85eb321bae784ab716975ddeef6da2c6': 'RWTS (DOS 3.3 System Master)',
        '822c7450afa01f46bbc828d4d46e01bc08d73198': 'RWTS (ProntoDOS (1982))',
        '30da15678e0d70e20ecf86bcb2de3fd3874dbd0d': 'RWTS (ProntoDOS (March 1983))',
        '93d81a812d824d58dedec8f7787e9cfcc7a2d3b3': 'RWTS (Apple Pascal, Fortran)',
        'adeb3be5c3d9487a76f1917d1c28104a1a6fc72f': 'RWTS (Faster DOS 3.3?)',
        '4f4aff4e1eb8d806164544b64dc967abd76128a4': 'RWTS (ProDOS?)'
    }

    def HumanName(self):
        try:
            human_name = self.KNOWN_HASHES[self.hash]
        except KeyError:
            human_name = "Hash %s (Entropy: %d%%)" % (self.hash, self.compress_ratio)
        return human_name

    def __str__(self):
        return "Track $%02x Sector $%02x: %s" % (self.track, self.sector, self.HumanName())

def main():
    disks = {}
    for root, dirs, files in os.walk(sys.argv[1]):
        for f in files:
            if not f.lower().endswith('.dsk') and not f.lower().endswith('.do'):
                continue

            print f
            b = bytearray(open(os.path.join(root, f), 'r').read())
            try:
                disk = Disk(f, b)
                disks[f] = disk
            except IOError:
                continue
            except AssertionError:
                continue

            for ts, data in sorted(disk.sectors.iteritems()):
                print data

    # Group disks by hash of RWTS sector
    rwts_hashes = {}
    for f, d in disks.iteritems():
        rwts_hash = d.RWTS().hash
        rwts_hashes.setdefault(rwts_hash, []).append(f)

    for h, disks in rwts_hashes.iteritems():
        print h
        for d in sorted(disks):
            print "  %s" % d

if __name__ == "__main__":
    main()
