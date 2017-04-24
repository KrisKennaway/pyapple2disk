import container

import bitstring
import hashlib
import zlib

SECTOR_SIZE = 256
SECTORS_PER_TRACK = 16
# TODO: support larger disks
TRACKS_PER_DISK = 35

TRACK_SIZE = SECTORS_PER_TRACK * SECTOR_SIZE

class IOError(Exception):
    pass

class Disk(container.Container):
    def __init__(self, name, data):
        super(Disk, self).__init__()

        self.name = name
        self.data = data

        # TODO: support larger disk sizes
        assert len(data) == 140 * 1024

        self.hash = hashlib.sha1(data).hexdigest()

        self.sectors = {}
        # Pre-load all sectors into map
        for (track, sector) in self.EnumerateSectors():
            self._ReadSector(track, sector)

        # Assign ownership of T0, S0 to boot1
        self.boot1 = Boot1.fromSector(self.ReadSector(0, 0))

    @classmethod
    def Taste(cls, disk):
        # TODO: return a defined exception here
        newdisk = cls(disk.name, disk.data)
        disk.AddChild(newdisk)
        return newdisk

    def SetSectorOwner(self, track, sector, owner):
        self.sectors[(track, sector)] = owner

    def EnumerateSectors(self):
        for track in xrange(TRACKS_PER_DISK):
            for sector in xrange(SECTORS_PER_TRACK):
                yield (track, sector)

    def _ReadSector(self, track, sector):
        offset = track * TRACK_SIZE + sector * SECTOR_SIZE
        if sector >= SECTORS_PER_TRACK or offset > len(self.data):
            raise IOError("Track $%02x sector $%02x out of bounds" % (track, sector))

        data = bitstring.BitString(self.data[offset:offset + SECTOR_SIZE])

        # This calls SetSectorOwner to register in self.sectors
        return Sector(self, track, sector, data)

    def ReadSector(self, track, sector):
        # type: (int, int) -> Sector
        try:
            return self.sectors[(track, sector)]
        except KeyError:
            raise IOError("Track $%02x sector $%02x out of bounds" % (track, sector))


class Sector(container.Container):
    # TODO: other types will include: VTOC, Catalog, File metadata, File content, Deleted file, Free space
    TYPE = 'Unknown sector'

    def __init__(self, disk, track, sector, data):
        super(Sector, self).__init__()
        # Reference back to parent disk
        self.disk = disk

        self.track = track
        self.sector = sector

        self.data = data
        self.hash = hashlib.sha1(data.tobytes()).hexdigest()

        # Estimate entropy of disk sector
        compressed_data = zlib.compress(data.tobytes())
        self.compress_ratio = len(compressed_data) * 100 / len(data.tobytes())

        disk.SetSectorOwner(track, sector, self)
        disk.AddChild(self)

    # TODO: if all callers are using disk.ReadSector(track, sector) to get the sector then do that here
    @classmethod
    def fromSector(cls, sector, *args, **kwargs):
        """Create and register a new Sector from an existing Sector object."""
        # TODO: don't recompute hash and entropy
        return cls(sector.disk, sector.track, sector.sector, sector.data, *args, **kwargs)

    # TOOD: move boot1 ones into Boot1() class?
    KNOWN_HASHES = {
        'b376885ac8452b6cbf9ced81b1080bfd570d9b91': 'Zero sector',
        '90e6b1a0689974743cb92ca0b833ff1e683f4a73': 'Boot1 (DOS 3.3 August 1980)',
        '7ab36247fdf62e87f98d2964dd74d6572d17fff0': 'Boot1 (DOS 3.3 January 1983)',
        '16e4c17a85eb321bae784ab716975ddeef6da2c6': 'Boot1 (DOS 3.3 System Master)',
        '822c7450afa01f46bbc828d4d46e01bc08d73198': 'Boot1 (ProntoDOS (1982))',
        '30da15678e0d70e20ecf86bcb2de3fd3874dbd0d': 'Boot1 (ProntoDOS (March 1983))',
        '93d81a812d824d58dedec8f7787e9cfcc7a2d3b3': 'Boot1 (Apple Pascal, Fortran)',
        'adeb3be5c3d9487a76f1917d1c28104a1a6fc72f': 'Boot1 (Faster DOS 3.3?)',
        '4f4aff4e1eb8d806164544b64dc967abd76128a4': 'Boot1 (ProDOS?)'
    }

    def HumanName(self):
        try:
            human_name = self.KNOWN_HASHES[self.hash]
        except KeyError:
            human_name = "Hash %s (Entropy: %d%%)" % (self.hash, self.compress_ratio)
        return human_name

    def __str__(self):
        return "Track $%02x Sector $%02x: %s (%s)" % (self.track, self.sector, self.TYPE, self.HumanName())


class Boot1(Sector):
    TYPE = "Boot1"

    def __init__(self, disk, track, sector, data):
        super(Boot1, self).__init__(disk, track, sector, data)