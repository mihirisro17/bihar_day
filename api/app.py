from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from datetime import date
import csv, os, sys, json, hashlib, requests
from pathlib import Path
import base64  


BASE_DIR = os.getcwd()
sys.path.insert(0, BASE_DIR)
import config as C

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

# ── Cache dir ──
IS_VERCEL     = bool(os.environ.get("VERCEL", ""))
SAT_CACHE_DIR = Path("/tmp/sat_cache") if IS_VERCEL else Path(BASE_DIR) / "static" / "sat_cache"
SAT_CACHE_URL = "/sat_cache"           if IS_VERCEL else "/static/sat_cache"
SAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

EOX_AVAIL    = [2016,2017,2018,2019,2020,2021,2022,2023,2024]
SAT_W, SAT_H = 1600, 900
TARGET_AR    = 16 / 9
KM30_LAT, KM30_LNG = 0.27, 0.30


# ----------------------------
# Utility
# ----------------------------

def _norm(s):
    return "".join(str(s).lower().split()).replace("-","").replace("(","").replace(")","")


# ----------------------------
# Satellite helpers
# ----------------------------

def compute_padded_bbox(raw_bbox):
    if not raw_bbox:
        raw_bbox = {"minLng":83.3,"minLat":24.3,"maxLng":88.2,"maxLat":27.5}
    exp = {
        "minLng": raw_bbox["minLng"] - KM30_LNG,
        "maxLng": raw_bbox["maxLng"] + KM30_LNG,
        "minLat": raw_bbox["minLat"] - KM30_LAT,
        "maxLat": raw_bbox["maxLat"] + KM30_LAT,
    }
    lng_span = exp["maxLng"] - exp["minLng"]
    lat_span = exp["maxLat"] - exp["minLat"]
    cx = (exp["maxLng"] + exp["minLng"]) / 2
    cy = (exp["maxLat"] + exp["minLat"]) / 2
    pW = lng_span * 1.5
    pH = lat_span * 1.5
    if pW / pH > TARGET_AR: pH = pW / TARGET_AR
    else: pW = pH * TARGET_AR
    return {
        "minLng": round(cx - pW/2, 6), "maxLng": round(cx + pW/2, 6),
        "minLat": round(cy - pH/2, 6), "maxLat": round(cy + pH/2, 6),
    }


def _bq(bbox):
    """WMS 1.1.1 — SRS EPSG:4326, axis order: minLng,minLat,maxLng,maxLat"""
    b = f"{bbox['minLng']},{bbox['minLat']},{bbox['maxLng']},{bbox['maxLat']}"
    return f"&STYLES=&SRS=EPSG:4326&BBOX={b}&WIDTH={SAT_W}&HEIGHT={SAT_H}&FORMAT=image/jpeg"


def _bq_latlng(bbox):
    """WMS 1.3.0 — CRS EPSG:4326, axis order FLIPPED: minLat,minLng,maxLat,maxLng"""
    b = f"{bbox['minLat']},{bbox['minLng']},{bbox['maxLat']},{bbox['maxLng']}"
    return f"&STYLES=&CRS=EPSG:4326&BBOX={b}&WIDTH={SAT_W}&HEIGHT={SAT_H}&FORMAT=image/png"


def get_sentinel_url(year, bbox):
    """EOX Sentinel-2 cloudless — 2016 to 2024."""
    y = year if year in EOX_AVAIL else max(
        (v for v in EOX_AVAIL if v <= year), default=EOX_AVAIL[-1]
    )
    return (
        f"https://tiles.maps.eox.at/wms?SERVICE=WMS&VERSION=1.1.1"
        f"&REQUEST=GetMap&LAYERS=s2cloudless-{y}{_bq(bbox)}",
        "Sentinel-2"
    )


def get_modis_url(year, bbox):
    """NASA GIBS MODIS Terra — pre-1997 fallback only."""
    y = min(max(year, 2000), 2024)
    return (
        f"https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
        f"?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
        f"&TIME={y}-06-15{_bq(bbox)}",
        "MODIS Terra"
    )


def get_ridam_url(year, bbox):
    """
    ISRO/SAC RIDAM — Landsat dataset T0S1P11, RGB composite.
    Available: 1997–2016. Fixed date: Dec 31 of each year.
    """
    from urllib.parse import quote, urlencode

    date_str = f"{year}1231"

    # Build ARGS string — colons and semicolons MUST be percent-encoded (%3A, %3B)
    # exactly as the original RIDAM URL requires. safe='' encodes everything.
    args_raw = ";".join([
        "r_dataset_id:T0S1P11", "g_dataset_id:T0S1P11", "b_dataset_id:T0S1P11",
        f"r_from_time:{date_str}", f"r_to_time:{date_str}",
        f"g_from_time:{date_str}", f"g_to_time:{date_str}",
        f"b_from_time:{date_str}", f"b_to_time:{date_str}",
        "r_index:1", "g_index:2", "b_index:3",
        "r_max:50",  "g_max:50",  "b_max:50",
    ])
    args_encoded = quote(args_raw, safe='')  # encodes : → %3A and ; → %3B

    # WMS 1.3.0 EPSG:4326 — BBOX axis order is minLat,minLng,maxLat,maxLng
    bbox_str = f"{bbox['minLat']},{bbox['minLng']},{bbox['maxLat']},{bbox['maxLng']}"

    params = urlencode({
        "SERVICE":    "WMS",
        "VERSION":    "1.3.0",
        "REQUEST":    "GetMap",
        "FORMAT":     "image/png",
        "TRANSPARENT":"true",
        "name":       "RIDAM_RGB",
        "layers":     "T0S0M1",
        "PROJECTION": "EPSG:4326",
        "ARGS":       args_raw,      # urlencode handles encoding of the value
        "WIDTH":      SAT_W,
        "HEIGHT":     SAT_H,
        "CRS":        "EPSG:4326",
        "STYLES":     "",
        "BBOX":       bbox_str,
    })

    url = f"https://vedas.sac.gov.in/ridam/wms?{params}"
    return url, f"RIDAM Landsat {year}"



def get_birth_url(year, bbox):
    """
    Source selection by birth year:
      1997–2016 → RIDAM Landsat (ISRO/SAC), Dec 31 of that year  [fetched server-side]
      2016+     → Sentinel-2 cloudless (EOX), sharpest 10 m
      pre-1997  → MODIS Terra (NASA GIBS)
    """
    if 1997 <= year <= 2016:
        return get_ridam_url(year, bbox)
    if year >= 2016:
        return get_sentinel_url(year, bbox)
    return get_modis_url(year, bbox)


# def fetch_and_cache(url, cache_key, ext="jpg"):
#     """
#     Server-side fetch + local cache.
#     ext = 'jpg' for Sentinel/MODIS, 'png' for RIDAM.
#     Avoids all browser CORS restrictions.
#     """
#     filename   = hashlib.md5(cache_key.encode()).hexdigest() + f".{ext}"
#     filepath   = SAT_CACHE_DIR / filename
#     static_url = f"{SAT_CACHE_URL}/{filename}"
#     if filepath.exists() and filepath.stat().st_size > 10_000:
#         return static_url, True
#     try:
#         resp = requests.get(url, timeout=30, headers={"User-Agent": "BiharDiwas/1.0"})
#         ct   = resp.headers.get("content-type", "")
#         if resp.status_code == 200 and "image" in ct:
#             filepath.write_bytes(resp.content)
#             return static_url, True
#         print(f"[SAT] Bad response {resp.status_code} ct={ct} for {url[:120]}")
#     except Exception as e:
#         print(f"[SAT] Fetch failed: {e}")
#     return None, False
def fetch_and_cache(url, cache_key, ext="jpg"):
    mime = "image/png" if ext == "png" else "image/jpeg"

    if not IS_VERCEL:
        filename   = hashlib.md5(cache_key.encode()).hexdigest() + f".{ext}"
        filepath   = SAT_CACHE_DIR / filename
        static_url = f"{SAT_CACHE_URL}/{filename}"
        if filepath.exists() and filepath.stat().st_size > 10_000:
            return static_url, True
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "BiharDiwas/1.0"})
            ct   = resp.headers.get("content-type", "")
            print(f"[SAT] {resp.status_code} ct={ct} url={url[:100]}")  # ← debug
            if resp.status_code == 200 and "image" in ct:
                filepath.write_bytes(resp.content)
                return static_url, True
        except Exception as e:
            print(f"[SAT] Fetch failed: {e}")
        return None, False
    else:
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "BiharDiwas/1.0"})
            ct   = resp.headers.get("content-type", "")
            print(f"[SAT] {resp.status_code} ct={ct} url={url[:100]}")  # ← debug
            if resp.status_code == 200 and "image" in ct:
                b64 = base64.b64encode(resp.content).decode("utf-8")
                return f"data:{mime};base64,{b64}", True
        except Exception as e:
            print(f"[SAT] Fetch failed: {e}")
        return None, False



# ----------------------------
# Sat cache routes
# ----------------------------

@app.route("/sat_cache/<filename>")
def sat_cache_vercel(filename):
    return send_from_directory(str(SAT_CACHE_DIR), filename)

@app.route("/static/sat_cache/<filename>")
def sat_cache_local(filename):
    return send_from_directory(str(SAT_CACHE_DIR), filename)


# ----------------------------
# API: fetch one satellite image  (called by result.html JS)
# ----------------------------

@app.route("/api/sat_image")
def api_sat_image():
    img_type = request.args.get("type", "birth")
    try:
        year = int(request.args.get("year", 2000))
    except:
        return jsonify({"error": "bad year"}), 400

    try:
        raw_bbox = json.loads(request.args.get("bbox", "{}"))
    except:
        raw_bbox = None

    bbox = compute_padded_bbox(raw_bbox)

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
        # Birth year — RIDAM for 1997-2016 (server-side, no CORS)
        url, src  = get_birth_url(year, bbox)
        is_ridam  = (1997 <= year <= 2016)
        ext       = "png" if is_ridam else "jpg"

        key       = f"birth_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
        local, ok = fetch_and_cache(url, key, ext=ext)

        if not ok:
            # Fallback 1 — MODIS
            url, src  = get_modis_url(max(year, 2000), bbox)
            key       = f"birth_modis_{year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
            local, ok = fetch_and_cache(url, key, ext="jpg")
            src       = "MODIS Terra"

        if not ok:
            # Fallback 2 — MODIS 2000 absolute last resort
            url, src  = get_modis_url(2000, bbox)
            key       = f"birth_modis_2000_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
            local, _  = fetch_and_cache(url, key, ext="jpg")
            src       = "MODIS Terra"

    return jsonify({
        "url":       local or "",
        "src_label": f"📡 {src}",
        "bbox":      bbox
    })


# ----------------------------
# Load Events
# ----------------------------

def load_events():
    events   = []
    csv_path = os.path.join(BASE_DIR, "data", "events.csv")
    if not os.path.exists(csv_path): return events

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
                ev = row.get(f"Event_{i}","").strip()
                sc = row.get(f"Positivity_Score_{i}","0").strip()
                if ev:
                    try: sc = int(sc)
                    except: sc = 5
                    cands.append({"title":ev,"score":sc})
            cands.sort(key=lambda x: x["score"], reverse=True)
            for ev in cands[:C.EVENTS_PER_YEAR]:
                events.append({
                    "year":yr,"title":ev["title"],"icon":icon(ev["title"]),
                    "era":el,"color":ec,"score":ev["score"]
                })

    events.sort(key=lambda x: x["year"])
    return events

ALL_EVENTS = load_events()


# ----------------------------
# Routes
# ----------------------------

@app.route("/")
def index():
    return render_template("index.html",
        app_title=C.APP_TITLE, app_subtitle=C.APP_SUBTITLE,
        app_logo=C.APP_LOGO_EMOJI, app_footer=C.APP_FOOTER)

@app.route("/map")
def map_page():
    name       = request.args.get("name","").strip()
    birth_year = request.args.get("birth_year","").strip()
    if not name or not birth_year: return redirect(url_for("index"))
    return render_template("map.html", name=name, birth_year=birth_year, app_title=C.APP_TITLE)


@app.route("/analyse", methods=["GET","POST"])
def analyse():
    if request.method == "GET": return redirect(url_for("index"))

    name       = request.form.get("name","").strip()
    birth_year = request.form.get("birth_year","").strip()
    district   = request.form.get("district","").strip()
    bbox_raw   = request.form.get("bbox","{}")

    if not name or not birth_year or not district:
        return redirect(url_for("index"))

    try:
        by    = int(birth_year)
        today = date.today()
        age   = today.year - by - (today.month < 7)
    except:
        return redirect(url_for("index"))

    try:
        bbox = json.loads(bbox_raw)
        if not bbox: bbox = None
    except:
        bbox = None

    evs = [e for e in ALL_EVENTS if e["year"] >= by]

    return render_template(
        "result.html",
        name=name, birth_year=by, age=age,
        district=district, bbox=bbox, events=evs,
        eras=C.ERAS, tl_interval=C.TIMELINE_INTERVAL_MS,
        current_year=today.year, app_title=C.APP_TITLE,
    )
