import json, os
from collections import defaultdict

os.makedirs('public/blocks', exist_ok=True)
os.makedirs('public/panchayats', exist_ok=True)

# ── Split blocks by DIST_NAME ──────────────────────────────────────────────
print("Processing blocks...")
with open('data/block_boundary.geojson', encoding='utf-8') as f:
    blocks = json.load(f)

by_dist = defaultdict(list)
for feat in blocks['features']:
    dist = feat['properties'].get('DIST_NAME', 'UNKNOWN')
    by_dist[dist.strip()].append(feat)

for dist, feats in by_dist.items():
    safe = dist.replace(' ', '_').replace('/', '_')
    with open(f'public/blocks/{safe}.geojson', 'w') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f)
    print(f"  blocks/{safe}.geojson → {len(feats)} features")

# ── Split panchayats by DIST_NAME + BLK_NAME ──────────────────────────────
print("Processing panchayats...")
with open('data/panchayat_boundary.geojson', encoding='utf-8') as f:
    panchayats = json.load(f)

by_dist_blk = defaultdict(list)
for feat in panchayats['features']:
    dist = feat['properties'].get('DIST_NAME', 'UNKNOWN').strip()
    blk  = feat['properties'].get('BLK_NAME',  'UNKNOWN').strip()
    by_dist_blk[(dist, blk)].append(feat)

for (dist, blk), feats in by_dist_blk.items():
    safe_d = dist.replace(' ', '_').replace('/', '_')
    safe_b = blk.replace(' ', '_').replace('/', '_')
    fname  = f'public/panchayats/{safe_d}__{safe_b}.geojson'  # double underscore separator
    with open(fname, 'w') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f)
    print(f"  panchayats/{safe_d}__{safe_b}.geojson → {len(feats)} features")

print("Done.")
