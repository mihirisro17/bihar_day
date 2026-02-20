# ═══════════════════════════════════════════════════════════════════
#  config.py  —  Single source of truth for Bihar Analyser
#  Change anything here; the app picks it up automatically.
# ═══════════════════════════════════════════════════════════════════

# ── Branding ──────────────────────────────────────────────────────
APP_TITLE        = "Bihar Through Your Years"
APP_SUBTITLE     = "GOVERNMENT OF BIHAR  ·  EXHIBITION 2026"
APP_LOGO_EMOJI   = "🌸"
APP_FOOTER       = "Powered by VEDAS, SAC, ISRO, Government of India"

# ── Theme colours (CSS variables injected into every template) ─────
THEME = {
    "gold":    "#FFD700",
    "saffron": "#FF6B35",
    "deep":    "#0D0D2B",
    "orb1":    "#7B2FBE",
    "orb2":    "#FF6B35",
    "orb3":    "#0066ff",
}

# ── Transition on Analyse click ───────────────────────────────────
#  ring1_color  → first burst color
#  ring2_color  → second burst color
#  ring3_bg     → final fill (destination background)
#  ring3_symbol → emoji shown at centre of ring3
#  submit_delay_ms → ms to wait before form.submit()
TRANSITION = {
    "ring1_color":    "#FF6B35",
    "ring2_color":    "#FFD700",
    "ring3_bg":       "linear-gradient(135deg,#0D0D2B 0%,#1a0533 50%,#001a3a 100%)",
    "ring3_symbol":   "🌸",
    "submit_delay_ms": 720,
}

# ── Bihar Districts ───────────────────────────────────────────────
DISTRICTS = [
    "Araria","Arwal","Aurangabad","Banka","Begusarai","Bhagalpur",
    "Bhojpur","Buxar","Darbhanga","East Champaran","Gaya","Gopalganj",
    "Jamui","Jehanabad","Kaimur","Katihar","Khagaria","Kishanganj",
    "Lakhisarai","Madhepura","Madhubani","Munger","Muzaffarpur","Nalanda",
    "Nawada","Patna","Purnia","Rohtas","Saharsa","Samastipur","Saran",
    "Sheikhpura","Sheohar","Sitamarhi","Siwan","Supaul","Vaishali",
    "West Champaran",
]

# ── Era definitions ────────────────────────────────────────────────
#  Each era: start year (inclusive), label, dot/badge color
ERAS = [
    {"start": 1900, "end": 1946, "label": "British Era",       "color": "#FF9632"},
    {"start": 1947, "end": 1969, "label": "Post-Independence", "color": "#32D878"},
    {"start": 1970, "end": 1999, "label": "Modern Era",        "color": "#6496FF"},
    {"start": 2000, "end": 9999, "label": "Recent",            "color": "#C864FF"},
]

# ── Icon map  (keyword → emoji, applied to event title) ───────────
ICON_MAP = {
    "flood":"🌊","earthquake":"🌍","famine":"🌾","drought":"🏜️",
    "war":"⚔️","independence":"🇮🇳","election":"🗳️","bridge":"🌉",
    "railway":"🚂","road":"🛣️","industry":"🏭","education":"📚",
    "university":"🎓","hospital":"🏥","festival":"🎉","chhath":"🙏",
    "sonepur":"🐘","mela":"🎪","gandhi":"✊","movement":"✊",
    "constitution":"📜","court":"⚖️","partition":"✂️","riot":"🔥",
    "covid":"🦠","vaccine":"💉","economy":"📈","growth":"📈",
    "poverty":"📉","technology":"💻","airport":"✈️","highway":"🛣️",
    "sports":"🏆","award":"🏅","women":"👩","agriculture":"🌱",
    "milk":"🥛","export":"📦","culture":"🎭","art":"🎨",
    "literature":"📖","music":"🎵","heritage":"🏛️","buddhist":"☸️",
    "patna":"🏙️","bihar":"🌸",
}
DEFAULT_ICON = "📌"

# ── Timeline auto-advance interval (ms) ──────────────────────────
TIMELINE_INTERVAL_MS = 10000

# ── How many events per year to pick (picks highest positivity) ──
EVENTS_PER_YEAR = 1