# dayz-wrp-reader

Read DayZ Standalone terrain files (`.wrp`, OPRW version 32) with plain Python.

DayZ ships its maps as binarized `.wrp` files (`chernarusplus.wrp`, `enoch.wrp`,
and the same for any mod map built with DayZ Tools). Until now the only way to
look inside them was paid closed-source software. This reader opens them with
Python 3 and numpy, loads a full map in about two seconds, and exports
everything to CSV, JSON, PNG and `.npy` files that any tool can use.

What you get out of a map:

* every placed object (about 3 million per official map): model path, position, heading, scale
* the buildings with their config class names (`Land_*`)
* the road network, piece by piece, with connection points
* the terrain heightmap (2048 x 2048 floats on the official maps)
* the surface / ground-texture layout per terrain cell
* the forest, road and water flags the engine uses per 60 m cell
* everything the in-game map draws (tree, bush and rock icons, building footprints, power lines, rail...)

It was verified on both official maps: every section of the file ends exactly
where the file says it should, road pieces sit on the decoded terrain with a
0.00 m median error, and building positions match known landmarks.

## Install

```bash
git clone https://github.com/DevilinJake/dayz-wrp-reader
cd dayz-wrp-reader
pip install numpy
```

No other dependencies. The LZO decompressor the format needs is included
(`lzo1x.py`, pure Python).

## Where to get a .wrp file

Install **DayZ Tools** (free on Steam), run *Settings > Extract Game Data* once,
and the official maps appear on the `P:` drive:

```
P:\DZ\worlds\chernarusplus\world\chernarusplus.wrp
P:\DZ\worlds\enoch\world\enoch.wrp
```

Mod maps: unpack the map PBO with any PBO tool; the `.wrp` is inside.

The reader never modifies the file.

## Usage

Export everything to a folder:

```bash
python dump_wrp.py "P:\DZ\worlds\chernarusplus\world\chernarusplus.wrp" out\chernarusplus
```

Or use it as a library:

```python
from dayz_wrp import Wrp

w = Wrp.load(r"P:\DZ\worlds\chernarusplus\world\chernarusplus.wrp")

w.world_size                       # 15360.0 (metres)
w.elevation[z_index, x_index]      # float32 heightmap, row 0 = south edge
w.height_at(6500.0, 2700.0)        # bilinear terrain height at world x, z

pos = w.object_positions()         # (N, 3) array: x, height, z
names = w.models[w.objects['model']]
yaw = w.object_yaw_deg()           # 0 = north, clockwise

for cls, model, x, y, z, object_id, flags in w.classed_models:
    ...                            # buildings with config class names

for cell, points, types, object_id, flags, p3d, matrix in w.roads:
    ...                            # road pieces
```

`Wrp.load(path, want_objects=False, want_roads=False, want_mapinfo=False)`
skips the big sections if you only need the terrain.

## Exported files

| file | content |
|---|---|
| `meta.json` | world size, cell size, counts, the model list and the material (rvmat) list |
| `objects.csv` | `id, model, x, y, z, yaw_deg, scale, shape, flags` for every placed object |
| `classed_models.csv` | `class, model, x, y, z, object_id, flags` for objects that have a config class |
| `roads.csv` | one row per road piece: p3d, position, heading, connection points and types |
| `mapinfo.csv` | what the in-game map draws: `type, name, object_id, x, y, extra` |
| `heightmap.npy` | float32 `[rows, cols]` terrain heights in metres, `[row = z / cell, col = x / cell]` |
| `heightmap.png` | 16-bit grayscale preview, north up |
| `surface_index.npy` | uint8 per terrain cell: the 1-based slot of the dominant surface layer in that cell's rvmat name; 0 = open sea tile |
| `surface_index.png` | preview, north up |
| `material_index.npy` | uint16 per layer cell (256 x 256): index into `meta.json["materials"]` |
| `geography.npy` | uint16 bit flags per layer cell, see below |
| `sound_map.npy` | uint8 ambient-sound zone per layer cell |
| `peaks.csv` | hill-top markers `x, y, z` |
| `subdiv_hints.npy`, `persistent.npy` | engine grids kept for completeness |

### Coordinates

Game convention throughout: **x = east, z = north, y = height**, all in
metres from the south-west corner of the map. Chernarus is 15360 m wide
(2048 x 2048 terrain cells of 7.5 m, 256 x 256 "layer" cells of 60 m).
Livonia is 12800 m (6.25 m and 50 m cells).

Grids are numpy arrays indexed `[row, col]` = `[z / cell_size, x / cell_size]`,
so row 0 is the south edge. The PNG previews are flipped to be north up.

Object transforms are the usual 3x4 matrix (three axis rows then the position
row). Heading is `atan2(m[6], m[8])` on the forward row; scale is the length
of the first row.

### Geography flags (per 60 m / 50 m layer cell)

bits 0-1 minimum water depth class, 2 full, 3 forest, 4 road, 5-6 maximum
water depth class, 7-8 object count class, 9-10 hard-object count class,
11-13 gradient class, 14 some roadway, 15 some objects.

### Surface index and rvmat names

The ground texture of a 60 m layer cell is an rvmat whose name lists the
surface layers it blends, for example
`p_012-027_l00_l03_l04_n_l09_l12.rvmat` (tile column 12, row 27 counted from
the north, layers l00, l03, l04, none, l09, l12). The surface index gives,
per 7.5 m terrain cell, which of those slots is dominant: value 3 in that
cell means `l04`. The global layer numbers refer to the map's
`layers.cfg` / `config.cpp` surface list.

## The file format

DayZ uses OPRW **version 32**, a newer revision of the Arma 3 OPRW format
(public documentation stops at version 24/25). The layout below was
established by parsing the two official files until every section landed
exactly on its declared size. Differences from Arma 3 are marked `<-`.

```
"OPRW"  u32 version = 32   char[4] "0FNE"   u8 1   u32 0              <- tag + 5 bytes are new
u32 layerSizeX, layerSizeY (256)   u32 mapSizeX, mapSizeY (2048)   f32 layerCellSize
quadtree<u16> geography            (Arma packed quad tree: u8 rootIsNode, nodes = u16 flag + 16 children, leaf = 4 bytes)
quadtree<u8>  sound map
u32 nPeaks, f32[3] peaks[n]
quadtree<u16> material index
u32 size, LZO1X(size) -> "ENFI" block                                 <- replaces grass + primary-texture arrays
LZO1X(mapSize*4)      -> float32 elevation
u32 nMaterials, { asciiz rvmat, u8 }   (entry 0 is the empty name)
u32 nModels, { asciiz p3d }
u32 nClassed, { asciiz class, asciiz p3d, f32 x y z, u32 objectId, u32 flags }   <- flags is new
quadtree<u32> object offsets, u32 sizeOfObjects
quadtree<u32> map-object offsets, u32 sizeOfMapInfo
LZO1X(layerSize) persistent, LZO1X(mapSize) subdivision hints
u32 maxObjectId, u32 roadNetSize
roadnet: for each of the layerSizeX*layerSizeY cells: u32 nParts, parts {
    u16 nPts, f32[3] pts[n], u8 types[n], u32 objectId, u32 flags,   <- flags is new
    asciiz p3d, f32[12] transform }
objects: sizeOfObjects / 64 records { u32 id, u32 modelIndex, f32[12] transform,
    u32 shapeParam (2), u32 extra (0) }                                  <- 64 bytes, not 60
map info until end of file: u32 type + payload
    types 36, 38, 39, 40 are 16-byte records (objId, x, y)              <- differ from Arma tables
    types 41, 42, 43 are 44-byte records (objId, 4 corners, rgba)       <- differ from Arma tables
```

The ENFI block (decompressed):

```
"ENFI" u32 1  u32 width(2048) u32 height(2048)  u32 unknown  u32 tileCount  u32 0  u32 0
u8 tileTable[(width/64) * (height/64)]   0xff = tile present, 0 = absent (open sea)
u8 tileBits[...]                         the same table as a bit mask (LSB first)
tileCount x 2048 bytes                   64 x 64 cells, 4 bits each, low nibble first, row-major
```

Compressed blocks smaller than 1024 bytes are stored raw, as in Arma.

Map-info type names in `mapinfo.csv` come from the Arma 3 documentation and
may not all be right for DayZ; the numeric `type` is what the file says.

### Known unknowns

* the header tag `0FNE` and the following `u8 1, u32 0`
* the ENFI header word `0x867f0406` (identical on both official maps)
* the per-record `flags` word on classed models and road pieces (always `0x80xxxx00`)
* the meaning of map-info types 41-43 beyond their shape

Pull requests that pin these down are welcome.

## Files

| file | purpose |
|---|---|
| `dayz_wrp.py` | the parser, `Wrp.load(path)` |
| `lzo1x.py` | LZO1X decompressor, pure Python |
| `dump_wrp.py` | exports a map to CSV / JSON / PNG / `.npy` |
| `check_map.py` | the sanity checks used to verify the format |

## Credits

Built on the public Arma 3 OPRW documentation and readers:
the Bohemia Interactive community wiki, [Braini01/bis-file-formats](https://github.com/Braini01/bis-file-formats),
[gruppe-adler/grad_aff](https://github.com/gruppe-adler/grad_aff) and
[arma-tools/arma-file-formats-rs](https://github.com/arma-tools/arma-file-formats-rs).

## Legal

MIT licensed. The reader is original code. The `.wrp` files and anything
exported from them belong to Bohemia Interactive; keep exported game data
within what Bohemia's modding terms allow and do not redistribute it as if it
were yours.
