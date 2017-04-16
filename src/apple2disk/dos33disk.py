import applesoft
import bitstring
import disk as disklib
import string

PRINTABLE = set(string.letters + string.digits + string.punctuation + ' ')

class FileType(object):
    def __init__(self, short_type, long_type, parser=None):
        self.short_type = short_type
        self.long_type = long_type
        self.parser = parser

FILE_TYPES = {
    0x00: FileType('T', 'TEXT'),
    0x01: FileType('I', 'INTEGER BASIC'),
    # TODO: add handler for parsing file content
    0x02: FileType('A', 'APPLESOFT BASIC', applesoft.AppleSoft),
    0x04: FileType('B', 'BINARY'),
    # TODO: others
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

        self.catalog_track = catalog_track
        self.catalog_sector = catalog_sector

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
                    old_sector = self.disk.ReadSector(track, sector)
                    # check first this is an unclaimed sector
                    assert type(old_sector) == disklib.Sector
                    FreeSector.fromSector(old_sector)
                # TODO: also handle sectors that are claimed to be used but don't end up getting referenced by anything

            if track == tracks_per_disk:
                break
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
            # TODO: last character has special meaning for deleted files and may legitimately be whitespace.  Could collide with a non-deleted file of the same stripped name
            self.files[catalog_entry.FileName().rstrip()] = self.ReadCatalogEntry(catalog_entry)

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
            fs = FileMetadataSector.fromSector(self.ReadSector(next_track, next_sector), entry.FileName())
            (next_track, next_sector) = (fs.next_track, fs.next_sector)

            num_sectors = len(fs.data_track_sectors)
            sector_list[fs.sector_offset:fs.sector_offset+num_sectors] = fs.data_track_sectors

        # TODO: Assert we didn't have any holes.  Or is this fine e.g. for a sparse text file?

        #print track_sector_count
        # We allocated space up-front for an unknown number of t/s list sectors, trim them from the end
        sector_list = sector_list[:entry.length - track_sector_count]

        #print sector_list
        contents = bitstring.BitString()
        for ts in sector_list:
            if not ts:
                #print "XXX found a sparse sector?"
                continue
            (t, s) = ts
            fds = FileDataSector.fromSector(self.ReadSector(t, s), entry.FileName())
            contents.append(fds.data)

        return File(entry, contents)

    def __str__(self):
        catalog = ['DISK VOLUME %d\n' % self.volume]
        for filename in self.catalog:
            entry = self.files[filename]
            try:
                file_type = FILE_TYPES[entry.file_type].short_type
            except KeyError:
                print "%s has unknown file type %02x" % (entry.FileName(), entry.file_type)
                file_type = '?'
            catalog.append(
                '%s%s %03d %s' % (
                    '*' if entry.locked else ' ',
                    file_type, entry.length,
                    entry.FileName()
                )
            )
        return '\n'.join(catalog)


class CatalogEntry(object):
    def __init__(self, track, sector, file_type, file_name, length):
        self.track = track
        self.sector = sector
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


class File(object):
    def __init__(self, catalog_entry, contents):
        self.catalog_entry = catalog_entry

        self.contents = contents
        parser = catalog_entry.file_type.parser
        if parser:
            self.parsed_contents = parser(contents)
        else:
            self.parsed_contents = None