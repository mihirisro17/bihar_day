# from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
# from datetime import date
# import csv, os, sys, json, hashlib, requests, base64, io
# import concurrent.futures
# from pathlib import Path
# from PIL import Image

# BASE_DIR = os.getcwd()
# sys.path.insert(0, BASE_DIR)
# import config as C

# app = Flask(
#     __name__,
#     template_folder=os.path.join(BASE_DIR, "templates"),
#     static_folder=os.path.join(BASE_DIR, "static")
# )

# # ── Cache ──
# IS_VERCEL     = bool(os.environ.get("VERCEL", ""))
# SAT_CACHE_DIR = Path("/tmp/sat_cache") if IS_VERCEL else Path(BASE_DIR) / "static" / "sat_cache"
# SAT_CACHE_URL = "/sat_cache"           if IS_VERCEL else "/static/sat_cache"
# SAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# EOX_AVAIL    = [2016,2017,2018,2019,2020,2021,2022,2023,2024]
# SAT_W, SAT_H = 1600, 900   # Sentinel / MODIS
# TARGET_AR    = 16 / 9
# KM30_LAT, KM30_LNG = 0.27, 0.30

# # RIDAM tile grid — 256×256 per tile, 4 cols × 3 rows = 1024×768 stitched
# RIDAM_TILE = 256
# RIDAM_COLS = 4
# RIDAM_ROWS = 3


# # ----------------------------
# # BBox
# # ----------------------------

# def compute_padded_bbox(raw_bbox):
#     if not raw_bbox:
#         raw_bbox = {"minLng":83.3,"minLat":24.3,"maxLng":88.2,"maxLat":27.5}
#     exp = {
#         "minLng": raw_bbox["minLng"] - KM30_LNG,
#         "maxLng": raw_bbox["maxLng"] + KM30_LNG,
#         "minLat": raw_bbox["minLat"] - KM30_LAT,
#         "maxLat": raw_bbox["maxLat"] + KM30_LAT,
#     }
#     cx = (exp["maxLng"] + exp["minLng"]) / 2
#     cy = (exp["maxLat"] + exp["minLat"]) / 2
#     pW = (exp["maxLng"] - exp["minLng"]) * 1.5
#     pH = (exp["maxLat"] - exp["minLat"]) * 1.5
#     if pW / pH > TARGET_AR: pH = pW / TARGET_AR
#     else: pW = pH * TARGET_AR
#     return {
#         "minLng": round(cx - pW/2, 6), "maxLng": round(cx + pW/2, 6),
#         "minLat": round(cy - pH/2, 6), "maxLat": round(cy + pH/2, 6),
#     }


# # ----------------------------
# # WMS URL builders
# # ----------------------------

# def _bq(bbox):
#     """WMS 1.1.1 — axis order: minLng,minLat,maxLng,maxLat"""
#     b = f"{bbox['minLng']},{bbox['minLat']},{bbox['maxLng']},{bbox['maxLat']}"
#     return f"&STYLES=&SRS=EPSG:4326&BBOX={b}&WIDTH={SAT_W}&HEIGHT={SAT_H}&FORMAT=image/jpeg"


# def get_sentinel_url(year, bbox):
#     y = year if year in EOX_AVAIL else max(
#         (v for v in EOX_AVAIL if v <= year), default=EOX_AVAIL[-1]
#     )
#     return (
#         f"https://tiles.maps.eox.at/wms?SERVICE=WMS&VERSION=1.1.1"
#         f"&REQUEST=GetMap&LAYERS=s2cloudless-{y}{_bq(bbox)}",
#         "Sentinel-2"
#     )


# def get_modis_url(year, bbox):
#     y = min(max(year, 2000), 2024)
#     return (
#         f"https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
#         f"?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
#         f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
#         f"&TIME={y}-06-15{_bq(bbox)}",
#         "MODIS Terra"
#     )


# def _ridam_tile_url(year, tile_bbox):
#     """Build a single 256×256 RIDAM WMS tile URL for a sub-bbox."""
#     from urllib.parse import quote
#     date_str = f"{year}1231"
#     args_raw = (
#         f"r_dataset_id:T0S1P11;g_dataset_id:T0S1P11;b_dataset_id:T0S1P11;"
#         f"r_from_time:{date_str};r_to_time:{date_str};"
#         f"g_from_time:{date_str};g_to_time:{date_str};"
#         f"b_from_time:{date_str};b_to_time:{date_str};"
#         f"r_index:1;g_index:2;b_index:3;"
#         f"r_max:50;g_max:50;b_max:50"
#     )
#     args_enc = quote(args_raw, safe='')  # : → %3A, ; → %3B
#     # WMS 1.3.0 EPSG:4326 — BBOX axis order: minLat,minLng,maxLat,maxLng
#     bbox_str = (
#         f"{tile_bbox['minLat']},"
#         f"{tile_bbox['minLng']},"
#         f"{tile_bbox['maxLat']},"
#         f"{tile_bbox['maxLng']}"
#     )
#     return (
#         "https://vedas.sac.gov.in/ridam/wms"
#         "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
#         "&FORMAT=image%2Fpng&TRANSPARENT=true"
#         "&name=RIDAM_RGB&layers=T0S0M1"
#         "&PROJECTION=EPSG%3A4326"
#         f"&ARGS={args_enc}"
#         f"&WIDTH={RIDAM_TILE}&HEIGHT={RIDAM_TILE}"
#         "&CRS=EPSG%3A4326&STYLES="
#         f"&BBOX={bbox_str}"
#     )


# def fetch_ridam_tiled(year, bbox):
#     """
#     Split bbox into a RIDAM_COLS × RIDAM_ROWS grid of 256×256 tiles.
#     Fetch all tiles in parallel, stitch with PIL, return JPEG bytes.
#     Returns (bytes, 'jpg') on success, (None, None) on failure.
#     """
#     lng_span = bbox['maxLng'] - bbox['minLng']
#     lat_span = bbox['maxLat'] - bbox['minLat']
#     lng_step = lng_span / RIDAM_COLS
#     lat_step = lat_span / RIDAM_ROWS

#     # Build tile definitions: (col, row, sub-bbox)
#     tile_defs = []
#     for row in range(RIDAM_ROWS):
#         for col in range(RIDAM_COLS):
#             tile_bbox = {
#                 'minLng': bbox['minLng'] + col * lng_step,
#                 'maxLng': bbox['minLng'] + (col + 1) * lng_step,
#                 'maxLat': bbox['maxLat'] - row * lat_step,        # top edge of tile
#                 'minLat': bbox['maxLat'] - (row + 1) * lat_step,  # bottom edge of tile
#             }
#             tile_defs.append((col, row, tile_bbox))

#     def fetch_one(args):
#         col, row, tile_bbox = args
#         url = _ridam_tile_url(year, tile_bbox)
#         try:
#             resp = requests.get(url, timeout=30, headers={"User-Agent": "BiharDiwas/1.0"})
#             ct   = resp.headers.get("content-type", "")
#             if resp.status_code == 200 and "image" in ct and len(resp.content) > 500:
#                 return col, row, resp.content
#             print(f"[RIDAM tile ({col},{row})] {resp.status_code} ct={ct} | {resp.content[:120]}")
#         except Exception as e:
#             print(f"[RIDAM tile ({col},{row})] error: {e}")
#         return col, row, None

#     # Fetch all tiles concurrently
#     with concurrent.futures.ThreadPoolExecutor(max_workers=RIDAM_COLS * RIDAM_ROWS) as ex:
#         results = list(ex.map(fetch_one, tile_defs))

#     success_count = sum(1 for _, _, d in results if d is not None)
#     total = RIDAM_COLS * RIDAM_ROWS
#     print(f"[RIDAM] {success_count}/{total} tiles fetched for year={year}")

#     if success_count < total * 0.5:
#         print(f"[RIDAM] Too many failures — falling back")
#         return None, None

#     # Stitch tiles onto canvas
#     canvas_w = RIDAM_COLS * RIDAM_TILE
#     canvas_h = RIDAM_ROWS * RIDAM_TILE
#     canvas = Image.new("RGBA", (canvas_w, canvas_h), (10, 10, 20, 255))

#     for col, row, data in results:
#         if data:
#             try:
#                 tile_img = Image.open(io.BytesIO(data)).convert("RGBA")
#                 canvas.paste(tile_img, (col * RIDAM_TILE, row * RIDAM_TILE))
#             except Exception as e:
#                 print(f"[RIDAM stitch ({col},{row})] {e}")

#     # Flatten to RGB (dark background for transparent areas)
#     bg    = Image.new("RGB", canvas.size, (10, 10, 20))
#     alpha = canvas.split()[3]
#     bg.paste(canvas.convert("RGB"), mask=alpha)

#     buf = io.BytesIO()
#     bg.save(buf, format="JPEG", quality=90)
#     return buf.getvalue(), "jpg"


# # ----------------------------
# # Cache / Fetch helpers
# # ----------------------------

# def _image_to_url(img_bytes, cache_key, ext):
#     """Write bytes to disk (local) or return base64 data URI (Vercel)."""
#     if not IS_VERCEL:
#         filename   = hashlib.md5(cache_key.encode()).hexdigest() + f".{ext}"
#         filepath   = SAT_CACHE_DIR / filename
#         static_url = f"{SAT_CACHE_URL}/{filename}"
#         filepath.write_bytes(img_bytes)
#         return static_url
#     else:
#         mime = "image/png" if ext == "png" else "image/jpeg"
#         b64  = base64.b64encode(img_bytes).decode("utf-8")
#         return f"data:{mime};base64,{b64}"


# def fetch_and_cache(url, cache_key, ext="jpg"):
#     """Fetch a WMS URL (Sentinel/MODIS) — cache to disk or return base64 URI."""
#     mime = "image/png" if ext == "png" else "image/jpeg"

#     if not IS_VERCEL:
#         filename   = hashlib.md5(cache_key.encode()).hexdigest() + f".{ext}"
#         filepath   = SAT_CACHE_DIR / filename
#         static_url = f"{SAT_CACHE_URL}/{filename}"
#         if filepath.exists() and filepath.stat().st_size > 10_000:
#             return static_url, True
#         try:
#             resp = requests.get(url, timeout=45, headers={"User-Agent": "BiharDiwas/1.0"})
#             ct   = resp.headers.get("content-type", "")
#             print(f"[SAT] {resp.status_code} ct={ct} size={len(resp.content)} url={url[:100]}")
#             if resp.status_code == 200 and "image" in ct and len(resp.content) > 10_000:
#                 filepath.write_bytes(resp.content)
#                 return static_url, True
#             print(f"[SAT] body: {resp.content[:200]}")
#         except Exception as e:
#             print(f"[SAT] Fetch failed: {e}")
#         return None, False
#     else:
#         try:
#             resp = requests.get(url, timeout=55, headers={"User-Agent": "BiharDiwas/1.0"})
#             ct   = resp.headers.get("content-type", "")
#             print(f"[SAT] {resp.status_code} ct={ct} size={len(resp.content)} url={url[:100]}")
#             if resp.status_code == 200 and "image" in ct and len(resp.content) > 10_000:
#                 b64 = base64.b64encode(resp.content).decode("utf-8")
#                 return f"data:{mime};base64,{b64}", True
#             print(f"[SAT] body: {resp.content[:200]}")
#         except Exception as e:
#             print(f"[SAT] Fetch failed: {e}")
#         return None, False


# # ----------------------------
# # Sat cache routes
# # ----------------------------

# @app.route("/sat_cache/<filename>")
# def sat_cache_vercel(filename):
#     return send_from_directory(str(SAT_CACHE_DIR), filename)

# @app.route("/static/sat_cache/<filename>")
# def sat_cache_local(filename):
#     return send_from_directory(str(SAT_CACHE_DIR), filename)


# # ----------------------------
# # API: satellite image
# # ----------------------------

# @app.route("/api/sat_image")
# def api_sat_image():
#     img_type = request.args.get("type", "birth")
#     try:
#         year = int(request.args.get("year", 2000))
#     except:
#         return jsonify({"error": "bad year"}), 400

#     try:
#         raw_bbox = json.loads(request.args.get("bbox", "{}"))
#     except:
#         raw_bbox = None

#     bbox = compute_padded_bbox(raw_bbox)
#     local = None
#     src   = "Unknown"

#     if img_type == "current":
#         # ── Present: Sentinel-2 cloudless ──
#         url, src  = get_sentinel_url(year, bbox)
#         key       = f"current_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
#         local, ok = fetch_and_cache(url, key, ext="jpg")
#         if not ok:
#             url, src  = get_modis_url(2024, bbox)
#             key       = f"current_modis_2024_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
#             local, _  = fetch_and_cache(url, key, ext="jpg")
#             src       = "MODIS Terra"

#     else:
#         if 1997 <= year <= 2016:
#             # ── RIDAM tiled fetch + PIL stitch ──
#             src = f"RIDAM Landsat {year}"
#             key = f"ridam_tiled_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"

#             # Check disk cache first (local only)
#             if not IS_VERCEL:
#                 filename   = hashlib.md5(key.encode()).hexdigest() + ".jpg"
#                 filepath   = SAT_CACHE_DIR / filename
#                 static_url = f"{SAT_CACHE_URL}/{filename}"
#                 if filepath.exists() and filepath.stat().st_size > 10_000:
#                     local = static_url
#                 else:
#                     img_bytes, ext = fetch_ridam_tiled(year, bbox)
#                     if img_bytes:
#                         filepath.write_bytes(img_bytes)
#                         local = static_url
#             else:
#                 img_bytes, ext = fetch_ridam_tiled(year, bbox)
#                 if img_bytes:
#                     local = _image_to_url(img_bytes, key, "jpg")

#             # Fallback to MODIS if RIDAM completely failed
#             if not local:
#                 print(f"[RIDAM] Tiled fetch failed for {year} — MODIS fallback")
#                 url, src  = get_modis_url(max(year, 2000), bbox)
#                 key       = f"birth_modis_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
#                 local, ok = fetch_and_cache(url, key, ext="jpg")
#                 src       = "MODIS Terra"
#                 if not ok:
#                     url, src  = get_modis_url(2000, bbox)
#                     key       = f"birth_modis_2000_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
#                     local, _  = fetch_and_cache(url, key, ext="jpg")
#                     src       = "MODIS Terra"

#         elif year >= 2016:
#             # ── Sentinel-2 cloudless ──
#             url, src  = get_sentinel_url(year, bbox)
#             key       = f"birth_s2_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
#             local, ok = fetch_and_cache(url, key, ext="jpg")
#             if not ok:
#                 url, src  = get_modis_url(year, bbox)
#                 key       = f"birth_modis_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
#                 local, _  = fetch_and_cache(url, key, ext="jpg")
#                 src       = "MODIS Terra"

#         else:
#             # ── pre-1997: MODIS Terra ──
#             url, src  = get_modis_url(max(year, 2000), bbox)
#             key       = f"birth_modis_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
#             local, ok = fetch_and_cache(url, key, ext="jpg")
#             src       = "MODIS Terra"
#             if not ok:
#                 url, src  = get_modis_url(2000, bbox)
#                 key       = f"birth_modis_2000"
#                 local, _  = fetch_and_cache(url, key, ext="jpg")
#                 src       = "MODIS Terra"

#     return jsonify({
#         "url":       local or "",
#         "src_label": f"📡 {src}",
#         "bbox":      bbox
#     })


# # ----------------------------
# # Debug endpoint (remove after confirmed working)
# # ----------------------------

# @app.route("/api/debug_ridam")
# def debug_ridam():
#     year = int(request.args.get("year", 2005))
#     bbox = compute_padded_bbox(None)
#     img_bytes, ext = fetch_ridam_tiled(year, bbox)
#     if img_bytes:
#         b64 = base64.b64encode(img_bytes).decode("utf-8")
#         return f'<img src="data:image/jpeg;base64,{b64}" style="max-width:100%;"/>'
#     return "RIDAM tiled fetch failed — check server logs", 500


# # ----------------------------
# # Load Events
# # ----------------------------

# def load_events():
#     events   = []
#     csv_path = os.path.join(BASE_DIR, "data", "events.csv")
#     if not os.path.exists(csv_path): return events

#     def icon(t):
#         for kw, em in C.ICON_MAP.items():
#             if kw in t.lower(): return em
#         return C.DEFAULT_ICON

#     def get_era(yr):
#         for e in C.ERAS:
#             if e["start"] <= yr <= e["end"]: return e["label"], e["color"]
#         return "Recent", C.ERAS[-1]["color"]

#     with open(csv_path, newline="", encoding="utf-8") as f:
#         for row in csv.DictReader(f):
#             yr     = int(row["Year"])
#             el, ec = get_era(yr)
#             cands  = []
#             for i in range(1, 6):
#                 ev = row.get(f"Event_{i}","").strip()
#                 sc = row.get(f"Positivity_Score_{i}","0").strip()
#                 if ev:
#                     try: sc = int(sc)
#                     except: sc = 5
#                     cands.append({"title":ev,"score":sc})
#             cands.sort(key=lambda x: x["score"], reverse=True)
#             for ev in cands[:C.EVENTS_PER_YEAR]:
#                 events.append({
#                     "year":yr,"title":ev["title"],"icon":icon(ev["title"]),
#                     "era":el,"color":ec,"score":ev["score"]
#                 })
#     events.sort(key=lambda x: x["year"])
#     return events

# ALL_EVENTS = load_events()


# # ----------------------------
# # Routes
# # ----------------------------

# @app.route("/")
# def index():
#     return render_template("index.html",
#         app_title=C.APP_TITLE, app_subtitle=C.APP_SUBTITLE,
#         app_logo=C.APP_LOGO_EMOJI, app_footer=C.APP_FOOTER)

# @app.route("/map")
# def map_page():
#     name       = request.args.get("name","").strip()
#     birth_year = request.args.get("birth_year","").strip()
#     if not name or not birth_year: return redirect(url_for("index"))
#     return render_template("map.html", name=name, birth_year=birth_year, app_title=C.APP_TITLE)


# @app.route("/analyse", methods=["GET","POST"])
# def analyse():
#     if request.method == "GET": return redirect(url_for("index"))

#     name       = request.form.get("name","").strip()
#     birth_year = request.form.get("birth_year","").strip()
#     district   = request.form.get("district","").strip()
#     bbox_raw   = request.form.get("bbox","{}")

#     if not name or not birth_year or not district:
#         return redirect(url_for("index"))

#     try:
#         by    = int(birth_year)
#         today = date.today()
#         age   = today.year - by - (today.month < 7)
#     except:
#         return redirect(url_for("index"))

#     try:
#         bbox = json.loads(bbox_raw)
#         if not bbox: bbox = None
#     except:
#         bbox = None

#     evs = [e for e in ALL_EVENTS if e["year"] >= by]

#     return render_template(
#         "result.html",
#         name=name, birth_year=by, age=age,
#         district=district, bbox=bbox, events=evs,
#         eras=C.ERAS, tl_interval=C.TIMELINE_INTERVAL_MS,
#         current_year=today.year, app_title=C.APP_TITLE,
#     )


from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from datetime import date
import csv, os, sys, json, hashlib, requests, base64, io
import concurrent.futures
from pathlib import Path
from PIL import Image

BASE_DIR   = os.getcwd()
PUBLIC_DIR = os.path.join(BASE_DIR, "public")   # ← all GeoJSON lives here
sys.path.insert(0, BASE_DIR)
import config as C

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)


# ── District name aliases (GeoJSON display name → filename stem) ──
DISTRICT_ALIASES = {
    "PURBI CHAMPARAN":        "EAST_CHAMPARAN",
    "PURBI_CHAMPARAN":        "EAST_CHAMPARAN",
    "EAST CHAMPARAN":         "EAST_CHAMPARAN",
    "PASHCHIM CHAMPARAN":     "WEST_CHAMPARAN",
    "PASHCHIM_CHAMPARAN":     "WEST_CHAMPARAN",
    "WEST CHAMPARAN":         "WEST_CHAMPARAN",
    "KAIMUR BHABUA":          "KAIMUR_(BHABUA)",
    "KAIMUR (BHABUA)":        "KAIMUR_(BHABUA)",
}

def resolve_district_stem(district: str) -> str:
    """Map any display name → actual filename stem."""
    upper = district.strip().upper()
    # Direct alias lookup
    if upper in DISTRICT_ALIASES:
        return DISTRICT_ALIASES[upper]
    # Norm fallback
    return norm_name(district)



# ── Cache ──
IS_VERCEL     = bool(os.environ.get("VERCEL", ""))
SAT_CACHE_DIR = Path("/tmp/sat_cache") if IS_VERCEL else Path(BASE_DIR) / "static" / "sat_cache"
SAT_CACHE_URL = "/sat_cache"           if IS_VERCEL else "/static/sat_cache"
SAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

EOX_AVAIL    = [2016,2017,2018,2019,2020,2021,2022,2023,2024]
SAT_W, SAT_H = 1600, 900
TARGET_AR    = 16 / 9
KM30_LAT, KM30_LNG = 0.27, 0.30

RIDAM_TILE = 256
RIDAM_COLS = 4
RIDAM_ROWS = 3


# ══════════════════════════════════════════════════
# GeoJSON name normalizer
# Converts any input → UPPERCASE_WITH_UNDERSCORES
# matching the actual filenames on disk
# ══════════════════════════════════════════════════

def norm_name(s: str) -> str:
    """
    'East Champaran' → 'EAST_CHAMPARAN'
    'Kaimur (Bhabua)' → 'KAIMUR_(BHABUA)'
    'Patna Sadar'     → 'PATNA_SADAR'
    """
    return s.strip().upper().replace(" ", "_")


def find_geojson(directory: Path, filename_stem: str) -> Path | None:
    """
    Try exact match first, then case-insensitive scan of directory.
    Returns Path if found, else None.
    """
    exact = directory / f"{filename_stem}.geojson"
    if exact.exists():
        return exact
    # Case-insensitive fallback
    stem_lower = filename_stem.lower()
    for f in directory.glob("*.geojson"):
        if f.stem.lower() == stem_lower:
            return f
    return None


# ══════════════════════════════════════════════════
# BBox helpers
# ══════════════════════════════════════════════════

def compute_padded_bbox(raw_bbox, pad_factor=1.5):
    if not raw_bbox or not isinstance(raw_bbox, dict):
        raw_bbox = {"minLng":83.3,"minLat":24.3,"maxLng":88.2,"maxLat":27.5}
    exp = {
        "minLng": raw_bbox["minLng"] - KM30_LNG,
        "maxLng": raw_bbox["maxLng"] + KM30_LNG,
        "minLat": raw_bbox["minLat"] - KM30_LAT,
        "maxLat": raw_bbox["maxLat"] + KM30_LAT,
    }
    cx = (exp["maxLng"] + exp["minLng"]) / 2
    cy = (exp["maxLat"] + exp["minLat"]) / 2
    pW = (exp["maxLng"] - exp["minLng"]) * pad_factor
    pH = (exp["maxLat"] - exp["minLat"]) * pad_factor
    if pW / pH > TARGET_AR: pH = pW / TARGET_AR
    else: pW = pH * TARGET_AR
    return {
        "minLng": round(cx - pW/2, 6), "maxLng": round(cx + pW/2, 6),
        "minLat": round(cy - pH/2, 6), "maxLat": round(cy + pH/2, 6),
    }


def parse_bbox(raw_str):
    if not raw_str or raw_str in ("{}", "null", ""):
        return None
    try:
        b = json.loads(raw_str)
        if isinstance(b, dict) and b.get("minLng") is not None:
            return b
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════
# WMS URL builders
# ══════════════════════════════════════════════════

def _bq(bbox):
    b = f"{bbox['minLng']},{bbox['minLat']},{bbox['maxLng']},{bbox['maxLat']}"
    return f"&STYLES=&SRS=EPSG:4326&BBOX={b}&WIDTH={SAT_W}&HEIGHT={SAT_H}&FORMAT=image/jpeg"


def get_sentinel_url(year, bbox):
    y = year if year in EOX_AVAIL else max(
        (v for v in EOX_AVAIL if v <= year), default=EOX_AVAIL[-1]
    )
    return (
        f"https://tiles.maps.eox.at/wms?SERVICE=WMS&VERSION=1.1.1"
        f"&REQUEST=GetMap&LAYERS=s2cloudless-{y}{_bq(bbox)}",
        "Sentinel-2"
    )


def get_modis_url(year, bbox):
    y = min(max(year, 2000), 2024)
    return (
        f"https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
        f"?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
        f"&TIME={y}-06-15{_bq(bbox)}",
        "MODIS Terra"
    )


def _ridam_tile_url(year, tile_bbox):
    from urllib.parse import quote
    date_str = f"{year}1231"
    args_raw = (
        f"r_dataset_id:T0S1P11;g_dataset_id:T0S1P11;b_dataset_id:T0S1P11;"
        f"r_from_time:{date_str};r_to_time:{date_str};"
        f"g_from_time:{date_str};g_to_time:{date_str};"
        f"b_from_time:{date_str};b_to_time:{date_str};"
        f"r_index:1;g_index:2;b_index:3;"
        f"r_max:50;g_max:50;b_max:50"
    )
    args_enc = quote(args_raw, safe='')
    bbox_str = (
        f"{tile_bbox['minLat']},"
        f"{tile_bbox['minLng']},"
        f"{tile_bbox['maxLat']},"
        f"{tile_bbox['maxLng']}"
    )
    return (
        "https://vedas.sac.gov.in/ridam/wms"
        "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
        "&FORMAT=image%2Fpng&TRANSPARENT=true"
        "&name=RIDAM_RGB&layers=T0S0M1"
        "&PROJECTION=EPSG%3A4326"
        f"&ARGS={args_enc}"
        f"&WIDTH={RIDAM_TILE}&HEIGHT={RIDAM_TILE}"
        "&CRS=EPSG%3A4326&STYLES="
        f"&BBOX={bbox_str}"
    )


def fetch_ridam_tiled(year, bbox):
    lng_span = bbox['maxLng'] - bbox['minLng']
    lat_span = bbox['maxLat'] - bbox['minLat']
    lng_step = lng_span / RIDAM_COLS
    lat_step = lat_span / RIDAM_ROWS

    tile_defs = []
    for row in range(RIDAM_ROWS):
        for col in range(RIDAM_COLS):
            tile_bbox = {
                'minLng': bbox['minLng'] + col * lng_step,
                'maxLng': bbox['minLng'] + (col + 1) * lng_step,
                'maxLat': bbox['maxLat'] - row * lat_step,
                'minLat': bbox['maxLat'] - (row + 1) * lat_step,
            }
            tile_defs.append((col, row, tile_bbox))

    def fetch_one(args):
        col, row, tile_bbox = args
        url = _ridam_tile_url(year, tile_bbox)
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "BiharDiwas/1.0"})
            ct   = resp.headers.get("content-type", "")
            if resp.status_code == 200 and "image" in ct and len(resp.content) > 500:
                return col, row, resp.content
            print(f"[RIDAM tile ({col},{row})] {resp.status_code} ct={ct}")
        except Exception as e:
            print(f"[RIDAM tile ({col},{row})] error: {e}")
        return col, row, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=RIDAM_COLS * RIDAM_ROWS) as ex:
        results = list(ex.map(fetch_one, tile_defs))

    success_count = sum(1 for _, _, d in results if d is not None)
    total = RIDAM_COLS * RIDAM_ROWS
    print(f"[RIDAM] {success_count}/{total} tiles for year={year}")

    if success_count < total * 0.5:
        return None, None

    canvas_w = RIDAM_COLS * RIDAM_TILE
    canvas_h = RIDAM_ROWS * RIDAM_TILE
    canvas   = Image.new("RGBA", (canvas_w, canvas_h), (10, 10, 20, 255))

    for col, row, data in results:
        if data:
            try:
                tile_img = Image.open(io.BytesIO(data)).convert("RGBA")
                canvas.paste(tile_img, (col * RIDAM_TILE, row * RIDAM_TILE))
            except Exception as e:
                print(f"[RIDAM stitch ({col},{row})] {e}")

    bg    = Image.new("RGB", canvas.size, (10, 10, 20))
    alpha = canvas.split()[3]
    bg.paste(canvas.convert("RGB"), mask=alpha)

    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "jpg"


# ══════════════════════════════════════════════════
# Cache / fetch helpers
# ══════════════════════════════════════════════════

def _image_to_url(img_bytes, cache_key, ext):
    if not IS_VERCEL:
        filename   = hashlib.md5(cache_key.encode()).hexdigest() + f".{ext}"
        filepath   = SAT_CACHE_DIR / filename
        static_url = f"{SAT_CACHE_URL}/{filename}"
        filepath.write_bytes(img_bytes)
        return static_url
    else:
        mime = "image/png" if ext == "png" else "image/jpeg"
        b64  = base64.b64encode(img_bytes).decode("utf-8")
        return f"data:{mime};base64,{b64}"


def fetch_and_cache(url, cache_key, ext="jpg"):
    mime = "image/png" if ext == "png" else "image/jpeg"
    if not IS_VERCEL:
        filename   = hashlib.md5(cache_key.encode()).hexdigest() + f".{ext}"
        filepath   = SAT_CACHE_DIR / filename
        static_url = f"{SAT_CACHE_URL}/{filename}"
        if filepath.exists() and filepath.stat().st_size > 10_000:
            return static_url, True
        try:
            resp = requests.get(url, timeout=45, headers={"User-Agent": "BiharDiwas/1.0"})
            ct   = resp.headers.get("content-type", "")
            print(f"[SAT] {resp.status_code} ct={ct} size={len(resp.content)} url={url[:100]}")
            if resp.status_code == 200 and "image" in ct and len(resp.content) > 10_000:
                filepath.write_bytes(resp.content)
                return static_url, True
            print(f"[SAT] body: {resp.content[:200]}")
        except Exception as e:
            print(f"[SAT] Fetch failed: {e}")
        return None, False
    else:
        try:
            resp = requests.get(url, timeout=55, headers={"User-Agent": "BiharDiwas/1.0"})
            ct   = resp.headers.get("content-type", "")
            print(f"[SAT] {resp.status_code} ct={ct} size={len(resp.content)} url={url[:100]}")
            if resp.status_code == 200 and "image" in ct and len(resp.content) > 10_000:
                b64 = base64.b64encode(resp.content).decode("utf-8")
                return f"data:{mime};base64,{b64}", True
            print(f"[SAT] body: {resp.content[:200]}")
        except Exception as e:
            print(f"[SAT] Fetch failed: {e}")
        return None, False


# ══════════════════════════════════════════════════
# Sat cache static routes
# ══════════════════════════════════════════════════

@app.route("/sat_cache/<filename>")
def sat_cache_vercel(filename):
    return send_from_directory(str(SAT_CACHE_DIR), filename)

@app.route("/static/sat_cache/<filename>")
def sat_cache_local(filename):
    return send_from_directory(str(SAT_CACHE_DIR), filename)


# ══════════════════════════════════════════════════
# API: satellite image
# ══════════════════════════════════════════════════

@app.route("/api/sat_image")
def api_sat_image():
    img_type = request.args.get("type", "birth")
    try:
        year = int(request.args.get("year", 2000))
    except Exception:
        return jsonify({"error": "bad year"}), 400

    raw_bbox = parse_bbox(request.args.get("bbox", "{}"))
    bbox     = compute_padded_bbox(raw_bbox)
    local    = None
    src      = "Unknown"

    if img_type == "current":
        url, src  = get_sentinel_url(year, bbox)
        key       = f"current_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
        local, ok = fetch_and_cache(url, key, ext="jpg")
        if not ok:
            url, src  = get_modis_url(2024, bbox)
            key       = f"current_modis_2024_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
            local, _  = fetch_and_cache(url, key, ext="jpg")
            src       = "MODIS Terra"
    else:
        if 1997 <= year <= 2016:
            src = f"RIDAM Landsat {year}"
            key = f"ridam_tiled_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
            if not IS_VERCEL:
                filename   = hashlib.md5(key.encode()).hexdigest() + ".jpg"
                filepath   = SAT_CACHE_DIR / filename
                static_url = f"{SAT_CACHE_URL}/{filename}"
                if filepath.exists() and filepath.stat().st_size > 10_000:
                    local = static_url
                else:
                    img_bytes, _ = fetch_ridam_tiled(year, bbox)
                    if img_bytes:
                        filepath.write_bytes(img_bytes)
                        local = static_url
            else:
                img_bytes, _ = fetch_ridam_tiled(year, bbox)
                if img_bytes:
                    local = _image_to_url(img_bytes, key, "jpg")

            if not local:
                url, src  = get_modis_url(max(year, 2000), bbox)
                key       = f"birth_modis_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
                local, ok = fetch_and_cache(url, key, ext="jpg")
                src       = "MODIS Terra"
                if not ok:
                    url, _   = get_modis_url(2000, bbox)
                    key      = f"birth_modis_2000_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
                    local, _ = fetch_and_cache(url, key, ext="jpg")
                    src      = "MODIS Terra"

        elif year >= 2016:
            url, src  = get_sentinel_url(year, bbox)
            key       = f"birth_s2_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
            local, ok = fetch_and_cache(url, key, ext="jpg")
            if not ok:
                url, src  = get_modis_url(year, bbox)
                key       = f"birth_modis_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
                local, _  = fetch_and_cache(url, key, ext="jpg")
                src       = "MODIS Terra"

        else:
            url, src  = get_modis_url(max(year, 2000), bbox)
            key       = f"birth_modis_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
            local, ok = fetch_and_cache(url, key, ext="jpg")
            src       = "MODIS Terra"
            if not ok:
                url, _   = get_modis_url(2000, bbox)
                key      = f"birth_modis_2000_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
                local, _ = fetch_and_cache(url, key, ext="jpg")
                src      = "MODIS Terra"

    return jsonify({"url": local or "", "src_label": f"📡 {src}", "bbox": bbox})


# ══════════════════════════════════════════════════
# Static GeoJSON routes  (served from public/)
# ══════════════════════════════════════════════════

@app.route("/bihar_dist_ready.geojson")
def bihar_geojson():
    """public/bihar_dist_ready.geojson"""
    return send_from_directory(PUBLIC_DIR, "bihar_dist_ready.geojson")


@app.route("/blocks/<path:filename>")
def serve_block_file(filename):
    """public/blocks/DISTRICT.geojson"""
    return send_from_directory(os.path.join(PUBLIC_DIR, "blocks"), filename)


@app.route("/panchayats/<path:filename>")
def serve_panchayat_file(filename):
    """public/panchayats/DISTRICT__BLOCK.geojson"""
    return send_from_directory(os.path.join(PUBLIC_DIR, "panchayats"), filename)


@app.route("/api/blocks")
def api_blocks():
    district = request.args.get("district", "").strip()
    if not district:
        return jsonify({"error": "district required"}), 400

    blocks_dir = Path(PUBLIC_DIR) / "blocks"
    stem       = resolve_district_stem(district)   # ← changed
    geo_path   = find_geojson(blocks_dir, stem)

    if not geo_path:
        print(f"[blocks] not found: {stem}.geojson  (input: {district})")
        return jsonify({"error": "not found", "features": []}), 404

    return app.response_class(response=geo_path.read_bytes(),
                              status=200, mimetype="application/json")


@app.route("/api/panchayats")
def api_panchayats():
    district = request.args.get("district", "").strip()
    block    = request.args.get("block",    "").strip()
    if not district or not block:
        return jsonify({"error": "district and block required"}), 400

    panch_dir = Path(PUBLIC_DIR) / "panchayats"
    d_stem    = resolve_district_stem(district)    # ← changed
    stem      = f"{d_stem}__{norm_name(block)}"
    geo_path  = find_geojson(panch_dir, stem)

    if not geo_path:
        print(f"[panchayats] not found: {stem}.geojson")
        return jsonify({"error": "not found", "features": []}), 404

    return app.response_class(response=geo_path.read_bytes(),
                              status=200, mimetype="application/json")



# ══════════════════════════════════════════════════
# API: single block boundary for satellite overlay
# Filters one block feature from the district file
# ══════════════════════════════════════════════════

@app.route("/api/block_geojson")
def api_block_geojson():
    district = request.args.get("district", "").strip()
    block    = request.args.get("block",    "").strip()
    if not district or not block:
        return jsonify({"error": "district and block required"}), 400

    blocks_dir = Path(PUBLIC_DIR) / "blocks"
    geo_path   = find_geojson(blocks_dir, norm_name(district))

    if not geo_path:
        return jsonify({"error": "not found", "features": []}), 404

    try:
        gj   = json.loads(geo_path.read_text(encoding="utf-8"))
        norm = lambda s: str(s).lower().replace(" ", "").replace("_", "").replace("-", "")
        feats = [
            f for f in gj.get("features", [])
            if norm(
                f.get("properties", {}).get("block_name", "") or
                f.get("properties", {}).get("Block_Name", "") or
                f.get("properties", {}).get("name", "")
            ) == norm(block)
        ]
        return jsonify({"type": "FeatureCollection", "features": feats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════
# API: single panchayat boundary for satellite overlay
# Loads DISTRICT__BLOCK.geojson and filters one panchayat
# ══════════════════════════════════════════════════

@app.route("/api/panchayat_geojson")
def api_panchayat_geojson():
    district  = request.args.get("district",  "").strip()
    block     = request.args.get("block",     "").strip()
    panchayat = request.args.get("panchayat", "").strip()
    if not district or not block or not panchayat:
        return jsonify({"error": "district, block and panchayat required"}), 400

    panch_dir = Path(PUBLIC_DIR) / "panchayats"
    stem      = f"{norm_name(district)}__{norm_name(block)}"
    geo_path  = find_geojson(panch_dir, stem)

    if not geo_path:
        print(f"[panchayat_geojson] not found: {stem}.geojson")
        return jsonify({"error": "not found", "features": []}), 404

    try:
        gj   = json.loads(geo_path.read_text(encoding="utf-8"))
        norm = lambda s: str(s).lower().replace(" ", "").replace("_", "").replace("-", "")
        feats = [
            f for f in gj.get("features", [])
            if norm(
                f.get("properties", {}).get("panchayat_name", "") or
                f.get("properties", {}).get("Panchayat_Name", "") or
                f.get("properties", {}).get("name", "")
            ) == norm(panchayat)
        ]
        return jsonify({"type": "FeatureCollection", "features": feats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════
# Debug endpoint
# ══════════════════════════════════════════════════

@app.route("/api/debug_ridam")
def debug_ridam():
    year = int(request.args.get("year", 2005))
    bbox = compute_padded_bbox(None)
    img_bytes, _ = fetch_ridam_tiled(year, bbox)
    if img_bytes:
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        return f'<img src="data:image/jpeg;base64,{b64}" style="max-width:100%;"/>'
    return "RIDAM tiled fetch failed — check server logs", 500


@app.route("/api/debug_paths")
def debug_paths():
    """Quick sanity check — visit this URL to verify all paths exist."""
    blocks_dir = Path(PUBLIC_DIR) / "blocks"
    panch_dir  = Path(PUBLIC_DIR) / "panchayats"
    return jsonify({
        "public_dir":       PUBLIC_DIR,
        "public_exists":    os.path.isdir(PUBLIC_DIR),
        "blocks_exists":    blocks_dir.exists(),
        "panchayats_exists":panch_dir.exists(),
        "blocks_count":     len(list(blocks_dir.glob("*.geojson"))) if blocks_dir.exists() else 0,
        "panchayats_count": len(list(panch_dir.glob("*.geojson"))) if panch_dir.exists() else 0,
        "dist_geojson":     os.path.exists(os.path.join(PUBLIC_DIR, "bihar_dist_ready.geojson")),
    })


# ══════════════════════════════════════════════════
# Load Events
# ══════════════════════════════════════════════════

def load_events():
    events   = []
    csv_path = os.path.join(BASE_DIR, "data", "events.csv")
    if not os.path.exists(csv_path):
        return events

    def icon(t):
        for kw, em in C.ICON_MAP.items():
            if kw in t.lower(): return em
        return C.DEFAULT_ICON

    def get_era(yr):
        for e in C.ERAS:
            if e["start"] <= yr <= e["end"]: return e["label"], e["color"]
        return "Recent", C.ERAS[-1]["color"]

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yr     = int(row["Year"])
            el, ec = get_era(yr)
            cands  = []
            for i in range(1, 6):
                ev = row.get(f"Event_{i}", "").strip()
                sc = row.get(f"Positivity_Score_{i}", "0").strip()
                if ev:
                    try: sc = int(sc)
                    except: sc = 5
                    cands.append({"title": ev, "score": sc})
            cands.sort(key=lambda x: x["score"], reverse=True)
            for ev in cands[:C.EVENTS_PER_YEAR]:
                events.append({
                    "year": yr, "title": ev["title"], "icon": icon(ev["title"]),
                    "era": el, "color": ec, "score": ev["score"]
                })
    events.sort(key=lambda x: x["year"])
    return events


ALL_EVENTS = load_events()


# ══════════════════════════════════════════════════
# API: block names — scans panchayats/ filenames
# GET /api/block_names?district=PURBI%20CHAMPARAN
# Returns {"blocks": ["Adapur", "Areraj", ...]}
# ══════════════════════════════════════════════════
@app.route("/api/block_names")
def api_block_names():
    district = request.args.get("district", "").strip()
    if not district:
        return jsonify({"error": "district required"}), 400

    panch_dir = Path(PUBLIC_DIR) / "panchayats"
    norm_dist = norm_name(district)
    blocks = set()

    # Primary: exact prefix match  DISTRICT__BLOCK.geojson
    for f in panch_dir.glob(f"{norm_dist}__*.geojson"):
        block_raw = f.stem.split("__", 1)[1]          # e.g. "ADAPUR"
        blocks.add(block_raw.replace("_", " ").title())

    # Fallback: case-insensitive scan
    if not blocks:
        for f in panch_dir.glob("*.geojson"):
            if "__" not in f.stem:
                continue
            d_part, b_part = f.stem.split("__", 1)
            if d_part.lower() == norm_dist.lower():
                blocks.add(b_part.replace("_", " ").title())

    return jsonify({"district": district, "blocks": sorted(blocks)})


# ══════════════════════════════════════════════════
# API: panchayat names — reads features from GeoJSON
# GET /api/panchayat_names?district=X&block=Y
# Returns {"panchayats": ["Aam Tola", ...]}
# ══════════════════════════════════════════════════
@app.route("/api/panchayat_names")
def api_panchayat_names():
    district = request.args.get("district", "").strip()
    block    = request.args.get("block",    "").strip()
    if not district or not block:
        return jsonify({"error": "district and block required"}), 400

    panch_dir = Path(PUBLIC_DIR) / "panchayats"
    stem      = f"{norm_name(district)}__{norm_name(block)}"
    geo_path  = find_geojson(panch_dir, stem)

    if not geo_path:
        return jsonify({"panchayats": [], "error": f"{stem}.geojson not found"}), 404

    try:
        gj    = json.loads(geo_path.read_text(encoding="utf-8"))
        names = []
        for feat in gj.get("features", []):
            p = feat.get("properties", {})
            name = (p.get("panchayat_name") or p.get("Panchayat_Name") or
                    p.get("PANCHAYAT_NAME") or p.get("village_name") or
                    p.get("name") or p.get("NAME") or "")
            if name:
                names.append(name)
        return jsonify({"panchayats": sorted(set(names))})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html",
        app_title    = C.APP_TITLE,
        app_subtitle = C.APP_SUBTITLE,
        app_logo     = C.APP_LOGO_EMOJI,
        app_footer   = C.APP_FOOTER
    )


@app.route("/map")
def map_page():
    name       = request.args.get("name", "").strip()
    birth_year = request.args.get("birth_year", "").strip()
    if not name or not birth_year:
        return redirect(url_for("index"))
    return render_template("map.html", name=name, birth_year=birth_year, app_title=C.APP_TITLE)


@app.route("/analyse", methods=["GET", "POST"])
def analyse():
    if request.method == "GET":
        return redirect(url_for("index"))

    name       = request.form.get("name",       "").strip()
    birth_year = request.form.get("birth_year", "").strip()
    district   = request.form.get("district",   "").strip()
    block      = request.form.get("block",      "").strip()
    panchayat  = request.form.get("panchayat",  "").strip()

    if not name or not birth_year or not district:
        return redirect(url_for("index"))

    try:
        by    = int(birth_year)
        today = date.today()
        age   = today.year - by - (today.month < 7)
    except Exception:
        return redirect(url_for("index"))

    bbox       = parse_bbox(request.form.get("bbox",       "{}"))
    block_bbox = parse_bbox(request.form.get("block_bbox", "{}"))
    panch_bbox = parse_bbox(request.form.get("panch_bbox", "{}"))

    # Fallback: if block selected but no specific block bbox, use district bbox
    if block and not block_bbox and bbox:
        block_bbox = bbox

    evs = [e for e in ALL_EVENTS if e["year"] >= by]

    return render_template(
        "result.html",
        name         = name,
        birth_year   = by,
        age          = age,
        district     = district,
        block        = block     or None,
        panchayat    = panchayat or None,
        bbox         = bbox,
        block_bbox   = block_bbox,
        panch_bbox   = panch_bbox,
        events       = evs,
        eras         = C.ERAS,
        tl_interval  = C.TIMELINE_INTERVAL_MS,
        current_year = today.year,
        app_title    = C.APP_TITLE,
    )


