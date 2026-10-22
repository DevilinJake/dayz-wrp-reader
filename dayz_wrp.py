"""Reader for DayZ Standalone binarized terrain files (OPRW version 32).

Reverse-engineered from the public Arma 3 OPRW v24/25 layout
(community.bistudio.com, Braini01/bis-file-formats, gruppe-adler/grad_aff)
plus the differences found in DayZ's chernarusplus.wrp / enoch.wrp:

  * header: "OPRW", u32 version(32), 4-byte tag "0FNE", u8 1, u32 0,
            then the usual layerSizeX/Y, mapSizeX/Y, f32 layerCellSize
  * the grass / primary-texture byte arrays are replaced by one
    LZO block (u32 decompressedSize + LZO1X stream) holding an "ENFI"
    tiled 4-bit grid
  * classed models carry an extra u32 flags field after the object id
  * road parts carry the same extra u32 after the object id
  * objects are 64 bytes (an extra u32 after shapeParam)
  * map-info types 38 and 42 are 16 and 44 bytes respectively

Usage:
    from dayz_wrp import Wrp
    w = Wrp.load(r"...\\chernarusplus.wrp")
    w.elevation          # numpy float32 [mapSizeY, mapSizeX], row 0 = south
    w.objects            # numpy structured array (id, model, m[12], shape, extra)
    w.models[w.objects['model']]  # model path per object
"""
import struct
import numpy as np
import lzo1x

OBJECT_DTYPE = np.dtype([('id', '<u4'), ('model', '<u4'), ('m', '<f4', (12,)),
                         ('shape', '<u4'), ('extra', '<u4')])

# map-info record layouts (id -> (fixed byte size after the u32 id, kind))
MAPINFO_T1 = {0, 1, 2, 10, 11, 12, 13, 14, 15, 16, 17, 22, 23, 26, 27, 30, 36, 38, 39, 40}  # objId, x, y
MAPINFO_T2 = {24, 31, 32}                                                         # objId, 4 corners
MAPINFO_T3 = {25, 33}                                                             # color, indicator, 4 floats
MAPINFO_T4 = {3, 4, 8, 9, 18, 19, 20, 21, 28, 29, 37, 41, 42, 43}                 # objId, 4 corners, rgba
MAPINFO_NAMES = {
    0: 'tree', 1: 'small tree', 2: 'bush', 3: 'building', 4: 'house', 8: 'forest border',
    9: 'forest triangle', 10: 'rock', 11: 'bush hard', 12: 'fountain', 13: 'view tower',
    14: 'lighthouse', 15: 'quay', 16: 'fuel station', 17: 'hospital', 18: 'fence', 19: 'wall',
    20: 'hide', 21: 'busstop', 22: 'road', 23: 'forest', 24: 'transmitter', 25: 'stack',
    26: 'ruin', 27: 'tourism', 28: 'watertower', 29: 'track', 30: 'main road', 31: 'rocks',
    32: 'power lines', 33: 'rail road', 34: 'power solar', 35: 'power wave', 36: 'power wind',
    37: 'shipwreck', 38: 'chapel', 39: 'church', 41: 'cross', 42: 'rock', 43: 'bunker',
    44: 'river',
}


class Reader:
    def __init__(self, data):
        self.d = data
        self.pos = 0

    def u8(self):
        v = self.d[self.pos]; self.pos += 1; return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.pos)[0]; self.pos += 2; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.pos)[0]; self.pos += 4; return v

    def f32(self):
        v = struct.unpack_from('<f', self.d, self.pos)[0]; self.pos += 4; return v

    def floats(self, n):
        v = struct.unpack_from('<%df' % n, self.d, self.pos); self.pos += 4 * n; return v

    def bytes(self, n):
        v = self.d[self.pos:self.pos + n]; self.pos += n; return v

    def asciiz(self):
        e = self.d.index(b'\0', self.pos)
        v = self.d[self.pos:e].decode('latin1')
        self.pos = e + 1
        return v

    def compressed(self, expected):
        """Arma 'compressed' array: raw if < 1024 bytes, else LZO1X."""
        if expected == 0:
            return b''
        if expected < 1024:
            return self.bytes(expected)
        out, self.pos = lzo1x.decompress(self.d, self.pos, expected)
        return out

    def quadtree(self, size_x, size_y, elem_size, dtype):
        """Decode a packed quad tree into a numpy grid [size_y, size_x]."""
        # virtual (power-of-4) dimensions, as in BIS.Core.QuadTree
        def log2ceil(n):
            n -= 1; l = 0
            while n:
                l += 1; n >>= 1
            return l
        leaf_lx, leaf_ly = {1: (1, 1), 2: (1, 0), 4: (0, 0)}[elem_size]
        lx, ly = log2ceil(size_x), log2ceil(size_y)
        levels = max((lx - leaf_lx + 1) // 2, (ly - leaf_ly + 1) // 2)
        tot_lx, tot_ly = levels * 2 + leaf_lx, levels * 2 + leaf_ly
        tot_x, tot_y = 1 << tot_lx, 1 << tot_ly
        grid = np.zeros((tot_y, tot_x), dtype=dtype)
        leaf_w, leaf_h = 1 << leaf_lx, 1 << leaf_ly

        def leaf(x0, y0, w, h):
            raw = self.d[self.pos:self.pos + 4]; self.pos += 4
            vals = np.frombuffer(raw, dtype=dtype).reshape(leaf_h, leaf_w)
            if w == leaf_w and h == leaf_h:
                grid[y0:y0 + h, x0:x0 + w] = vals
            else:
                grid[y0:y0 + h, x0:x0 + w] = np.tile(vals, (h // leaf_h, w // leaf_w))

        def node(x0, y0, w, h):
            flag = self.u16()
            cw, ch = w // 4, h // 4
            for i in range(16):
                ix, iy = i & 3, i >> 2
                if (flag >> i) & 1:
                    node(x0 + ix * cw, y0 + iy * ch, cw, ch)
                else:
                    leaf(x0 + ix * cw, y0 + iy * ch, cw, ch)

        root_is_node = self.u8()
        if root_is_node:
            node(0, 0, tot_x, tot_y)
        else:
            leaf(0, 0, tot_x, tot_y)
        return grid[:size_y, :size_x].copy()


class Enfi:
    """The 'ENFI' tiled 4-bit grid stored in DayZ wrp files (replaces the
    Arma grass / primary-texture arrays). grid[z, x] holds one nibble per
    terrain cell: the 1-based slot of the dominant surface layer in the
    cell's rvmat name (material_index -> materials, e.g. 'p_000-000_l01_l03_l04_n_l10'
    with value 3 means layer l04). Tiles that are absent (open sea) are 0."""
    TILE = 64

    def __init__(self, blob):
        magic, version, self.width, self.height, self.unknown, self.tile_count, u1, u2 = \
            struct.unpack_from('<4sIIIIIII', blob, 0)
        if magic != b'ENFI':
            raise ValueError('bad ENFI magic %r' % magic)
        self.version = version
        self.unknown2 = (u1, u2)
        tx, ty = self.width // self.TILE, self.height // self.TILE
        pos = 32
        self.tile_table = np.frombuffer(blob, dtype=np.uint8, count=tx * ty, offset=pos).reshape(ty, tx)
        pos += tx * ty
        bits_bytes = (tx * ty + 7) // 8
        self.tile_bits = np.unpackbits(np.frombuffer(blob, dtype=np.uint8, count=bits_bytes, offset=pos),
                                       bitorder='little')[:tx * ty].reshape(ty, tx)
        pos += bits_bytes
        tile_bytes = self.TILE * self.TILE // 2
        self.grid = np.zeros((self.height, self.width), dtype=np.uint8)
        n = 0
        for j in range(ty):
            for i in range(tx):
                if self.tile_table[j, i]:
                    raw = np.frombuffer(blob, dtype=np.uint8, count=tile_bytes, offset=pos)
                    pos += tile_bytes
                    n += 1
                    lo = raw & 0x0f
                    hi = raw >> 4
                    cells = np.empty(self.TILE * self.TILE, dtype=np.uint8)
                    cells[0::2] = lo
                    cells[1::2] = hi
                    self.grid[j * self.TILE:(j + 1) * self.TILE, i * self.TILE:(i + 1) * self.TILE] = \
                        cells.reshape(self.TILE, self.TILE)
        if n != self.tile_count or pos != len(blob):
            raise ValueError('ENFI size mismatch: %d tiles, %d of %d bytes' % (n, pos, len(blob)))


class Wrp:
    @classmethod
    def load(cls, path, want_objects=True, want_mapinfo=True, want_roads=True, progress=print):
        with open(path, 'rb') as f:
            data = f.read()
        return cls(data, want_objects, want_mapinfo, want_roads, progress)

    def __init__(self, data, want_objects=True, want_mapinfo=True, want_roads=True, progress=print):
        r = Reader(data)
        log = progress or (lambda *a: None)
        if r.bytes(4) != b'OPRW':
            raise ValueError('not an OPRW file')
        self.version = r.u32()
        if self.version != 32:
            raise ValueError('only OPRW version 32 (DayZ) is supported, got %d' % self.version)
        self.tag = r.bytes(4)            # b'0FNE'
        self.hdr_flag = r.u8()           # 1
        self.hdr_unknown = r.u32()       # 0
        self.layer_x, self.layer_y = r.u32(), r.u32()
        self.map_x, self.map_y = r.u32(), r.u32()
        self.layer_cell_size = r.f32()
        self.cell_size = self.layer_cell_size * self.layer_x / self.map_x
        self.world_size = self.layer_cell_size * self.layer_x
        L, M = self.layer_x * self.layer_y, self.map_x * self.map_y

        log('geography / sound / material grids')
        self.geography = r.quadtree(self.layer_x, self.layer_y, 2, np.dtype('<u2'))
        self.sound_map = r.quadtree(self.layer_x, self.layer_y, 1, np.uint8)
        n = r.u32()
        self.peaks = np.frombuffer(r.bytes(12 * n), dtype='<f4').reshape(n, 3).copy()
        self.material_index = r.quadtree(self.layer_x, self.layer_y, 2, np.dtype('<u2'))

        log('ENFI surface grid')
        size = r.u32()
        self.enfi = Enfi(r.compressed(size))

        log('elevation')
        self.elevation = np.frombuffer(r.compressed(M * 4), dtype='<f4').reshape(self.map_y, self.map_x).copy()

        n = r.u32()
        self.materials = []
        for i in range(n):
            name = r.asciiz(); flag = r.u8()
            self.materials.append(name)
        n = r.u32()
        self.models = np.array([r.asciiz() for i in range(n)], dtype=object)

        log('classed models')
        n = r.u32()
        cm = []
        for i in range(n):
            cls_name = r.asciiz(); model = r.asciiz()
            x, y, z = r.floats(3)
            oid = r.u32(); flags = r.u32()
            cm.append((cls_name, model, x, y, z, oid, flags))
        self.classed_models = cm

        self.object_offsets = r.quadtree(self.layer_x, self.layer_y, 4, np.dtype('<u4'))
        size_objects = r.u32()
        self.map_object_offsets = r.quadtree(self.layer_x, self.layer_y, 4, np.dtype('<u4'))
        size_mapinfo = r.u32()
        self.mapinfo_size = size_mapinfo
        self.persistent = np.frombuffer(r.compressed(L), dtype=np.uint8).reshape(self.layer_y, self.layer_x).copy()
        self.subdiv_hints = np.frombuffer(r.compressed(M), dtype=np.uint8).reshape(self.map_y, self.map_x).copy()
        self.max_object_id = r.u32()
        size_roadnet = r.u32()

        log('road network')
        road_start = r.pos
        self.roads = []          # (cell_index, [(x,y,z)...], [types...], object_id, flags, p3d, matrix12)
        if want_roads:
            for cell in range(L):
                nparts = r.u32()
                for j in range(nparts):
                    npos = r.u16()
                    pts = np.frombuffer(r.bytes(12 * npos), dtype='<f4').reshape(npos, 3).copy()
                    types = r.bytes(npos)
                    oid = r.u32(); flags = r.u32()
                    p3d = r.asciiz()
                    m = r.floats(12)
                    self.roads.append((cell, pts, bytes(types), oid, flags, p3d, m))
            if r.pos != road_start + size_roadnet:
                raise ValueError('road net size mismatch')
        r.pos = road_start + size_roadnet

        log('objects')
        if size_objects % OBJECT_DTYPE.itemsize:
            raise ValueError('object block not a multiple of 64 bytes')
        n = size_objects // OBJECT_DTYPE.itemsize
        if want_objects:
            self.objects = np.frombuffer(r.bytes(size_objects), dtype=OBJECT_DTYPE).copy()
        else:
            self.objects = None
            r.pos += size_objects
        self.object_count = n

        log('map info')
        self.mapinfo = []        # (type, dict)
        if want_mapinfo:
            self._read_mapinfo(r, len(data))
        elif len(data) - r.pos != size_mapinfo:
            raise ValueError('map info size mismatch')

    def _read_mapinfo(self, r, end):
        out = self.mapinfo
        d = r.d
        pos = r.pos
        recent = []
        while pos < end:
            tid = struct.unpack_from('<I', d, pos)[0]
            recent.append((tid, pos)); recent = recent[-6:]
            if tid in MAPINFO_T1:
                oid, x, y = struct.unpack_from('<Iff', d, pos + 4)
                out.append((tid, {'id': oid, 'x': x, 'y': y})); pos += 16
            elif tid in MAPINFO_T2:
                v = struct.unpack_from('<I8f', d, pos + 4)
                out.append((tid, {'id': v[0], 'corners': v[1:]})); pos += 40
            elif tid in MAPINFO_T3:
                v = struct.unpack_from('<II4f', d, pos + 4)
                out.append((tid, {'color': v[0], 'indicator': v[1], 'floats': v[2:]})); pos += 28
            elif tid in MAPINFO_T4:
                v = struct.unpack_from('<I8f4B', d, pos + 4)
                out.append((tid, {'id': v[0], 'corners': v[1:9], 'rgba': v[9:]})); pos += 44
            elif tid == 34:
                v = struct.unpack_from('<I4f', d, pos + 4)
                out.append((tid, {'id': v[0], 'floats': v[1:]})); pos += 24
            elif tid == 35:
                v = struct.unpack_from('<I6fB', d, pos + 4)
                out.append((tid, {'id': v[0], 'line': v[1:7], 'unknown': v[7]})); pos += 33
            elif tid == 44:
                oid, n = struct.unpack_from('<II', d, pos + 4)
                pts = np.frombuffer(d[pos + 12:pos + 12 + 8 * n], dtype='<f4').reshape(n, 2).copy()
                out.append((tid, {'id': oid, 'polygon': pts})); pos += 12 + 8 * n
            else:
                detail = ' | '.join('%d@0x%x: %s' % (t, p, d[p:p + 52].hex(' ')) for t, p in recent[:-1])
                raise ValueError('unknown map info type %d at 0x%x; preceding records: %s' % (tid, pos, detail))
        r.pos = pos

    # ---- helpers -------------------------------------------------------
    def object_positions(self):
        """(N,3) world positions x, y(height), z(north) of every object."""
        return self.objects['m'][:, 9:12]

    def object_yaw_deg(self):
        """Heading in degrees (0 = north, clockwise) from the forward vector."""
        m = self.objects['m']
        return np.degrees(np.arctan2(m[:, 6], m[:, 8])) % 360.0

    def object_scale(self):
        m = self.objects['m']
        return np.sqrt(m[:, 0] ** 2 + m[:, 1] ** 2 + m[:, 2] ** 2)

    def height_at(self, x, z):
        """Bilinear terrain height at world x, z (meters)."""
        fx, fz = x / self.cell_size, z / self.cell_size
        ix, iz = int(fx), int(fz)
        ix = min(max(ix, 0), self.map_x - 2); iz = min(max(iz, 0), self.map_y - 2)
        tx, tz = fx - ix, fz - iz
        e = self.elevation
        return ((1 - tx) * (1 - tz) * e[iz, ix] + tx * (1 - tz) * e[iz, ix + 1]
                + (1 - tx) * tz * e[iz + 1, ix] + tx * tz * e[iz + 1, ix + 1])
