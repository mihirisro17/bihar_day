from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from datetime import date
import csv, os, sys, json, hashlib, requests
from pathlib import Path

BASE_DIR = os.getcwd()
sys.path.insert(0, BASE_DIR)
import config as C

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates")
)

# ── Satellite cache directory ──
SAT_CACHE_DIR = Path(BASE_DIR) / "static" / "sat_cache"
SAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

EOX_AVAIL      = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]
LANDSAT_MIN    = 2000
LANDSAT_MAX    = 2012
SAT_W, SAT_H   = 1600, 900
TARGET_AR      = 16 / 9
KM30_LAT       = 0.27
KM30_LNG       = 0.30

# ----------------------------
# Utility
# ----------------------------

def _norm(s):
    return "".join(str(s).lower().split()).replace("-", "").replace("(", "").replace(")", "")


# ----------------------------
# Satellite helpers
# ----------------------------

def compute_padded_bbox(raw_bbox):
    """
    Mirrors the JS BBOX math exactly.
    Adds ~30 km buffer then pads to 16:9 aspect ratio.
    Returns dict with minLng/maxLng/minLat/maxLat.
    """
    if not raw_bbox:
        # Bihar state fallback
        raw_bbox = {"minLng": 83.3, "minLat": 24.3, "maxLng": 88.2, "maxLat": 27.5}

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
    if pW / pH > TARGET_AR:
        pH = pW / TARGET_AR
    else:
        pW = pH * TARGET_AR

    return {
        "minLng": round(cx - pW / 2, 6),
        "maxLng": round(cx + pW / 2, 6),
        "minLat": round(cy - pH / 2, 6),
        "maxLat": round(cy + pH / 2, 6),
    }


def _base_query(bbox):
    b = f"{bbox['minLng']},{bbox['minLat']},{bbox['maxLng']},{bbox['maxLat']}"
    return f"&STYLES=&SRS=EPSG:4326&BBOX={b}&WIDTH={SAT_W}&HEIGHT={SAT_H}&FORMAT=image/jpeg"


def get_sentinel_url(year, bbox):
    y = year if year in EOX_AVAIL else max(
        (v for v in EOX_AVAIL if v <= year), default=EOX_AVAIL[-1]
    )
    q = _base_query(bbox)
    return (
        f"https://tiles.maps.eox.at/wms?SERVICE=WMS&VERSION=1.1.1"
        f"&REQUEST=GetMap&LAYERS=s2cloudless-{y}{q}",
        "Sentinel-2"
    )


def get_landsat_url(year, bbox):
    y = min(max(year, LANDSAT_MIN), LANDSAT_MAX)
    q = _base_query(bbox)
    return (
        f"https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
        f"?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS=Landsat_WELD_CorrectedReflectance_TrueColor_Global_Annual"
        f"&TIME={y}-01-01{q}",
        "Landsat"
    )


def get_modis_url(year, bbox):
    y = max(year, 2000)
    q = _base_query(bbox)
    return (
        f"https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
        f"?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor"
        f"&TIME={y}-03-15{q}",
        "MODIS Terra"
    )


def get_birth_url(year, bbox):
    """Pick best source for birth year."""
    if year >= 2016:
        return get_sentinel_url(year, bbox)
    if LANDSAT_MIN <= year <= LANDSAT_MAX:
        return get_landsat_url(year, bbox)
    return get_modis_url(year, bbox)


def fetch_and_cache(url, cache_key):
    """
    Download image if not already cached.
    Returns (static_url_path, success_bool).
    """
    filename  = hashlib.md5(cache_key.encode()).hexdigest() + ".jpg"
    filepath  = SAT_CACHE_DIR / filename
    static_url = f"/static/sat_cache/{filename}"

    if filepath.exists() and filepath.stat().st_size > 10_000:
        # Already cached and looks valid (>10 KB)
        return static_url, True

    try:
        resp = requests.get(
            url, timeout=30,
            headers={"User-Agent": "BiharDiwas/1.0"}
        )
        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 200 and "image" in content_type:
            filepath.write_bytes(resp.content)
            return static_url, True
        else:
            print(f"[SAT] Bad response {resp.status_code} for {url}")
    except Exception as e:
        print(f"[SAT] Fetch failed: {e}")

    return None, False


def prefetch_satellite_images(birth_year, raw_bbox):
    """
    Called during /analyse route.
    Fetches both satellite images server-side before rendering.
    Returns dict with local static URLs + source labels.
    """
    bbox = compute_padded_bbox(raw_bbox)

    # ── Birth year image ──
    birth_url, birth_src = get_birth_url(birth_year, bbox)
    birth_cache_key      = f"birth_{birth_year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
    birth_local, ok      = fetch_and_cache(birth_url, birth_cache_key)

    # Landsat fallback → MODIS
    if not ok and LANDSAT_MIN <= birth_year <= LANDSAT_MAX:
        print(f"[SAT] Landsat failed for {birth_year}, trying MODIS...")
        birth_url, birth_src = get_modis_url(birth_year, bbox)
        birth_cache_key      = f"birth_modis_{birth_year}_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
        birth_local, ok      = fetch_and_cache(birth_url, birth_cache_key)

    # MODIS fallback → any available year
    if not ok:
        print(f"[SAT] All sources failed for birth {birth_year}, using 2000")
        birth_url, birth_src = get_modis_url(2000, bbox)
        birth_cache_key      = f"birth_modis_2000_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
        birth_local, _       = fetch_and_cache(birth_url, birth_cache_key)
        birth_src            = "MODIS Terra"

    # ── 2026 / current image ──
    current_url, current_src = get_sentinel_url(2026, bbox)
    current_cache_key        = f"current_2026_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
    current_local, ok        = fetch_and_cache(current_url, current_cache_key)

    if not ok:
        print("[SAT] Sentinel-2 failed for 2026, trying MODIS...")
        current_url, current_src = get_modis_url(2024, bbox)
        current_cache_key        = f"current_modis_2024_{bbox['minLng']:.3f}_{bbox['minLat']:.3f}"
        current_local, _         = fetch_and_cache(current_url, current_cache_key)
        current_src              = "MODIS Terra"

    return {
        "birth_img_url":    birth_local   or "",
        "birth_src_label":  f"📡 {birth_src}",
        "current_img_url":  current_local or "",
        "current_src_label": f"📡 {current_src}",
        "padded_bbox":       bbox,
    }


# Serve cached satellite images
@app.route("/static/sat_cache/<filename>")
def sat_cache(filename):
    return send_from_directory(str(SAT_CACHE_DIR), filename)


# ----------------------------
# Load Events (cached once)
# ----------------------------

def load_events():
    events   = []
    csv_path = os.path.join(BASE_DIR, "data", "events.csv")

    if not os.path.exists(csv_path):
        return events

    def icon(t):
        for kw, em in C.ICON_MAP.items():
            if kw in t.lower():
                return em
        return C.DEFAULT_ICON

    def get_era(yr):
        for e in C.ERAS:
            if e["start"] <= yr <= e["end"]:
                return e["label"], e["color"]
        return "Recent", C.ERAS[-1]["color"]

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yr     = int(row["Year"])
            el, ec = get_era(yr)

            cands = []
            for i in range(1, 6):
                ev = row.get(f"Event_{i}", "").strip()
                sc = row.get(f"Positivity_Score_{i}", "0").strip()
                if ev:
                    try:
                        sc = int(sc)
                    except:
                        sc = 5
                    cands.append({"title": ev, "score": sc})

            cands.sort(key=lambda x: x["score"], reverse=True)

            for ev in cands[:C.EVENTS_PER_YEAR]:
                events.append({
                    "year":  yr,
                    "title": ev["title"],
                    "icon":  icon(ev["title"]),
                    "era":   el,
                    "color": ec,
                    "score": ev["score"]
                })

    events.sort(key=lambda x: x["year"])
    return events


ALL_EVENTS = load_events()


# ----------------------------
# Routes
# ----------------------------

@app.route("/")
def index():
    return render_template(
        "index.html",
        app_title=C.APP_TITLE,
        app_subtitle=C.APP_SUBTITLE,
        app_logo=C.APP_LOGO_EMOJI,
        app_footer=C.APP_FOOTER
    )


@app.route("/map")
def map_page():
    name       = request.args.get("name", "").strip()
    birth_year = request.args.get("birth_year", "").strip()

    if not name or not birth_year:
        return redirect(url_for("index"))

    return render_template(
        "map.html",
        name=name,
        birth_year=birth_year,
        app_title=C.APP_TITLE
    )


@app.route("/analyse", methods=["GET", "POST"])
def analyse():
    if request.method == "GET":
        return redirect(url_for("index"))

    name      = request.form.get("name", "").strip()
    birth_year = request.form.get("birth_year", "").strip()
    district  = request.form.get("district", "").strip()
    bbox_raw  = request.form.get("bbox", "{}")

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
        if not bbox:
            bbox = None
    except:
        bbox = None

    evs = [e for e in ALL_EVENTS if e["year"] >= by]

    # ── Prefetch satellite images before rendering ──
    sat = prefetch_satellite_images(by, bbox)

    return render_template(
        "result.html",
        name=name,
        birth_year=by,
        age=age,
        district=district,
        bbox=bbox,
        events=evs,
        eras=C.ERAS,
        tl_interval=C.TIMELINE_INTERVAL_MS,
        current_year=today.year,
        app_title=C.APP_TITLE,
        # Satellite preloaded data
        birth_img_url     = sat["birth_img_url"],
        birth_src_label   = sat["birth_src_label"],
        current_img_url   = sat["current_img_url"],
        current_src_label = sat["current_src_label"],
        padded_bbox       = sat["padded_bbox"],
    )
