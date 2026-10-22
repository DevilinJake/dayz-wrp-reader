"""Sanity checks for a parsed DayZ wrp: python check_map.py <file.wrp>"""
import sys, time, collections, re, numpy as np
from dayz_wrp import Wrp

t = time.time()
w = Wrp.load(sys.argv[1], progress=lambda *a: print('  ...', *a, '%.0fs' % (time.time() - t), flush=True))
print('loaded in %.1fs' % (time.time() - t), flush=True)
print('world', w.world_size, 'cell', w.cell_size, 'objects', w.object_count, 'classed', len(w.classed_models),
      'roads', len(w.roads), 'mapinfo', len(w.mapinfo), 'peaks', len(w.peaks))
print('elev', w.elevation.min(), w.elevation.max(), 'geo uniq', len(np.unique(w.geography)), 'sound uniq', np.unique(w.sound_map)[:20])
print('matidx range', w.material_index.min(), w.material_index.max(), 'nmat', len(w.materials), 'models', len(w.models),
      'model idx max', w.objects['model'].max())
print('shape vals', collections.Counter(w.objects['shape'].tolist()).most_common(4), 'extra vals',
      collections.Counter(w.objects['extra'].tolist()).most_common(4))
print('mapinfo types', sorted(collections.Counter(t for t, _ in w.mapinfo).items()))
g = w.enfi.grid
print('enfi hdr', hex(w.enfi.unknown), w.enfi.tile_count, w.enfi.unknown2, 'nibble hist', sorted(collections.Counter(g.ravel().tolist()).items()))
rng = np.random.default_rng(1); hits = 0; tot = 0; miss = collections.Counter()
for k in range(3000):
    x = int(rng.integers(0, w.map_x)); y = int(rng.integers(0, w.map_y))
    v = int(g[y, x]); mi = int(w.material_index[y // 8, x // 8]); name = w.materials[mi]
    layers = [int(s) for s in re.findall(r'_l(\d\d)', name)]
    if not name or v == 0:
        continue
    tot += 1
    if v in layers:
        hits += 1
    else:
        miss[(v, tuple(layers))] += 1
print('nibble in rvmat layers: %d/%d' % (hits, tot), miss.most_common(6))
print('sample names', w.materials[1], w.materials[100], w.materials[len(w.materials) // 2])
pos = w.object_positions(); print('obj pos range', pos.min(0), pos.max(0))
print('object sample', w.models[w.objects['model'][:5]], pos[:3])
print('classed sample', w.classed_models[:2])
print('road sample', w.roads[0][:6])
idx = rng.integers(0, len(pos), 2000); dh = [pos[i, 1] - w.height_at(pos[i, 0], pos[i, 2]) for i in idx]
print('object height above terrain: median %.2f, 10/90 pct %.2f/%.2f' % (np.median(dh), np.percentile(dh, 10), np.percentile(dh, 90)))
