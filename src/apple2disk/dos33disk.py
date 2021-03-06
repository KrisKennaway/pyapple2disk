import anomaly
import applesoft
import container
import disk as disklib
import utils

import bitstring

class FileType(object):
    def __init__(self, short_type, long_type, parser=None):
        self.short_type = short_type
        self.long_type = long_type
        self.parser = parser

# TODO: add handlers for parsing the rest
FILE_TYPES = {
    0x00: FileType('T', 'TEXT'),
    0x01: FileType('I', 'INTEGER BASIC'),
    0x02: FileType('A', 'APPLESOFT BASIC', applesoft.AppleSoft),
    0x04: FileType('B', 'BINARY'),
    # TODO: add anomalies for these
    0x08: FileType('S', 'Type S File'),
    0x10: FileType('R', 'Relocatable object module file'),
    0x20: FileType('a', 'Type a File'),
    0x40: FileType('b', 'Type b File'),
    # TODO: unknown file type
}

class VTOCSector(disklib.Sector):
    TYPE = 'DOS 3.3 VTOC'

    def __init__(self, disk, track, sector, data):
        super(VTOCSector, self).__init__(disk, track, sector, data)
        (
            catalog_track, catalog_sector, dos_release, volume, max_track_sector_pairs,
            last_track_allocated, track_direction, tracks_per_disk, sectors_per_track,
            bytes_per_sector, freemap
        ) = data.unpack(
            'pad:8, uint:8, uint:8, uint:8, pad:16, uint:8, pad:256, uint:8, pad:64, uint:8, ' +
            'int:8, pad:16, uint:8, uint:8, uintle:16, bits:1600'
        )

        # TODO: throw a better exception here to reject the identification as a DOS 3.3 disk
        assert dos_release == 3
        assert bytes_per_sector == disklib.SECTOR_SIZE
        assert sectors_per_track == disklib.SECTORS_PER_TRACK

        # Max number of track/sector pairs which will fit in one file track/sector
    	# list sector (122 for 256 byte sectors)
        assert max_track_sector_pairs == 122

        if tracks_per_disk != disklib.TRACKS_PER_DISK:
            self.anomalies.append(
                anomaly.Anomaly(
                    self, anomaly.UNUSUAL, 'Disk has %d tracks > %d' % (
                        tracks_per_disk, disklib.TRACKS_PER_DISK)
                )
            )

        self.catalog_track = catalog_track
        self.catalog_sector = catalog_sector

        if (catalog_track, catalog_sector) != (0x11, 0x0f):
            self.anomalies.append(
                anomaly.Anomaly(
                    self, anomaly.UNUSUAL, 'Catalog begins in unusual place: T$%02X S$%02X' % (
                        catalog_track, catalog_sector)
                )
            )

        # TODO: why does DOS 3.3 sometimes display e.g. volume 254 when the VTOC says 178
        self.volume = volume

        # Process freemap
        offset = 0
        track = 0
        while offset < len(freemap):
            track_freemap = freemap[offset:offset+32]
            # Each track freemap is a 32-bit sequence where the sector order is
            # FEDCBA9876543210................

            for sector in xrange(disklib.SECTORS_PER_TRACK):
                free = track_freemap[15-sector]

                if free:
                    if track == 0:
                        self.anomalies.append(
                            anomaly.Anomaly(
                                self, anomaly.CORRUPTION,
                                'Freemap claims free sector in track 0: T$%02X S$%02X (cannot be allocated in DOS '
                                '3.3)' % (track, sector)
                            )
                        )
                        continue
                    if track >= tracks_per_disk:
                        self.anomalies.append(
                            anomaly.Anomaly(
                                self, anomaly.CORRUPTION,
                                'Freemap claims free sector beyond last track: T$%02X S$%02X' % (track, sector)
                            )
                        )
                        continue

                    old_sector = self.disk.ReadSector(track, sector)
                    # check first this is an unclaimed sector
                    # TODO: we haven't yet parsed the catalog so this won't yet have claimed the sectors.  We
                    # need to validate the freemap once everything else is done.
                    if type(old_sector) != disklib.Sector:
                        self.anomalies.append(
                            anomaly.Anomaly(
                                self, anomaly.CORRUPTION, 'VTOC claims used sector is free: %s' % old_sector
                            )
                        )

                    FreeSector.fromSector(old_sector)
                # TODO: also handle sectors that are claimed to be used but don't end up getting referenced by anything

            track += 1
            offset += 32

class CatalogSector(disklib.Sector):
    TYPE = 'DOS 3.3 Catalog'

    def __init__(self, disk, track, sector, data):
        super(CatalogSector, self).__init__(disk, track, sector, data)

        (next_track, next_sector, file_entries) = data.unpack(
            'pad:8, int:8, int:8, pad:64, bits:1960'
        )

        catalog_entries = []
        offset = 0
        while offset < len(file_entries):
            file_entry = file_entries[offset:offset+(35*8)]
            (file_track, file_sector, file_type, file_name, file_length) = file_entry.unpack(
                'uint:8, uint:8, uint:8, bytes:30, uintle:16'
            )
            if file_track and file_sector:
                entry = CatalogEntry(file_track, file_sector, file_type, file_name, file_length)
                catalog_entries.append(entry)
            offset += (35*8)

        self.next_track = next_track
        self.next_sector = next_sector
        self.catalog_entries = catalog_entries

class FileMetadataSector(disklib.Sector):

    def __init__(self, disk, track, sector, data, filename):
        super(FileMetadataSector, self).__init__(disk, track, sector, data)

        self.filename = filename
        self.TYPE = 'DOS 3.3 File Metadata (%s)' % filename

        (next_track, next_sector, sector_offset, data_sectors) = data.unpack(
            'pad:8, uint:8, uint:8, pad:16, uintle:16, pad:40, bits:1952'
        )

        offset = 0
        data_track_sectors = []
        while offset < len(data_sectors):
            ds = data_sectors[offset:offset + 16]
            (t, s) = ds.unpack(
                'uint:8, uint:8'
            )
            if t:
                # This may not be the end of the file, it can be sparse.
                data_track_sectors.append((t, s))
            # TODO: should I append a hole here if this is not the last entry?
            offset += 16

        self.next_track = next_track
        self.next_sector = next_sector
        self.sector_offset = sector_offset
        self.data_track_sectors = data_track_sectors


class FileDataSector(disklib.Sector):

    def __init__(self, disk, track, sector, data, filename):
        super(FileDataSector, self).__init__(disk, track, sector, data)

        self.filename = filename
        self.TYPE = 'DOS 3.3 File Contents (%s)' % filename


class FreeSector(disklib.Sector):
    TYPE = "DOS 3.3 Free Sector"

    def __init__(self, disk, track, sector, data):
        super(FreeSector, self).__init__(disk, track, sector, data)


class Dos33Disk(disklib.Disk):

    def __init__(self, *args, **kwargs):
        super(Dos33Disk, self).__init__(*args, **kwargs)
        # TODO: read DOS tracks and compare to known images

        self.vtoc = self._ReadVTOC()

        self.catalog_track = self.vtoc.catalog_track
        self.catalog_sector = self.vtoc.catalog_sector

        # TODO: why does DOS 3.3 sometimes display e.g. volume 254 when the VTOC says 178
        self.volume = self.vtoc.volume

        # List of stripped filenames in catalog order
        self.filenames = []

        # Maps stripped filenames to CatalogEntry objects
        self.catalog = {}

        self.ReadCatalog()

        # Maps stripped filename to File() object
        self.files = {}
        for catalog_entry in self.catalog.itervalues():
            newfile = self.ReadCatalogEntry(catalog_entry)
            # TODO: last character has special meaning for deleted files and may legitimately be whitespace.  Could collide with a non-deleted file of the same stripped name
            self.files[catalog_entry.FileName().rstrip()] = newfile

    def _ReadVTOC(self):
        return VTOCSector.fromSector(self.ReadSector(0x11, 0x0))

    def ReadCatalog(self):
        next_track = self.catalog_track
        next_sector = self.catalog_sector

        catalog = {}
        catalog_entries = []
        while next_track and next_sector:
            cs = CatalogSector.fromSector(self.ReadSector(next_track, next_sector))
            (next_track, next_sector, new_entries) = (cs.next_track, cs.next_sector, cs.catalog_entries)
            catalog_entries.extend(new_entries)

        filenames = []
        for entry in catalog_entries:
            filename = entry.FileName().rstrip()
            catalog[entry.FileName().rstrip()] = entry
            filenames.append(filename)

        self.filenames = filenames
        self.catalog = catalog

    def ReadCatalogEntry(self, entry):
        next_track = entry.track
        next_sector = entry.sector

        sector_list = [None] * entry.length
        # entry.length counts the number of data sectors as well as track/sector list sectors
        track_sector_count = 0
        while next_track and next_sector:
            track_sector_count += 1
            if next_track == 0x00:
                # This entry has never been used, skip it
                break
            if next_track == 0xff:
                # Deleted file
                # TODO: add sector type for this.  What to do about sectors claimed by this file that are in use by another file?  May discover this before or after this entry
                print "Found deleted file %s" % entry.FileName()
                break
            try:
                fs = FileMetadataSector.fromSector(self.ReadSector(next_track, next_sector), entry.FileName())
                (next_track, next_sector) = (fs.next_track, fs.next_sector)
                num_sectors = len(fs.data_track_sectors)
                sector_list[fs.sector_offset:fs.sector_offset + num_sectors] = fs.data_track_sectors
            except disklib.IOError, e:
                # TODO: add a flag indicating truncated file?
                self.anomalies.append(
                    anomaly.Anomaly(
                        self, anomaly.CORRUPTION, 'File metadata sector out of bounds for file %s: %s' % (
                            entry.FileName(), e)
                    )
                )
                (next_track, next_sector) = (None, None)

        # TODO: Assert we didn't have any holes.  Or is this fine e.g. for a sparse text file?

        # We allocated space up-front for an unknown number of t/s list sectors, trim them from the end
        sector_list = sector_list[:entry.length - track_sector_count]

        contents = bitstring.BitString()
        for ts in sector_list:
            if not ts:
                #print "XXX found a sparse sector?"
                continue
            (t, s) = ts
            try:
                fds = FileDataSector.fromSector(self.ReadSector(t, s), entry.FileName())
            except disklib.IOError, e:
                self.anomalies.append(
                    anomaly.Anomaly(
                        self, anomaly.CORRUPTION, 'File data sector out of bounds for file %s: %s' % (
                            entry.FileName(), e)
                    )
                )
                continue
            contents.append(fds.data)

        newfile = File(entry, contents)
        self.AddChild(newfile)
        return newfile

    def Catalog(self):
        catalog = ['DISK VOLUME %d\n' % self.volume]
        for filename in self.filenames:
            entry = self.catalog[filename]
            file_type = entry.file_type.short_type
            catalog.append(
                '%s%s %03d %s' % (
                    '*' if entry.locked else ' ',
                    file_type, entry.length,
                    entry.FileName()
                )
            )
        return '\n'.join(catalog)

    def __str__(self):
        return '%s (DOS 3.3 disk)' % (self.name)


class CatalogEntry(container.Container):
    def __init__(self, track, sector, file_type, file_name, length):
        super(CatalogEntry, self).__init__()

        self.track = track
        self.sector = sector
        # TODO: add anomaly for unknown file type
        self.file_type = FILE_TYPES[file_type & 0x7f]
        self.locked = bool(file_type & 0x80)
        self.file_name = file_name
        self.length = length
        # TODO: handle deleted files (track = 0xff, original track in file_name[0x20])

    def FileName(self):
        return '%s' % ''.join([chr(ord(b) & 0x7f) for b in self.file_name])

    def __str__(self):
        type_string = self.file_type.long_type
        if self.locked:
            type_string += ' (LOCKED)'
        return "Track $%02x Sector $%02x Type %s Name: %s Length: %d" % (self.track, self.sector, type_string, self.FileName(), self.length)


class File(container.Container):
    def __init__(self, catalog_entry, contents):
        super(File, self).__init__()

        self.catalog_entry = catalog_entry

        self.contents = contents
        self.parsed_contents = None

        parser = catalog_entry.file_type.parser
        if parser:
            try:
                self.parsed_contents = parser(catalog_entry.FileName(), contents)
                self.AddChild(self.parsed_contents)
            except Exception, e:
                self.anomalies.append(
                    anomaly.Anomaly(
                        self, anomaly.CORRUPTION, 'Failed to parse file %s: %s' % (self.catalog_entry, e)
                    )
                )

    def __str__(self):
        return 'File(%s)' % self.catalog_entry.FileName()