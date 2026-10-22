"""Export everything readable from a DayZ .wrp into plain files.

    python dump_wrp.py <map.wrp> <output_dir>

Writes into <output_dir>:
  meta.json            sizes, cell size, counts, model/material lists
  heightmap.npy        float32 [rows=north, cols=east], row 0 = south edge (y=0)
  heightmap.png        16-bit grayscale preview (north up)
  objects.csv          id, model, x, y, z, yaw_deg, scale, shape, flags
  classed_models.csv   class, model, x, y, z, object_id, flags
  roads.csv            one row per road part: object_id, p3d, x, y, z, yaw_deg, points
  mapinfo.csv          type, name, object_id, x, y (centre of corners for area types)
  surface_index.npy    uint8 per terrain cell (the ENFI 4-bit grid)
  surface_index.png    preview
  material_index.npy   uint16 per layer cell -> index into meta.json "materials"
  geography.npy        uint16 bit flags per layer cell (forest/road/water bits)
  sound_map.npy, subdiv_hints.npy, persistent.npy, peaks.csv
"""
import sys, os, json, zlib, struct, csv, time
import numpy as np
from dayz_wrp import Wrp, MAPINFO_NAMES


def write_png(path, img):
    """Write a 2-D uint8 or uint16 grayscale array as PNG (no PIL needed)."""
    img = np.ascontiguousarray(img)
    bit = 16 if img.dtype == np.uint16 else 8
    if bit == 16:
        img = img.byteswap() if img.dtype.byteorder == '<' or (img.dtype.byteorder == '=' and sys.byteorder == 'little') else img
    h, w = img.shape
    raw = b''.join(b'\0' + img[y].tobytes() for y in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, bit, 0, 0, 0, 0)))
        f.write(chunk(b'IDAT', zlib.compress(raw, 6)))
        f.write(chunk(b'IEND', b''))


def main(src, out):
    os.makedirs(out, exist_ok=True)
    t = time.time()
    w = Wrp.load(src, progress=lambda *a: print('  reading', *a, flush=True))
    print('parsed in %.0fs' % (time.time() - t), flush=True)

    meta = {
        'source': os.path.basename(src), 'version': w.version,
        'world_size_m': w.world_size, 'terrain_cell_size_m': w.cell_size,
        'terrain_grid': [w.map_x, w.map_y], 'layer_grid': [w.layer_x, w.layer_y],
        'layer_cell_size_m': w.layer_cell_size,
        'object_count': int(w.object_count), 'classed_model_count': len(w.classed_models),
        'road_part_count': len(w.roads), 'mapinfo_count': len(w.mapinfo), 'peak_count': len(w.peaks),
        'max_object_id': w.max_object_id,
        'elevation_min': float(w.elevation.min()), 'elevation_max': float(w.elevation.max()),
        'models': list(w.models), 'materials': w.materials,
        'coordinate_note': 'x = east (m), z = north (m), y = height (m). Grids are indexed [row=z/cell, col=x/cell].',
    }
    json.dump(meta, open(os.path.join(out, 'meta.json'), 'w'), indent=1)

    np.save(os.path.join(out, 'heightmap.npy'), w.elevation)
    e = w.elevation
    img = ((e - e.min()) / max(e.max() - e.min(), 1e-6) * 65535).astype(np.uint16)
    write_png(os.path.join(out, 'heightmap.png'), img[::-1])          # north up
    np.save(os.path.join(out, 'surface_index.npy'), w.enfi.grid)
    write_png(os.path.join(out, 'surface_index.png'), (w.enfi.grid * 17).astype(np.uint8)[::-1])
    np.save(os.path.join(out, 'material_index.npy'), w.material_index)
    np.save(os.path.join(out, 'geography.npy'), w.geography)
    np.save(os.path.join(out, 'sound_map.npy'), w.sound_map)
    np.save(os.path.join(out, 'subdiv_hints.npy'), w.subdiv_hints)
    np.save(os.path.join(out, 'persistent.npy'), w.persistent)
    with open(os.path.join(out, 'peaks.csv'), 'w', newline='') as f:
        cw = csv.writer(f); cw.writerow(['x', 'y', 'z'])
        cw.writerows(w.peaks.tolist())

    print('writing objects.csv', flush=True)
    o = w.objects
    pos = w.object_positions(); yaw = w.object_yaw_deg(); scale = w.object_scale()
    names = w.models[o['model']]
    with open(os.path.join(out, 'objects.csv'), 'w', newline='') as f:
        cw = csv.writer(f)
        cw.writerow(['id', 'model', 'x', 'y', 'z', 'yaw_deg', 'scale', 'shape', 'flags'])
        for i in range(len(o)):
            cw.writerow([int(o['id'][i]), names[i], '%.3f' % pos[i, 0], '%.3f' % pos[i, 1], '%.3f' % pos[i, 2],
                         '%.2f' % yaw[i], '%.3f' % scale[i], int(o['shape'][i]), int(o['extra'][i])])

    with open(os.path.join(out, 'classed_models.csv'), 'w', newline='') as f:
        cw = csv.writer(f)
        cw.writerow(['class', 'model', 'x', 'y', 'z', 'object_id', 'flags'])
        for c in w.classed_models:
            cw.writerow([c[0], c[1], '%.3f' % c[2], '%.3f' % c[3], '%.3f' % c[4], c[5], hex(c[6])])

    with open(os.path.join(out, 'roads.csv'), 'w', newline='') as f:
        cw = csv.writer(f)
        cw.writerow(['object_id', 'p3d', 'x', 'y', 'z', 'yaw_deg', 'layer_cell', 'connection_points', 'connection_types'])
        for cell, pts, types, oid, flags, p3d, m in w.roads:
            yaw = np.degrees(np.arctan2(m[6], m[8])) % 360
            cw.writerow([oid, p3d, '%.3f' % m[9], '%.3f' % m[10], '%.3f' % m[11], '%.2f' % yaw, cell,
                         ';'.join('%.2f %.2f %.2f' % tuple(p) for p in pts), ';'.join(str(b) for b in types)])

    with open(os.path.join(out, 'mapinfo.csv'), 'w', newline='') as f:
        cw = csv.writer(f)
        cw.writerow(['type', 'name', 'object_id', 'x', 'y', 'extra'])
        for tid, rec in w.mapinfo:
            name = MAPINFO_NAMES.get(tid, '')
            if 'x' in rec:
                cw.writerow([tid, name, rec['id'], '%.2f' % rec['x'], '%.2f' % rec['y'], ''])
            elif 'corners' in rec:
                c = rec['corners']
                cx = sum(c[0::2]) / 4; cy = sum(c[1::2]) / 4
                cw.writerow([tid, name, rec['id'], '%.2f' % cx, '%.2f' % cy, ' '.join('%.2f' % v for v in c)])
            elif 'polygon' in rec:
                p = rec['polygon']
                cw.writerow([tid, name, rec['id'], '%.2f' % p[:, 0].mean(), '%.2f' % p[:, 1].mean(), ';'.join('%.2f %.2f' % tuple(q) for q in p)])
            elif 'line' in rec:
                l = rec['line']
                cw.writerow([tid, name, rec['id'], '%.2f' % l[0], '%.2f' % l[1], ' '.join('%.2f' % v for v in l)])
            else:
                cw.writerow([tid, name, '', '', '', json.dumps({k: (list(v) if isinstance(v, tuple) else v) for k, v in rec.items()})])
    print('done in %.0fs -> %s' % (time.time() - t, out))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
