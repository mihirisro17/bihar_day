

from flask import Flask, render_template, request, redirect, url_for
from datetime import date
import csv, os, sys

BASE_DIR = os.getcwd()

sys.path.insert(0, BASE_DIR)
import config as C

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates")
)

# ----------------------------
# Utility
# ----------------------------

def _norm(s):
    return "".join(str(s).lower().split()).replace("-", "").replace("(", "").replace(")", "")

# ----------------------------
# Load Events (cached once)
# ----------------------------

def load_events():
    events = []
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
            yr = int(row["Year"])
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
                    "year": yr,
                    "title": ev["title"],
                    "icon": icon(ev["title"]),
                    "era": el,
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
    name = request.args.get("name", "").strip()
    birth_year = request.args.get("birth_year", "").strip()

    if not name or not birth_year:
        return redirect(url_for("index"))

    return render_template(
        "map.html",
        name=name,
        birth_year=birth_year,
        app_title=C.APP_TITLE
    )


import json

@app.route("/analyse", methods=["GET", "POST"])
def analyse():

    if request.method == "GET":
        return redirect(url_for("index"))

    name = request.form.get("name", "").strip()
    birth_year = request.form.get("birth_year", "").strip()
    district = request.form.get("district", "").strip()
    bbox_raw = request.form.get("bbox", "{}")

    if not name or not birth_year or not district:
        return redirect(url_for("index"))

    try:
        by = int(birth_year)
        today = date.today()
        age = today.year - by - (today.month < 7)
    except:
        return redirect(url_for("index"))

    try:
        bbox = json.loads(bbox_raw)
        if not bbox:     # catches {} empty dict if field ever missing again
            bbox = None
    except:
        bbox = None

    evs = [e for e in ALL_EVENTS if e["year"] >= by]

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
        current_year=date.today().year,
        app_title=C.APP_TITLE
    )
