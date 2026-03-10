"""HappyBites — Candy Glass (Aurora) design system."""

import hashlib
import os
import random as _rng
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import streamlit as st

API_URL = os.getenv("HAPPYBITES_API_URL", "http://localhost:8000")

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
SESSION_ID = st.session_state["session_id"]

DEAL_TYPES = ["Happy Hour", "Lunch Special"]
CITY_PRESETS = {
    "San Francisco": (37.7749, -122.4194),
    "New York":      (40.7128,  -74.0060),
    "Los Angeles":   (34.0522, -118.2437),
    "Austin":        (30.2672,  -97.7431),
}

# ── Mock nearby deals (shown when API returns no results) ──────────────────────

_MOCK_NEARBY: dict[str, list[dict]] = {
    "San Francisco": [
        {
            "id": 9001, "title": "Happy Hour: $6 Cocktails & Half-Off Bites",
            "merchant": "Zuni Café", "category": "Happy Hour",
            "description": "Classic SF bistro offering half-price cocktails and select appetizers every weekday 5–7 PM.",
            "deal_price": 6.00, "original_price": 13.00, "discount_pct": 54,
            "distance_m": 620, "url": "", "source": "mock",
            "rank_reasons": ["54% off", "0.6 km away", "Opens in 2 hrs"],
        },
        {
            "id": 9002, "title": "Lunch Special: Dim Sum for Two",
            "merchant": "Dragon Beaux", "category": "Lunch Special",
            "description": "Premium dim sum lunch set for two including 6 dishes and tea service — weekdays only.",
            "deal_price": 38.00, "original_price": 62.00, "discount_pct": 39,
            "distance_m": 1400, "url": "", "source": "mock",
            "rank_reasons": ["39% off", "1.4 km away", "Top-rated venue"],
        },
        {
            "id": 9003, "title": "Happy Hour All Night: $5 Wine & Cheese Plates",
            "merchant": "Bar Agricole", "category": "Happy Hour",
            "description": "Natural wine bar running all-night happy hour on Sundays — $5 pours and $8 cheese plates.",
            "deal_price": 5.00, "original_price": 12.00, "discount_pct": 58,
            "distance_m": 900, "url": "", "source": "mock",
            "rank_reasons": ["58% off", "0.9 km away"],
        },
    ],
    "New York": [
        {
            "id": 9011, "title": "Early Bird Lunch: 3-Course for $28",
            "merchant": "Balthazar", "category": "Lunch Special",
            "description": "Three-course prix-fixe lunch available Monday–Friday 11:30 AM–2:30 PM. Classic French bistro fare.",
            "deal_price": 28.00, "original_price": 52.00, "discount_pct": 46,
            "distance_m": 850, "url": "", "source": "mock",
            "rank_reasons": ["46% off", "0.9 km away", "Highly rated"],
        },
        {
            "id": 9012, "title": "Happy Hour: $8 Cocktails & $6 Drafts",
            "merchant": "230 Fifth Rooftop", "category": "Happy Hour",
            "description": "Rooftop happy hour every weekday 4–7 PM. $8 cocktails, $6 draft beers, complimentary rooftop access.",
            "deal_price": 8.00, "original_price": 18.00, "discount_pct": 56,
            "distance_m": 1100, "url": "", "source": "mock",
            "rank_reasons": ["56% off", "1.1 km away", "Open now"],
        },
        {
            "id": 9013, "title": "Lunch Special: Ramen + Gyoza Set $18",
            "merchant": "Ippudo NY", "category": "Lunch Special",
            "description": "Lunch set includes a bowl of signature tonkotsu ramen and 4-piece gyoza. Weekdays only until 3 PM.",
            "deal_price": 18.00, "original_price": 30.00, "discount_pct": 40,
            "distance_m": 1600, "url": "", "source": "mock",
            "rank_reasons": ["40% off", "1.6 km away"],
        },
    ],
    "Los Angeles": [
        {
            "id": 9021, "title": "Taco Tuesday Lunch: $2 Street Tacos",
            "merchant": "Guerrilla Tacos", "category": "Lunch Special",
            "description": "Every Tuesday, all street tacos are $2 each. Mix and match proteins — carne asada, carnitas, veggie.",
            "deal_price": 2.00, "original_price": 5.00, "discount_pct": 60,
            "distance_m": 740, "url": "", "source": "mock",
            "rank_reasons": ["60% off", "0.7 km away", "Fan favourite"],
        },
        {
            "id": 9022, "title": "Happy Hour: $5 Margaritas & Free Chips",
            "merchant": "El Compadre", "category": "Happy Hour",
            "description": "Daily happy hour 3–7 PM. $5 house margaritas, $4 beers, complimentary chips and salsa.",
            "deal_price": 5.00, "original_price": 13.00, "discount_pct": 62,
            "distance_m": 1200, "url": "", "source": "mock",
            "rank_reasons": ["62% off", "1.2 km away"],
        },
        {
            "id": 9023, "title": "Lunch Special: Bao Set for $15",
            "merchant": "Majordomo", "category": "Lunch Special",
            "description": "Lunch bao set — three filled bao, house pickles, and a soft drink. Available weekdays noon–2:30 PM.",
            "deal_price": 15.00, "original_price": 26.00, "discount_pct": 42,
            "distance_m": 2000, "url": "", "source": "mock",
            "rank_reasons": ["42% off", "2.0 km away"],
        },
    ],
    "Austin": [
        {
            "id": 9031, "title": "Happy Hour: $4 Drafts & $5 Margaritas",
            "merchant": "Stubb's Bar & Grill", "category": "Happy Hour",
            "description": "Happy hour every Friday 5–8 PM on the outdoor patio. $4 draft beers, $5 margaritas, $6 cocktails.",
            "deal_price": 4.00, "original_price": 9.00, "discount_pct": 56,
            "distance_m": 950, "url": "", "source": "mock",
            "rank_reasons": ["56% off", "0.95 km away", "Open now"],
        },
        {
            "id": 9032, "title": "BBQ Lunch Plate: $12 All-In",
            "merchant": "La Barbecue", "category": "Lunch Special",
            "description": "Full BBQ plate with your choice of two meats, two sides, and a slice of bread for $12. Weekdays only.",
            "deal_price": 12.00, "original_price": 20.00, "discount_pct": 40,
            "distance_m": 1800, "url": "", "source": "mock",
            "rank_reasons": ["40% off", "1.8 km away"],
        },
        {
            "id": 9033, "title": "Lunch Special: Tacos + Agua Fresca $11",
            "merchant": "Veracruz All Natural", "category": "Lunch Special",
            "description": "Three handmade tacos and a fresh agua fresca for $11. Served daily 11 AM–3 PM.",
            "deal_price": 11.00, "original_price": 18.00, "discount_pct": 39,
            "distance_m": 600, "url": "", "source": "mock",
            "rank_reasons": ["39% off", "0.6 km away"],
        },
    ],
}

# ── Modal constants ────────────────────────────────────────────────────────────

CATEGORY_HERO: dict[str, tuple[str, str]] = {
    "Happy Hour":    ("#FF6B35", "#F7931E"),
    "Lunch Special": ("#6B46C1", "#9333EA"),
}
_HERO_EMOJI = {
    "Happy Hour": "🍹", "Lunch Special": "🍱",
}

# Curated Unsplash photo IDs — restaurant/bar scenes, deterministically picked by deal_id
CATEGORY_PHOTOS: dict[str, list[str]] = {
    "Happy Hour": [
        "1514362545857-3bc16c4c7d1b",  # cocktails at bar
        "1517248135467-4c7edcad34c4",  # restaurant interior
        "1559339352-11d035aa65de",     # bar counter with drinks
        "1470337458703-4ad1d8f15ca0",  # lively bar scene
        "1551024709-8f23befc548e",     # cocktail close-up
    ],
    "Lunch Special": [
        "1414235077428-338989a2e8c0",  # vibrant food bowl
        "1565299624946-b28f40a0ae38",  # wood-fired pizza
        "1559847844-5315695dadae",     # ramen close-up
        "1568901346375-23c9450c58cd",  # gourmet burger
        "1482049016688-2d3e1b311543",  # brunch plate
        "1484980765958-7ff1b0c0c49e",  # street tacos
    ],
}
_DEFAULT_PHOTOS = CATEGORY_PHOTOS["Happy Hour"]


def _hero_img(deal_id, cat: str) -> str:
    pool = CATEGORY_PHOTOS.get(cat, _DEFAULT_PHOTOS)
    idx  = int(hashlib.md5(str(deal_id).encode()).hexdigest()[:4], 16) % len(pool)
    pid  = pool[idx]
    return (
        f"https://images.unsplash.com/photo-{pid}"
        "?w=800&h=320&fit=crop&crop=center&auto=format&q=80"
    )


# ── API helpers ───────────────────────────────────────────────────────────────

def api_get(path, params=None):
    try:
        r = httpx.get(f"{API_URL}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def api_post(path, payload=None):
    try:
        r = httpx.post(f"{API_URL}{path}", json=payload, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def api_delete(path):
    try:
        r = httpx.delete(f"{API_URL}{path}", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def post_event(event_type, deal_id=None, payload=None):
    body = {"event_type": event_type, "session_id": SESSION_ID}
    if deal_id is not None:
        body["deal_id"] = deal_id
    if payload:
        body["payload"] = payload
    try:
        httpx.post(f"{API_URL}/events", json=body, timeout=5)
    except Exception:
        pass


# ── Utils ─────────────────────────────────────────────────────────────────────

def esc(t):
    return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _mock_dist(deal_id) -> str:
    h = int(hashlib.md5(str(deal_id).encode()).hexdigest()[:4], 16)
    km = (h % 90 + 3) / 10
    return f"{km:.1f} km"


def _mock_slots(deal_id) -> list[tuple[str, bool]]:
    """Stable mock reservation slots seeded by deal_id."""
    h = int(hashlib.md5(str(deal_id).encode()).hexdigest()[:8], 16)
    rng = _rng.Random(h)
    pool = [
        "12:00 PM", "12:30 PM", "1:00 PM", "1:30 PM",
        "5:30 PM",  "6:00 PM",  "6:30 PM",  "7:00 PM",
        "7:30 PM",  "8:00 PM",  "8:30 PM",  "9:00 PM",
    ]
    chosen = sorted(rng.sample(pool, 6), key=lambda t: datetime.strptime(t, "%I:%M %p"))
    full_set = set(rng.sample(range(6), rng.randint(1, 2)))
    return [(t, i not in full_set) for i, t in enumerate(chosen)]


def hours_until(dt_str):
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return (dt - datetime.now(timezone.utc)).total_seconds() / 3600
    except Exception:
        return None

def card_html(deal, idx=0):
    title  = esc(deal.get("title", ""))
    url    = esc(deal.get("url", "#"))
    merch  = esc(deal.get("merchant") or "")
    cat    = esc(deal.get("category") or "")
    src    = esc(deal.get("source") or "")
    dp     = deal.get("deal_price")
    op     = deal.get("original_price")
    pct    = deal.get("discount_pct")

    # badges
    badges = ""
    if pct and pct >= 15:
        badges += f'<span class="bdg ba">−{pct:.0f}%</span>'
    hrs = hours_until(deal.get("expires_at"))
    if hrs is not None and 0 < hrs <= 24:
        badges += '<span class="bdg br">Ends soon</span>'
    if (deal.get("quality_score") or 0) >= 0.8:
        badges += '<span class="bdg bg">Verified</span>'
    badges_html = f'<div class="br_">{badges}</div>' if badges else ""

    # price
    price_html = ""
    if dp:
        price_html = f'<span class="pm">${dp:.2f}</span>'
        if op and abs(op - dp) > 0.01:
            price_html += f' <span class="po">${op:.2f}</span>'

    meta = " · ".join(x for x in [merch, cat] if x) or src

    # distance / rank reasons (nearby)
    dist_m = deal.get("distance_m")
    dist_html = ""
    if dist_m is not None:
        d = f"{dist_m:.0f} m" if dist_m < 1000 else f"{dist_m / 1000:.1f} km"
        dist_html = f'<span class="dchip">{d} away</span> '
    reasons = deal.get("rank_reasons") or []
    rwhy = ""
    if reasons:
        rwhy = f'<p class="rwhy">{" · ".join(esc(r) for r in reasons[:2])}</p>'

    return f"""<div class="dc" style="animation-delay:{min(idx, 5) * 45}ms">
  {badges_html}
  <p class="dc-t">{title}</p>
  <p class="dc-m">{meta}</p>
  {'<div class="dc-p">' + price_html + '</div>' if price_html else ""}
  {dist_html}{rwhy}
</div>"""


def skeleton_grid_html(n: int = 6) -> str:
    """Shimmer skeleton grid shown while deals are loading."""
    widths = [("85%","60%"), ("75%","45%"), ("90%","55%"),
              ("70%","65%"), ("80%","50%"), ("88%","40%")]
    cards = ""
    for i in range(n):
        w1, w2 = widths[i % len(widths)]
        cards += f"""
        <div class="sk-card" style="animation-delay:{i * 90}ms">
          <div class="sk-line" style="width:32%;height:10px;margin-bottom:16px"></div>
          <div class="sk-line" style="width:{w1};height:15px;margin-bottom:8px"></div>
          <div class="sk-line" style="width:{w2};height:12px;margin-bottom:0"></div>
          <div class="sk-price"></div>
          <div class="sk-btn"></div>
        </div>"""
    return f'<div class="sk-grid">{cards}</div>'


def empty_state_html(title: str, body: str) -> str:
    """Playful SVG illustration for empty / no-results states."""
    return f"""
    <div class="empty-v2">
      <div class="empty-v2__illo">
        <svg viewBox="0 0 200 180" fill="none" xmlns="http://www.w3.org/2000/svg" class="empty-svg">
          <!-- soft background ellipse -->
          <ellipse cx="100" cy="116" rx="76" ry="50" fill="rgba(107,70,193,0.07)"/>
          <!-- bag body -->
          <rect x="50" y="70" width="100" height="82" rx="18"
                fill="rgba(255,255,255,0.80)" stroke="rgba(107,70,193,0.28)" stroke-width="2.5"/>
          <!-- bag handles -->
          <path d="M70 70 C70 46 130 46 130 70"
                stroke="#6B46C1" stroke-width="2.5" stroke-linecap="round" fill="none"/>
          <!-- crossed lines inside bag — "empty" -->
          <line x1="80"  y1="98"  x2="120" y2="138" stroke="rgba(249,83,160,0.50)" stroke-width="3" stroke-linecap="round"/>
          <line x1="120" y1="98"  x2="80"  y2="138" stroke="rgba(249,83,160,0.50)" stroke-width="3" stroke-linecap="round"/>
          <!-- sparkle left -->
          <g class="sparkle-a">
            <path d="M30 42 L33 34 L36 42 L44 45 L36 48 L33 56 L30 48 L22 45 Z"
                  fill="#F953A0" opacity="0.75"/>
          </g>
          <!-- sparkle right -->
          <g class="sparkle-b">
            <path d="M160 28 L162 22 L164 28 L170 30 L164 32 L162 38 L160 32 L154 30 Z"
                  fill="#2DD4BF" opacity="0.80"/>
          </g>
          <!-- small dot accents -->
          <circle cx="44"  cy="88"  r="4.5" fill="rgba(107,70,193,0.18)"/>
          <circle cx="164" cy="96"  r="5.5" fill="rgba(249,83,160,0.16)"/>
          <circle cx="158" cy="150" r="3.5" fill="rgba(45,212,191,0.22)"/>
          <circle cx="36"  cy="144" r="3"   fill="rgba(107,70,193,0.16)"/>
          <!-- tiny star bottom-center -->
          <path d="M100 158 L101.8 163.5 L107.5 163.5 L103 166.9 L104.8 172.5 L100 169 L95.2 172.5 L97 166.9 L92.5 163.5 L98.2 163.5 Z"
                fill="rgba(107,70,193,0.20)"/>
        </svg>
      </div>
      <h3 class="empty-v2__title">{title}</h3>
      <p class="empty-v2__body">{body}</p>
    </div>"""


# ── Deal modal ────────────────────────────────────────────────────────────────

@st.dialog("Deal details", width="large")
def deal_modal(deal: dict) -> None:
    deal_id  = deal.get("id", 0)
    title    = deal.get("title") or "Untitled deal"
    _raw_merch = deal.get("merchant") or ""
    _src       = deal.get("source") or ""
    merch      = _raw_merch if _raw_merch and _raw_merch.lower() not in ("fixture", "seed") \
                 else (_src if _src and _src.lower() not in ("fixture", "seed") \
                 else (title[:40] if title else "Local vendor"))
    cat      = deal.get("category") or "Other"
    desc     = deal.get("description") or ""
    dp       = deal.get("deal_price")
    op       = deal.get("original_price")
    pct      = deal.get("discount_pct")
    url      = deal.get("url", "")
    dist_m   = deal.get("distance_m")

    hero_img  = _hero_img(deal_id, cat)
    dist_label = (
        (f"{dist_m:.0f} m away" if dist_m < 1000 else f"{dist_m/1000:.1f} km away")
        if dist_m is not None else f"{_mock_dist(deal_id)} away"
    )
    maps_url = f"https://www.google.com/maps/search/?api=1&query={quote(merch)}"

    slots    = _mock_slots(deal_id)
    slot_key = f"slot_{deal_id}"
    selected = st.session_state.get(slot_key)

    price_row = ""
    if dp:
        price_row += f'<span class="dm-price">${dp:.2f}</span>'
        if op and abs(op - dp) > 0.01:
            price_row += f'<span class="dm-orig">${op:.2f}</span>'
    if pct and pct >= 5:
        price_row += f'<span class="dm-badge">−{pct:.0f}% off</span>'

    # ── Hero + info HTML ──────────────────────────────────────────────────────
    st.html(f"""
<style>
[data-testid="stModal"]>div {{background:rgba(15,5,30,.55)!important;backdrop-filter:blur(6px)!important}}
[data-testid="stModal"] [role="dialog"] {{
  background:rgba(255,248,240,0.82)!important;
  backdrop-filter:blur(40px) saturate(180%)!important;
  border:1px solid var(--glass-border)!important;
  border-radius:var(--r-xl)!important;
  box-shadow:var(--shadow-lg)!important;
  overflow:hidden!important;
}}
button[aria-label="Close"] {{
  background:var(--glass)!important;border-radius:50%!important;
  border:1px solid var(--glass-border-dk)!important;backdrop-filter:blur(8px)!important;
}}
.dm-hero {{
  position:relative;height:210px;overflow:hidden;border-radius:var(--r-lg);margin-bottom:20px;
  background:#1A0A2E;
}}
.dm-hero-img {{
  position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center;
  display:block;filter:brightness(.72) saturate(1.15);
  transition:transform var(--dur-slow) var(--ease-out);
}}
.dm-hero:hover .dm-hero-img {{transform:scale(1.03)}}
.dm-hero-scrim {{
  position:absolute;inset:0;
  background:linear-gradient(to bottom,rgba(15,5,30,.10) 0%,rgba(15,5,30,.72) 100%);
  z-index:1;
}}
.dm-hero-body {{
  position:absolute;bottom:0;left:0;right:0;z-index:2;
  padding:12px 20px 16px;
  display:flex;align-items:flex-end;gap:12px;
}}
.dm-avatar {{
  width:56px;height:56px;border-radius:var(--r-md);flex-shrink:0;
  background:var(--glass);backdrop-filter:blur(12px);
  border:1.5px solid rgba(255,255,255,.55);
  display:flex;align-items:center;justify-content:center;
  font-size:20px;font-weight:900;color:var(--primary);
  box-shadow:var(--shadow-sm);
}}
.dm-hero-text {{color:white;flex:1;min-width:0}}
.dm-hero-name {{font-size:19px;font-weight:800;letter-spacing:-.45px;line-height:1.1;margin-bottom:3px;text-shadow:0 1px 8px rgba(0,0,0,.35);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.dm-hero-cat  {{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.9px;opacity:.78;text-shadow:0 1px 4px rgba(0,0,0,.25)}}
.dm-title     {{font-size:19px;font-weight:800;letter-spacing:-.45px;color:var(--ink);line-height:1.3;margin:0 0 10px}}
.dm-price-row {{display:flex;align-items:baseline;gap:10px;margin-bottom:16px;flex-wrap:wrap}}
.dm-price     {{font-family:'DM Mono',monospace;font-size:30px;font-weight:500;color:var(--primary);letter-spacing:-1.5px}}
.dm-orig      {{font-family:'DM Mono',monospace;font-size:13px;color:var(--muted);text-decoration:line-through}}
.dm-badge     {{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;background:rgba(249,83,160,.12);color:#C026A0;border:1px solid rgba(249,83,160,.25);border-radius:var(--r-full);padding:2px 9px}}
.dm-loc       {{display:flex;align-items:center;gap:10px;padding:12px 14px;margin-bottom:20px;background:rgba(107,70,193,.06);border:1px solid rgba(107,70,193,.14);border-radius:var(--r-md)}}
.dm-dist-lbl  {{font-size:13px;font-weight:700;color:var(--primary);flex:1}}
.dm-dist-sub  {{font-size:11px;color:var(--muted);margin-top:1px}}
.dm-maps      {{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:700;background:var(--grad-brand);color:white!important;text-decoration:none!important;padding:7px 16px;border-radius:var(--r-full);box-shadow:var(--shadow-btn);flex-shrink:0}}
.dm-lbl       {{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:var(--muted);margin:0 0 10px}}
.dm-desc      {{font-size:13px;color:var(--muted);line-height:1.65;margin:16px 0 0}}
</style>

<div class="dm-hero">
  <img class="dm-hero-img" src="{hero_img}" alt="{esc(merch)}" loading="eager">
  <div class="dm-hero-scrim"></div>
  <div class="dm-hero-body">
    <div class="dm-avatar">{esc((merch[:2] if len(merch) >= 2 else merch).upper())}</div>
    <div class="dm-hero-text">
      <div class="dm-hero-name">{esc(merch)}</div>
      <div class="dm-hero-cat">{esc(cat)}</div>
    </div>
  </div>
</div>

<div class="dm-title">{esc(title)}</div>
{'<div class="dm-price-row">' + price_row + '</div>' if price_row else ''}

<div class="dm-loc">
  <div>
    <div class="dm-dist-lbl">📍 {dist_label}</div>
    <div class="dm-dist-sub">from your current location</div>
  </div>
  <a href="{maps_url}" target="_blank" rel="noopener" class="dm-maps">Route on Maps →</a>
</div>

<div class="dm-lbl">Reserve a table</div>
""")

    # ── Reservation slots ─────────────────────────────────────────────────────
    slot_cols = st.columns(len(slots))
    for i, (time_str, avail) in enumerate(slots):
        with slot_cols[i]:
            if not avail:
                st.button(time_str, key=f"slot_{deal_id}_{i}",
                          disabled=True, use_container_width=True)
            else:
                label = f"✓ {time_str}" if selected == time_str else time_str
                if st.button(label, key=f"slot_{deal_id}_{i}",
                             use_container_width=True):
                    st.session_state[slot_key] = time_str
                    st.rerun()

    # ── Description ───────────────────────────────────────────────────────────
    if desc:
        st.html(f'<p class="dm-desc">{esc(desc[:420])}</p>')

    # ── Confirm ───────────────────────────────────────────────────────────────
    if selected:
        st.html("<div style='margin-top:16px'></div>")
        cc1, cc2 = st.columns([3, 1])
        with cc1:
            if st.button(f"Confirm · {selected} at {merch[:28]}",
                         type="primary", use_container_width=True,
                         key=f"confirm_{deal_id}"):
                st.toast(f"Reserved for {selected} — see you there!")
                st.session_state.pop(slot_key, None)
                st.rerun()
        with cc2:
            if st.button("Clear", use_container_width=True,
                         key=f"clear_{deal_id}"):
                st.session_state.pop(slot_key, None)
                st.rerun()
    elif url:
        st.html("<div style='margin-top:16px'></div>")
        st.html(f'<a href="{esc(url)}" target="_blank" rel="noopener" '
                f'style="font-size:12px;color:#7C6E8A;text-decoration:underline">'
                f'View original listing →</a>')


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="HappyBites",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Design system ─────────────────────────────────────────────────────────────

st.html("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,600;0,700;0,800;0,900;1,900&family=DM+Mono:wght@500&display=swap" rel="stylesheet">
<style>
/* ══════════════════════════════════════════════
   CANDY GLASS (AURORA) — Design System Tokens
   ══════════════════════════════════════════════ */
:root {
  /* Palette */
  --bg:              #FFF8F0;
  --glass:           rgba(255,255,255,0.65);
  --glass-dk:        rgba(255,255,255,0.45);
  --glass-border:    rgba(255,255,255,0.80);
  --glass-border-dk: rgba(180,160,220,0.28);
  --primary: #6B46C1;
  --accent:  #F953A0;
  --mint:    #2DD4BF;
  --amber:   #F59E0B;
  --gn:      #10B981;
  --rd:      #EF4444;
  --ink:     #1A0A2E;
  --muted:   #7C6E8A;

  /* Gradients */
  --grad-brand: linear-gradient(135deg,#6B46C1 0%,#9333EA 50%,#F953A0 100%);
  --grad-card:  linear-gradient(135deg,rgba(107,70,193,.12),rgba(249,83,160,.06));

  /* Shape */
  --r-sm:   8px;
  --r-md:   12px;
  --r-lg:   20px;
  --r-xl:   28px;
  --r-full: 999px;

  /* Shadow */
  --shadow-sm:         0 2px 8px rgba(107,70,193,.07), 0 1px 2px rgba(0,0,0,.03);
  --shadow-md:         0 4px 24px rgba(107,70,193,.10), 0 1px 4px rgba(0,0,0,.04);
  --shadow-lg:         0 12px 48px rgba(107,70,193,.18), 0 2px 8px rgba(0,0,0,.06);
  --shadow-btn:        0 4px 18px rgba(107,70,193,.32), 0 1px 4px rgba(0,0,0,.08);
  --shadow-btn-accent: 0 6px 28px rgba(249,83,160,.38), 0 2px 8px rgba(0,0,0,.10);

  /* Misc */
  --blur-badge: blur(8px) saturate(130%);

  /* Motion */
  --spring:   cubic-bezier(0.34,1.56,0.64,1);
  --ease-out: cubic-bezier(0.0,0,0.2,1);
  --dur-fast: .15s;
  --dur-base: .28s;
  --dur-slow: .42s;
}

/* ── Base ── */
*,*::before,*::after {
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif !important;
  box-sizing:border-box;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, header[data-testid="stHeader"], footer,
.stDeployButton, .stStatusWidget,
[data-testid="stDecoration"] { display:none !important; }
section[data-testid="stSidebar"] { display:none !important; }
.main .block-container { padding:0 0 120px !important; max-width:100% !important; }
[data-testid="stAppViewBlockContainer"] { padding:0 !important; max-width:100% !important; }

/* ══════════════════════════════════════════════
   PLAYFUL BACKGROUND — atmospheric layer
   z-index 0 throughout; content sits at z-index 1+
   ══════════════════════════════════════════════ */

/* Ensure all Streamlit content stays above the background layer */
.main .block-container,
[data-testid="stAppViewBlockContainer"],
[data-testid="stVerticalBlock"] {
  position:relative !important;
  z-index:1 !important;
}

/* Page base + very subtle noise texture (SVG feTurbulence at 3% opacity) */
.stApp {
  background-color:var(--bg) !important;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='250' height='250'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.72' numOctaves='4' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='250' height='250' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E") !important;
  background-repeat:repeat !important;
  background-size:250px 250px !important;
  overflow-x:hidden !important;
}

/* ── Blob 1 — large violet, top-right ── */
.stApp::before {
  content:''; position:fixed; pointer-events:none; z-index:0;
  width:680px; height:620px;
  top:-170px; right:-160px;
  background:radial-gradient(ellipse at 40% 40%,
    rgba(107,70,193,0.22) 0%,
    rgba(147,51,234,0.10) 45%,
    transparent 72%);
  border-radius:63% 37% 54% 46% / 55% 48% 52% 45%;
  filter:blur(55px);
  animation:blob-a 62s ease-in-out infinite alternate;
}

/* ── Blob 2 — hot pink, bottom-left ── */
.stApp::after {
  content:''; position:fixed; pointer-events:none; z-index:0;
  width:560px; height:500px;
  bottom:-90px; left:-130px;
  background:radial-gradient(ellipse at 55% 55%,
    rgba(249,83,160,0.20) 0%,
    rgba(236,72,153,0.08) 45%,
    transparent 72%);
  border-radius:37% 63% 46% 54% / 48% 55% 45% 52%;
  filter:blur(52px);
  animation:blob-b 70s ease-in-out infinite alternate;
}

/* ── Blob 3 — mint teal, mid-right ── */
body::before {
  content:''; position:fixed; pointer-events:none; z-index:0;
  width:400px; height:380px;
  top:36%; right:6%;
  background:radial-gradient(ellipse at 45% 50%,
    rgba(45,212,191,0.17) 0%,
    rgba(6,182,212,0.07) 45%,
    transparent 72%);
  border-radius:50% 50% 33% 67% / 55% 44% 56% 45%;
  filter:blur(48px);
  animation:blob-c 56s ease-in-out infinite alternate;
}

/* ── Blob 4 — warm amber, upper-left accent ── */
body::after {
  content:''; position:fixed; pointer-events:none; z-index:0;
  width:280px; height:260px;
  top:12%; left:4%;
  background:radial-gradient(ellipse at 50% 45%,
    rgba(245,158,11,0.15) 0%,
    rgba(249,115,22,0.06) 45%,
    transparent 72%);
  border-radius:70% 30% 60% 40% / 40% 65% 35% 60%;
  filter:blur(44px);
  animation:blob-d 48s ease-in-out infinite alternate;
}

/* ── Corner gradient washes ── */
/* Top-right violet wash */
.main::before {
  content:''; position:fixed; pointer-events:none; z-index:0;
  top:0; right:0;
  width:55vw; height:45vh;
  background:linear-gradient(220deg,
    rgba(107,70,193,0.09) 0%,
    rgba(147,51,234,0.04) 40%,
    transparent 70%);
}
/* Bottom-left pink wash */
.main::after {
  content:''; position:fixed; pointer-events:none; z-index:0;
  bottom:0; left:0;
  width:55vw; height:45vh;
  background:linear-gradient(40deg,
    rgba(249,83,160,0.08) 0%,
    rgba(236,72,153,0.03) 40%,
    transparent 70%);
}

/* ── Blob keyframes ── */
/* Each uses slightly different translate + scale + rotate so they never sync */
@keyframes blob-a {
  0%   { transform:translate(0,0)       scale(1)    rotate(0deg);  }
  25%  { transform:translate(-28px,42px) scale(1.05) rotate(2deg);  }
  50%  { transform:translate(18px,60px)  scale(0.97) rotate(-1deg); }
  75%  { transform:translate(-12px,20px) scale(1.07) rotate(3deg);  }
  100% { transform:translate(25px,-35px) scale(0.95) rotate(-2deg); }
}
@keyframes blob-b {
  0%   { transform:translate(0,0)       scale(1)    rotate(0deg);  }
  25%  { transform:translate(38px,-32px) scale(1.04) rotate(-3deg); }
  50%  { transform:translate(-22px,28px) scale(0.98) rotate(2deg);  }
  75%  { transform:translate(30px,16px)  scale(1.06) rotate(-1deg); }
  100% { transform:translate(-18px,-40px) scale(0.96) rotate(3deg); }
}
@keyframes blob-c {
  0%   { transform:translate(0,0)        scale(1);    }
  33%  { transform:translate(-22px,30px)  scale(1.09); }
  66%  { transform:translate(16px,-24px)  scale(0.94); }
  100% { transform:translate(-10px,14px)  scale(1.04); }
}
@keyframes blob-d {
  0%   { transform:translate(0,0)       scale(1)    rotate(0deg);  }
  40%  { transform:translate(18px,22px)  scale(1.12) rotate(5deg);  }
  100% { transform:translate(-12px,-18px) scale(0.91) rotate(-4deg); }
}

/* ── Responsive: scale blobs down on small screens ── */
@media (max-width:768px) {
  .stApp::before { width:320px; height:300px; top:-100px; right:-100px; filter:blur(45px); }
  .stApp::after  { width:280px; height:250px; bottom:-60px; left:-80px; filter:blur(42px); }
  body::before   { width:220px; height:200px; top:30%; right:3%; filter:blur(38px); }
  body::after    { width:160px; height:150px; top:8%; left:3%; filter:blur(35px); }
  .main::before, .main::after { width:80vw; height:35vh; }
}

/* ── Reduced motion: freeze blobs, keep colors ── */
@media (prefers-reduced-motion:reduce) {
  .stApp::before, .stApp::after,
  body::before, body::after {
    animation:none !important;
  }
}

/* ══════════════════════════════════════════════
   NAV — floating pill bar
   ══════════════════════════════════════════════ */
.hb-nav-wrap {
  position:sticky; top:12px; z-index:200;
  display:flex; justify-content:space-between; align-items:center;
  max-width:1120px; margin:0 auto; padding:0 40px;
  pointer-events:none;
}
.hb-nav {
  pointer-events:all;
  display:flex; align-items:center; gap:10px;
  background:rgba(255,248,240,0.78);
  backdrop-filter:blur(28px) saturate(180%);
  -webkit-backdrop-filter:blur(28px) saturate(180%);
  border:1px solid rgba(255,255,255,0.80);
  border-radius:var(--r-full);
  padding:10px 22px;
  box-shadow:0 4px 32px rgba(107,70,193,0.14), 0 1px 4px rgba(0,0,0,0.06);
  animation:nav-in 500ms var(--spring);
}
@keyframes nav-in {
  from { transform:translateY(-16px) scale(0.95); }
  to   { transform:translateY(0)     scale(1);    }
}
.hb-logo {
  font-size:17px; font-weight:900; letter-spacing:-.7px;
  color:var(--primary); line-height:1;
}
.hb-logo-dot {
  display:inline-block; width:7px; height:7px;
  background:var(--accent); border-radius:50%;
  margin-left:2px; vertical-align:middle;
  margin-bottom:2px;
  animation:dot-pulse 5s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%,100% { transform:scale(1);    opacity:1;   }
  50%      { transform:scale(1.28); opacity:0.75; }
}

/* ══════════════════════════════════════════════
   HERO
   ══════════════════════════════════════════════ */
.hb-hero {
  max-width:1120px; margin:0 auto;
  padding:52px 40px 28px;
  position:relative; z-index:1;
}
.hb-h1 {
  font-size:clamp(38px,5.5vw,72px); font-weight:900;
  line-height:1.0; letter-spacing:-3px;
  margin:0 0 10px; color:var(--primary);
}
.hb-sub {
  font-size:15px; color:var(--muted); font-weight:500;
  letter-spacing:-.2px; margin:0;
}
.hb-w { max-width:1120px; margin:0 auto; padding:0 40px; position:relative; z-index:1; }

/* ══════════════════════════════════════════════
   TABS — pill row
   ══════════════════════════════════════════════ */
.stTabs [data-baseweb="tab-list"] {
  background:transparent !important;
  border-bottom:none !important;
  padding:0 40px 20px !important;
  gap:6px !important;
  max-width:1120px !important;
  margin:0 auto !important;
}
.stTabs [data-baseweb="tab"] {
  background:var(--glass) !important;
  backdrop-filter:blur(12px) !important;
  border:1px solid var(--glass-border-dk) !important;
  border-radius:var(--r-full) !important;
  color:var(--muted) !important;
  font-size:13px !important; font-weight:600 !important;
  padding:8px 20px !important;
  margin-bottom:0 !important;
  /* Spring only on transform — ease-out for color/border prevents bouncy hue shifts */
  transition:background var(--dur-base) var(--ease-out),
             color var(--dur-fast) var(--ease-out),
             border-color var(--dur-base) var(--ease-out),
             transform var(--dur-base) var(--spring),
             box-shadow var(--dur-base) var(--ease-out) !important;
  letter-spacing:.1px !important;
}
.stTabs [data-baseweb="tab"]:hover {
  background:rgba(107,70,193,0.08) !important;
  border-color:rgba(107,70,193,0.30) !important;
  color:var(--primary) !important;
  transform:translateY(-1px) !important;
}
.stTabs [aria-selected="true"] {
  background:var(--primary) !important;
  border-color:var(--primary) !important;
  color:white !important;
  font-weight:700 !important;
  box-shadow:0 4px 18px rgba(107,70,193,0.35) !important;
  transform:translateY(-1px) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display:none !important; }
.stTabs [data-baseweb="tab-panel"]  { padding:0 !important; }

/* ══════════════════════════════════════════════
   DEAL CARDS
   ══════════════════════════════════════════════ */
.dc {
  background:var(--glass);
  backdrop-filter:blur(18px) saturate(140%);
  -webkit-backdrop-filter:blur(18px) saturate(140%);
  border:1px solid var(--glass-border);
  border-radius:var(--r-xl);
  padding:24px 24px 20px;
  box-shadow:var(--shadow-md);
  position:relative; overflow:hidden;
  animation:card-in var(--dur-base) var(--spring);
  transition:transform var(--dur-base) var(--spring),
             box-shadow var(--dur-base) var(--ease-out),
             border-color var(--dur-base) var(--ease-out);
  z-index:1; will-change:transform;
}
/* internal shimmer tint */
.dc::before {
  content:''; position:absolute; inset:0; border-radius:inherit;
  background:var(--grad-card); opacity:.45;
  pointer-events:none; z-index:0;
  transition:opacity var(--dur-base) var(--ease-out);
}
.dc > * { position:relative; z-index:1; }

/* hover: lift + very slight tilt + glow */
.dc:hover {
  transform:translateY(-6px) rotate(-0.4deg) scale(1.010);
  border-color:rgba(107,70,193,0.30);
  box-shadow:var(--shadow-lg),
             0 0 0 1px rgba(107,70,193,0.12);
}
.dc:hover::before { opacity:.65; }

/* ── Badges ── */
.br_ { margin-bottom:12px; line-height:1.6; }
.bdg {
  display:inline-block; font-size:10px; font-weight:700;
  letter-spacing:.5px; text-transform:uppercase;
  padding:3px 10px; border-radius:var(--r-full); margin-right:5px;
  backdrop-filter:var(--blur-badge);
  transition:transform var(--dur-fast) var(--spring);
}
.bdg:hover { transform:scale(1.08); }
.ba { background:rgba(249,83,160,.14); color:#C026A0; border:1px solid rgba(249,83,160,.28); }
.bg { background:rgba(16,185,129,.13);  color:#059669; border:1px solid rgba(16,185,129,.28); }
.br { background:rgba(239,68,68,.12);   color:#DC2626; border:1px solid rgba(239,68,68,.25); }

/* ── Card body ── */
.dc-t {
  font-size:15px; font-weight:700; color:var(--ink);
  letter-spacing:-.4px; line-height:1.35; margin:0 0 8px;
}
.dc-m { font-size:12px; color:var(--muted); margin:0 0 14px; font-weight:500; }
.dc-p { margin-bottom:14px; display:flex; align-items:baseline; gap:8px; }
.pm {
  font-family:'DM Mono','Fira Mono',monospace !important;
  font-size:28px; font-weight:500; line-height:1; letter-spacing:-1px;
  color:var(--primary);
}
.po {
  font-family:'DM Mono','Fira Mono',monospace !important;
  font-size:13px; color:var(--muted); text-decoration:line-through;
}
.dchip {
  display:inline-block; font-size:11px; font-weight:600;
  color:var(--primary); background:rgba(107,70,193,.10);
  border:1px solid rgba(107,70,193,.20);
  padding:2px 10px; border-radius:var(--r-full); margin-bottom:12px;
}
.rwhy {
  font-size:11px; color:var(--muted); margin:0 0 12px;
  border-top:1px solid rgba(107,70,193,.10); padding-top:10px;
}

/* ── Card CTA ── */
.dc-cta {
  display:inline-flex; align-items:center; gap:5px;
  background:var(--grad-brand);
  background-size:200% 100%; background-position:0% 50%;
  color:white !important;
  font-size:12px; font-weight:700; letter-spacing:.3px;
  padding:8px 20px; border-radius:var(--r-full);
  text-decoration:none !important;
  box-shadow:var(--shadow-btn);
  transition:background-position 380ms var(--ease-out),
             transform var(--dur-base) var(--spring),
             box-shadow var(--dur-base) var(--ease-out);
}
.dc-cta:hover {
  background-position:100% 50%;
  transform:translateY(-2px) scale(1.04);
  box-shadow:var(--shadow-btn-accent);
}
.dc-cta:active { transform:scale(0.96); transition-duration:var(--dur-fast); }

/* ══════════════════════════════════════════════
   BUTTONS
   ══════════════════════════════════════════════ */

/* ── Base (micro / feedback pills) ── */
.stButton > button {
  border-radius:var(--r-full) !important;
  font-size:11px !important; font-weight:600 !important;
  border:1px solid rgba(107,70,193,.22) !important;
  background:var(--glass) !important;
  backdrop-filter:blur(8px) !important;
  color:var(--muted) !important;
  padding:5px 14px !important;
  /* Spring only on transform; ease-out on color/border to avoid bouncy hue shifts */
  transition:background var(--dur-base) var(--ease-out),
             border-color var(--dur-base) var(--ease-out),
             color var(--dur-base) var(--ease-out),
             transform var(--dur-base) var(--spring),
             box-shadow var(--dur-base) var(--ease-out) !important;
  height:auto !important;
}
.stButton > button:hover {
  border-color:rgba(107,70,193,.50) !important;
  color:var(--primary) !important;
  background:rgba(107,70,193,.08) !important;
  transform:translateY(-2px) scale(1.05) !important;
  box-shadow:0 4px 14px rgba(107,70,193,.16) !important;
}
.stButton > button:active {
  transform:scale(0.94) !important;
  transition-duration:var(--dur-fast) !important;
  box-shadow:none !important;
}

/* ── Primary ── */
.stButton > button[kind="primary"] {
  background:var(--grad-brand) !important;
  background-size:200% 100% !important;
  background-position:0% 50% !important;
  color:white !important;
  border:none !important;
  font-size:13px !important; font-weight:700 !important;
  padding:10px 28px !important;
  box-shadow:var(--shadow-btn) !important;
  letter-spacing:.2px !important;
}
.stButton > button[kind="primary"]:hover {
  background-position:100% 50% !important;
  box-shadow:var(--shadow-btn-accent) !important;
  transform:translateY(-3px) scale(1.04) !important;
}
.stButton > button[kind="primary"]:active {
  transform:scale(0.95) !important;
  box-shadow:0 2px 8px rgba(107,70,193,.20) !important;
  transition-duration:var(--dur-fast) !important;
}

/* ── Secondary ── */
.stButton > button[kind="secondary"] {
  background:rgba(255,255,255,0.70) !important;
  backdrop-filter:blur(10px) !important;
  border:1.5px solid rgba(107,70,193,.35) !important;
  color:var(--primary) !important;
  font-size:13px !important; font-weight:700 !important;
  padding:9px 22px !important;
  box-shadow:0 2px 10px rgba(107,70,193,.10) !important;
}
.stButton > button[kind="secondary"]:hover {
  background:rgba(107,70,193,.08) !important;
  border-color:var(--primary) !important;
  box-shadow:0 4px 18px rgba(107,70,193,.20) !important;
  transform:translateY(-2px) scale(1.03) !important;
}
.stButton > button[kind="secondary"]:active {
  transform:scale(0.96) !important;
  transition-duration:var(--dur-fast) !important;
}

/* ══════════════════════════════════════════════
   INPUTS, SELECTS, NUMBER INPUTS
   ══════════════════════════════════════════════ */
[data-baseweb="input"] > div,
[data-baseweb="select"] > div {
  border-radius:var(--r-full) !important;
  border:1.5px solid rgba(107,70,193,.22) !important;
  background:rgba(255,255,255,0.72) !important;
  backdrop-filter:blur(10px) !important;
  font-size:13px !important;
  transition:border-color var(--dur-base) var(--ease-out),
             box-shadow var(--dur-base) var(--ease-out),
             background var(--dur-base) var(--ease-out) !important;
}
[data-baseweb="input"] > div:hover,
[data-baseweb="select"] > div:hover {
  border-color:rgba(107,70,193,.40) !important;
  background:rgba(255,255,255,0.85) !important;
}
[data-baseweb="input"] > div:focus-within,
[data-baseweb="select"] > div:focus-within {
  border-color:var(--primary) !important;
  background:rgba(255,255,255,0.95) !important;
  box-shadow:0 0 0 4px rgba(107,70,193,.13),
             0 2px 12px rgba(107,70,193,.10) !important;
}
/* text area and plain textarea */
textarea {
  border-radius:var(--r-md) !important;
  border:1.5px solid rgba(107,70,193,.22) !important;
  background:rgba(255,255,255,0.72) !important;
  backdrop-filter:blur(10px) !important;
}
textarea:focus {
  border-color:var(--primary) !important;
  box-shadow:0 0 0 4px rgba(107,70,193,.13) !important;
}
.stNumberInput [data-testid="stNumberInputContainer"] {
  border-radius:var(--r-full) !important;
}
/* Labels */
[data-testid="stSelectbox"] label,
[data-testid="stNumberInput"] label,
[data-testid="stTextInput"] label,
[data-testid="stTextArea"] label,
[data-testid="stSlider"] label,
[data-testid="stRadio"] label {
  font-size:11px !important; font-weight:700 !important;
  text-transform:uppercase !important; letter-spacing:.5px !important;
  color:var(--muted) !important; margin-bottom:5px !important;
}
/* Slider track */
[data-testid="stSlider"] [data-testid="stTickBar"] { display:none !important; }
[role="slider"] {
  background:var(--primary) !important;
  box-shadow:0 0 0 4px rgba(107,70,193,.20) !important;
  transition:box-shadow var(--dur-base) var(--ease-out) !important;
}
[role="slider"]:hover {
  box-shadow:0 0 0 7px rgba(107,70,193,.18) !important;
}
/* Toggle */
input[type="checkbox"] + div {
  transition:background var(--dur-base) var(--ease-out) !important;
}

/* ══════════════════════════════════════════════
   STAT BOXES
   ══════════════════════════════════════════════ */
.sb-row { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:32px; }
.sb {
  background:var(--glass);
  backdrop-filter:blur(18px); -webkit-backdrop-filter:blur(18px);
  border:1px solid var(--glass-border);
  border-radius:var(--r-lg); padding:22px 24px;
  box-shadow:var(--shadow-md);
  position:relative; overflow:hidden;
  transition:transform var(--dur-base) var(--spring),
             box-shadow var(--dur-base) var(--ease-out);
}
.sb::before {
  content:''; position:absolute; inset:0;
  background:var(--grad-card); opacity:.50; pointer-events:none;
}
.sb > * { position:relative; }
.sb:hover {
  transform:translateY(-3px);
  box-shadow:var(--shadow-lg);
}
.sb-n {
  font-size:36px; font-weight:900; letter-spacing:-2px; line-height:1; margin-bottom:4px;
  color:var(--primary);
}
.sb-l { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.5px; color:var(--muted); }

/* ══════════════════════════════════════════════
   SECTION HEADER
   ══════════════════════════════════════════════ */
.sh_ { display:flex; align-items:baseline; justify-content:space-between; margin:36px 0 18px; }
.sh-t { font-size:22px; font-weight:800; letter-spacing:-.6px; color:var(--primary); }
.sh-s { font-size:13px; color:var(--muted); font-weight:500; }

/* ══════════════════════════════════════════════
   METRICS, EXPANDERS, DATAFRAMES
   ══════════════════════════════════════════════ */
[data-testid="metric-container"] {
  background:var(--glass) !important;
  backdrop-filter:blur(18px) !important;
  border:1px solid var(--glass-border) !important;
  border-radius:var(--r-lg) !important;
  padding:18px 20px !important;
  box-shadow:var(--shadow-md) !important;
  transition:transform var(--dur-base) var(--spring),
             box-shadow var(--dur-base) var(--ease-out) !important;
}
[data-testid="metric-container"]:hover {
  transform:translateY(-2px) !important;
  box-shadow:var(--shadow-lg) !important;
}
[data-testid="metric-container"] label {
  font-size:10px !important; font-weight:700 !important;
  text-transform:uppercase !important; letter-spacing:.6px !important;
  color:var(--muted) !important;
}
[data-testid="stMetricValue"] {
  font-size:30px !important; font-weight:900 !important;
  letter-spacing:-1.5px !important; color:var(--ink) !important;
}
[data-testid="stExpander"] {
  border:1px solid var(--glass-border-dk) !important;
  border-radius:var(--r-lg) !important;
  background:var(--glass) !important;
  backdrop-filter:blur(18px) !important;
  overflow:hidden !important;
  box-shadow:var(--shadow-sm) !important;
  transition:box-shadow var(--dur-base) var(--ease-out) !important;
}
[data-testid="stExpander"]:hover { box-shadow:var(--shadow-md) !important; }
[data-testid="stExpander"] > details > summary {
  font-size:14px !important; font-weight:700 !important;
  padding:16px 22px !important; color:var(--ink) !important;
  letter-spacing:-.3px !important;
  transition:background var(--dur-fast) var(--ease-out) !important;
}
[data-testid="stExpander"] > details > summary:hover {
  background:rgba(107,70,193,.06) !important;
}
[data-testid="stExpander"] > details > div { padding:4px 22px 22px !important; }
[data-testid="stDataFrame"] {
  border-radius:var(--r-lg) !important; overflow:hidden !important;
  border:1px solid var(--glass-border-dk) !important;
}

/* ══════════════════════════════════════════════
   INGEST RESULT PANEL
   ══════════════════════════════════════════════ */
.ir {
  background:var(--glass);
  backdrop-filter:blur(18px); -webkit-backdrop-filter:blur(18px);
  border:1px solid var(--glass-border);
  border-radius:var(--r-lg); padding:26px; margin-top:16px;
  box-shadow:var(--shadow-md);
  animation:card-in var(--dur-slow) var(--spring);
  position:relative; overflow:hidden;
}
.ir::before {
  content:''; position:absolute; inset:0;
  background:var(--grad-card); opacity:.5; pointer-events:none;
}
.ir > * { position:relative; }
.ir-title { font-size:15px; font-weight:700; color:var(--ink); letter-spacing:-.3px; margin-bottom:18px; }
.ir-nums  { display:flex; gap:32px; flex-wrap:wrap; }
.ir-n {
  font-family:'DM Mono','Fira Mono',monospace !important;
  font-size:34px; font-weight:500; line-height:1; color:var(--primary);
}
.ir-l { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.4px; color:var(--muted); margin-top:3px; }

/* ══════════════════════════════════════════════
   MISC
   ══════════════════════════════════════════════ */
.src-pill {
  display:inline-block; font-size:10px; font-weight:700;
  text-transform:uppercase; letter-spacing:.4px; padding:2px 9px;
  background:rgba(107,70,193,.10); border:1px solid rgba(107,70,193,.20);
  color:var(--primary); border-radius:var(--r-full);
}
.empty { text-align:center; padding:80px 24px; }
.empty h3 { font-size:22px; font-weight:800; letter-spacing:-.5px; margin-bottom:8px; color:var(--primary); }
.empty p  { font-size:14px; color:var(--muted); margin:0; }
hr { border-color:var(--glass-border-dk) !important; margin:32px 0 !important; }
.stAlert { border-radius:var(--r-md) !important; font-size:13px !important; }
.stCaptionContainer p { font-size:12px !important; color:var(--muted) !important; }
.stToggle label p { font-size:13px !important; font-weight:600 !important; }
.stSpinner > div { color:var(--primary) !important; }
/* Feedback button row — separate visually from the card above */
[data-testid="column"] > [data-testid="stHorizontalBlock"] {
  margin-top:6px !important;
}
/* Report buttons — scaled down visually (bypass browser min-font-size) */
[data-testid="column"]:nth-child(3) .stButton,
[data-testid="column"]:nth-child(4) .stButton {
  transform:scale(0.55) !important;
  transform-origin:left center !important;
}
[data-testid="column"]:nth-child(3) .stButton > button,
[data-testid="column"]:nth-child(4) .stButton > button {
  width:auto !important;
  padding:3px 10px !important;
  color:rgba(124,110,138,0.65) !important;
  border-color:rgba(107,70,193,.12) !important;
  background:transparent !important;
  backdrop-filter:none !important;
  letter-spacing:0 !important;
}
[data-testid="column"]:nth-child(3) .stButton > button,
[data-testid="column"]:nth-child(3) .stButton > button *,
[data-testid="column"]:nth-child(4) .stButton > button,
[data-testid="column"]:nth-child(4) .stButton > button * {
  white-space:nowrap !important;
  word-break:keep-all !important;
}
[data-testid="column"]:nth-child(3) .stButton > button:hover,
[data-testid="column"]:nth-child(4) .stButton > button:hover {
  color:var(--muted) !important;
  border-color:rgba(107,70,193,.25) !important;
  background:rgba(107,70,193,.05) !important;
  transform:none !important;
  box-shadow:none !important;
}

/* ══════════════════════════════════════════════
   MICRO-INTERACTIONS (shared keyframes)
   ══════════════════════════════════════════════ */

/* Card entrance — transform only, no opacity hide (prevents invisible cards in iframes) */
@keyframes card-in {
  from { transform:translateY(20px) scale(0.96); }
  to   { transform:translateY(0)    scale(1);    }
}
/* Toast / success pop */
@keyframes pop-in {
  0%   { transform:scale(0.8);  opacity:0; }
  65%  { transform:scale(1.06); opacity:1; }
  100% { transform:scale(1);    opacity:1; }
}
/* Subtle attention shake (for errors) */
@keyframes shake {
  0%,100% { transform:translateX(0); }
  20%      { transform:translateX(-6px); }
  40%      { transform:translateX(6px);  }
  60%      { transform:translateX(-4px); }
  80%      { transform:translateX(4px);  }
}
.stAlert { animation:pop-in 300ms var(--spring) both !important; }
.stAlert[data-baseweb="notification"][kind="error"],
.stAlert[data-baseweb="notification"][kind="warning"] {
  animation:shake 400ms var(--ease-out) both !important;
}

/* ══════════════════════════════════════════════
   PLAYFUL LAYOUT — personality layer
   ══════════════════════════════════════════════ */

/* ── Hero wrapper ── */
.pb-hero {
  max-width:1120px; margin:0 auto;
  padding:56px 40px 44px;
  position:relative; z-index:1; overflow:hidden;
}
.pb-hero__body { position:relative; z-index:2; max-width:580px; }

/* Pill kicker label above headline */
.pb-kicker {
  display:inline-flex; align-items:center; gap:6px;
  font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1.2px;
  color:var(--accent);
  background:rgba(249,83,160,0.10);
  border:1px solid rgba(249,83,160,0.28);
  padding:5px 14px; border-radius:var(--r-full);
  margin-bottom:20px;
}
.pb-kicker--mint  { color:#0D9488; background:rgba(45,212,191,0.10); border-color:rgba(45,212,191,0.30); }
.pb-kicker--amber { color:#B45309; background:rgba(245,158,11,0.10); border-color:rgba(245,158,11,0.30); }

/* Section header color modifiers */
.pb-sh__kicker--mint  { color:#0D9488; }
.pb-sh__kicker--amber { color:#D97706; }
.pb-sh__title--mint   { color:#0D9488; }
.pb-sh__title--amber  { color:#92400E; }

/* Big display headline */
.pb-h1 {
  font-size:clamp(42px,6vw,82px); font-weight:900;
  line-height:1.0; letter-spacing:-4px;
  color:var(--primary); margin:0 0 18px;
}
/* Second line — intentionally indented for asymmetry */
.pb-h1-line2 {
  display:block;
  margin-left:clamp(20px,3.5vw,64px);
  color:var(--ink);
}
.pb-h1-line2--mint  { color:#0D9488; }
.pb-h1-line2--amber { color:#92400E; }

.pb-sub {
  font-size:16px; color:var(--muted); font-weight:500;
  letter-spacing:-.2px; margin:0; max-width:400px; line-height:1.55;
}

/* Floating badge — top-right, slightly rotated */
.pb-hero__badge {
  position:absolute; top:52px; right:44px; z-index:3;
  background:var(--glass);
  backdrop-filter:blur(16px) saturate(140%);
  border:1px solid var(--glass-border);
  border-radius:var(--r-xl); padding:20px 28px; text-align:center;
  box-shadow:var(--shadow-md);
  transform:rotate(3.5deg);
  animation:badge-float 4.5s ease-in-out infinite alternate;
}
@keyframes badge-float {
  from { transform:rotate(3.5deg) translateY(0px);  }
  to   { transform:rotate(3.5deg) translateY(-10px); }
}
.pb-badge-num {
  display:block;
  font-family:'DM Mono',monospace; font-size:44px; font-weight:500;
  line-height:1; color:var(--primary); letter-spacing:-2px;
}
.pb-badge-label {
  display:block; font-size:10px; font-weight:700;
  text-transform:uppercase; letter-spacing:.8px;
  color:var(--muted); margin-top:5px;
}

/* Decorative shape blobs inside hero (purely visual) */
.pb-hero-shape {
  position:absolute; border-radius:50%; pointer-events:none; z-index:1;
}
.pb-hs1 {
  width:300px; height:300px; bottom:-100px; right:140px;
  background:radial-gradient(circle, rgba(107,70,193,0.13) 0%, transparent 70%);
  filter:blur(32px);
}
.pb-hs2 {
  width:180px; height:180px; top:16px; left:52%;
  background:radial-gradient(circle, rgba(249,83,160,0.15) 0%, transparent 70%);
  filter:blur(24px);
}
.pb-hs3 {
  width:140px; height:140px; bottom:0; left:36%;
  background:radial-gradient(circle, rgba(45,212,191,0.14) 0%, transparent 70%);
  filter:blur(20px);
}

/* ── Feature highlight strip ── */
.pb-strip {
  max-width:1120px; margin:0 auto 4px;
  padding:0 40px; position:relative; z-index:1;
}
.pb-strip__inner {
  background:var(--glass);
  backdrop-filter:blur(14px);
  border:1px solid var(--glass-border);
  border-radius:var(--r-lg);
  padding:13px 22px;
  display:flex; align-items:center; gap:14px;
  box-shadow:var(--shadow-sm);
  position:relative; overflow:hidden;
}
/* left accent bar */
.pb-strip__inner::before {
  content:''; position:absolute; left:0; top:0; bottom:0;
  width:4px; background:var(--grad-brand); border-radius:4px 0 0 4px;
}
.pb-strip__icon { font-size:17px; line-height:1; flex-shrink:0; }
.pb-strip__text {
  font-size:13px; font-weight:600; color:var(--ink); letter-spacing:-.2px;
}
.pb-strip__text em { font-style:normal; color:var(--primary); font-weight:700; }
.pb-strip__pill {
  margin-left:auto; flex-shrink:0;
  font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.5px;
  color:var(--accent); background:rgba(249,83,160,0.10);
  border:1px solid rgba(249,83,160,0.24); padding:3px 10px;
  border-radius:var(--r-full);
}

/* ── Playful section header ── */
.pb-sh {
  position:relative; overflow:hidden;
  display:flex; align-items:flex-end; justify-content:space-between;
  margin:40px 0 20px; padding-bottom:14px;
  border-bottom:1px solid var(--glass-border-dk);
}
/* huge ghosted background word */
.pb-sh__bg {
  position:absolute; left:-4px; bottom:-8px; z-index:0;
  font-size:96px; font-weight:900; line-height:1;
  letter-spacing:-7px; text-transform:uppercase;
  color:rgba(107,70,193,0.055);
  pointer-events:none; user-select:none; white-space:nowrap;
}
.pb-sh__fg { position:relative; z-index:1; }
.pb-sh__kicker {
  display:block; font-size:10px; font-weight:700;
  text-transform:uppercase; letter-spacing:.9px;
  color:var(--accent); margin-bottom:4px;
}
.pb-sh__title {
  font-size:28px; font-weight:900; letter-spacing:-.9px;
  color:var(--primary); margin:0; line-height:1;
}
.pb-sh__count {
  position:relative; z-index:1;
  font-family:'DM Mono',monospace; font-size:13px; font-weight:500;
  color:var(--muted); letter-spacing:-.2px; padding-bottom:2px;
}

/* ── Admin stat row — add hover accent color ── */
.sb--green .sb-n { color:var(--gn); }
.sb--amber .sb-n { color:#D97706; }

/* ══════════════════════════════════════════════
   TABLET (900px) — stat row 4→2 columns
   ══════════════════════════════════════════════ */
@media (max-width:900px) {
  .sb-row { grid-template-columns:repeat(2,1fr); }
}

/* ══════════════════════════════════════════════
   MOBILE
   ══════════════════════════════════════════════ */
@media (max-width:700px) {
  .hb-nav-wrap   { padding:0 16px; top:10px; }
  .hb-w          { padding:0 20px; }
  .ir-nums       { gap:18px; }
  .stTabs [data-baseweb="tab-list"] { padding:0 20px 16px !important; }
  /* Hero */
  .pb-hero         { padding:36px 20px 32px; }
  .pb-h1           { letter-spacing:-2.5px; }
  .pb-hero__badge  { display:none; }
  .pb-hs1,.pb-hs2,.pb-hs3 { display:none; }
  /* Strip */
  .pb-strip        { padding:0 20px; }
  .pb-strip__pill  { display:none; }
  /* Section header */
  .pb-sh__bg    { font-size:60px; letter-spacing:-4px; }
  .pb-sh__title { font-size:22px; }
}

/* ══════════════════════════════════════════════
   PAGE / TAB TRANSITIONS
   Streamlit re-renders on every tab click, so
   CSS animations DO replay on each switch.
   ══════════════════════════════════════════════ */
.stTabs [data-baseweb="tab-panel"] > div {
  animation: page-in 340ms cubic-bezier(0.0,0.0,0.2,1) both;
}
@keyframes page-in {
  from { opacity:0; transform:translateY(12px); }
  to   { opacity:1; transform:translateY(0);    }
}

/* Hero body elements stagger in */
.pb-hero__body { animation: hero-item 480ms cubic-bezier(0.0,0.0,0.2,1) both; }
.pb-kicker  { animation: hero-item 440ms  40ms cubic-bezier(0.0,0.0,0.2,1) both; }
.pb-h1      { animation: hero-item 480ms  90ms cubic-bezier(0.0,0.0,0.2,1) both; }
.pb-sub     { animation: hero-item 480ms 150ms cubic-bezier(0.0,0.0,0.2,1) both; }
@keyframes hero-item {
  from { transform:translateY(18px); }
  to   { transform:translateY(0);    }
}
/* Override badge to keep its float animation, add entrance delay */
.pb-hero__badge {
  animation: hero-item 560ms 220ms cubic-bezier(0.34,1.56,0.64,1) both,
             badge-float 4.5s 800ms ease-in-out infinite alternate !important;
}

/* ══════════════════════════════════════════════
   SKELETON LOADING
   ══════════════════════════════════════════════ */
.sk-grid {
  display:grid; grid-template-columns:1fr 1fr; gap:16px;
  max-width:1120px; margin:0 auto; padding:0 40px;
}
.sk-card {
  background:linear-gradient(
    90deg,
    rgba(255,255,255,0.55)  0%,
    rgba(107,70,193,0.09)  40%,
    rgba(249,83,160,0.06)  50%,
    rgba(107,70,193,0.09)  60%,
    rgba(255,255,255,0.55) 100%
  );
  background-size:300% 100%;
  border:1px solid var(--glass-border);
  border-radius:var(--r-xl);
  padding:24px; min-height:190px;
  box-shadow:var(--shadow-sm);
  animation:shimmer 1.8s ease-in-out infinite;
}
.sk-line {
  border-radius:8px; background:rgba(107,70,193,0.09); margin-bottom:10px;
}
.sk-price {
  border-radius:10px; background:rgba(107,70,193,0.11);
  width:30%; height:32px; margin:16px 0;
}
.sk-btn {
  border-radius:100px; background:rgba(107,70,193,0.08);
  width:108px; height:30px;
}
@keyframes shimmer {
  0%   { background-position: 150% 0; }
  100% { background-position:-150% 0; }
}
/* Stagger skeleton cards */
.sk-card:nth-child(2) { animation-delay:.12s; }
.sk-card:nth-child(3) { animation-delay:.06s; }
.sk-card:nth-child(4) { animation-delay:.20s; }
.sk-card:nth-child(5) { animation-delay:.04s; }
.sk-card:nth-child(6) { animation-delay:.16s; }

/* ══════════════════════════════════════════════
   EMPTY STATE v2 — SVG illustration
   ══════════════════════════════════════════════ */
.empty-v2 { text-align:center; padding:64px 24px 48px; }
.empty-v2__illo {
  display:inline-block; margin-bottom:24px;
  animation:empty-float 4.2s ease-in-out infinite alternate;
}
.empty-svg { width:160px; height:144px; }
@keyframes empty-float {
  from { transform:translateY(0);    }
  to   { transform:translateY(-12px); }
}
.sparkle-a {
  transform-origin:33px 45px;
  animation:sparkle-spin 3.2s ease-in-out infinite alternate;
}
.sparkle-b {
  transform-origin:162px 30px;
  animation:sparkle-spin 4.1s ease-in-out infinite alternate-reverse;
}
@keyframes sparkle-spin {
  from { transform:rotate(-18deg) scale(0.80); opacity:0.45; }
  to   { transform:rotate(18deg)  scale(1.20); opacity:1.00; }
}
.empty-v2__title {
  font-size:24px; font-weight:900; letter-spacing:-.6px;
  color:var(--primary); margin:0 0 10px;
}
.empty-v2__body {
  font-size:14px; color:var(--muted); margin:0;
  max-width:300px; display:inline-block; line-height:1.65;
}

/* ══════════════════════════════════════════════
   REDUCED MOTION — freeze all UI transitions
   ══════════════════════════════════════════════ */
@media (prefers-reduced-motion:reduce) {
  .dc, .sb, .ir, .dc-cta,
  .stButton > button,
  [data-testid="metric-container"],
  [data-testid="stExpander"],
  .bdg, .hb-logo-dot,
  .pb-kicker, .pb-h1, .pb-sub, .pb-hero__body, .pb-hero__badge,
  .empty-v2__illo, .sparkle-a, .sparkle-b,
  .sk-card,
  .stTabs [data-baseweb="tab-panel"] > div {
    transition:none !important;
    animation:none !important;
  }
  .dc, .ir, .pb-kicker, .pb-h1, .pb-sub, .pb-hero__badge { opacity:1; transform:none; }
  .sk-card { background:rgba(107,70,193,0.06); }
}
</style>
""")


# ── Nav ───────────────────────────────────────────────────────────────────────

st.html("""
<div class="hb-nav-wrap">
  <div class="hb-nav">
    <span class="hb-logo">happybites</span>
    <span class="hb-logo-dot"></span>
  </div>
</div>
""")

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_discover, tab_nearby, tab_profile = st.tabs(["Discover", "Nearby", "Profile"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 · DISCOVER
# ══════════════════════════════════════════════════════════════════════════════

with tab_discover:
    st.html("""
    <div class="pb-hero">
      <div class="pb-hero__body">
        <p class="pb-kicker">✦ ai-ranked deals</p>
        <h1 class="pb-h1">Find your next
          <span class="pb-h1-line2">great deal.</span>
        </h1>
        <p class="pb-sub">Fresh offers, curated and ranked every hour.</p>
      </div>
      <div class="pb-hero__badge">
        <span class="pb-badge-num">18+</span>
        <span class="pb-badge-label">live deals</span>
      </div>
      <div class="pb-hero-shape pb-hs1"></div>
      <div class="pb-hero-shape pb-hs2"></div>
      <div class="pb-hero-shape pb-hs3"></div>
    </div>
    """)

    with st.container():
        

        # ── Filters ───────────────────────────────────────────────────────────
        fc1, fc2, fc3, fc4 = st.columns([2, 2, 1.5, 1.5])
        with fc1:
            deal_type = st.selectbox(
                "Deal type",
                ["All types"] + DEAL_TYPES,
                label_visibility="collapsed",
            )
        with fc2:
            sort_by = st.selectbox(
                "Sort",
                ["rank_score", "discount_pct", "fetched_at"],
                format_func=lambda x: {
                    "rank_score": "Best match",
                    "discount_pct": "Biggest discount",
                    "fetched_at": "Newest first",
                }[x],
                label_visibility="collapsed",
            )
        with fc3:
            max_price = st.number_input(
                "Max price", min_value=0.0, value=0.0, step=10.0,
                placeholder="Max price ($)",
                label_visibility="collapsed",
            )
        with fc4:
            min_disc = st.number_input(
                "Min discount", min_value=0, max_value=90, value=0, step=5,
                placeholder="Min discount %",
                label_visibility="collapsed",
            )

        # ── Fetch — show skeleton while API call runs ─────────────────────────
        params: dict = {"sort": sort_by, "limit": 50, "offset": 0}
        if deal_type != "All types":
            params["category"] = deal_type
        if max_price > 0:
            params["max_price"] = max_price
        if min_disc > 0:
            params["min_discount"] = min_disc

        _slot = st.empty()
        _slot.html(skeleton_grid_html(6))

        data  = api_get("/deals", params=params)
        items = (data or {}).get("items", [])
        total = (data or {}).get("total", 0)

        _slot.empty()

        # ── Feature strip + section header ────────────────────────────────────
        sort_label = {"rank_score": "AI score", "discount_pct": "discount", "fetched_at": "recency"}[sort_by]
        st.html(f"""
        <div class="pb-strip">
          <div class="pb-strip__inner">
            <span class="pb-strip__icon">✦</span>
            <span class="pb-strip__text">
              Showing <em>{total} deals</em> — sorted by {sort_label}
            </span>
            <span class="pb-strip__pill">Updated hourly</span>
          </div>
        </div>
        <div class="hb-w">
          <div class="pb-sh">
            <span class="pb-sh__bg">PICKS</span>
            <div class="pb-sh__fg">
              <span class="pb-sh__kicker">right now</span>
              <h2 class="pb-sh__title">Today's picks</h2>
            </div>
            <span class="pb-sh__count">{total} results</span>
          </div>
        </div>
        """)

        if not items:
            st.html(empty_state_html(
                "Nothing here yet",
                "Run an ingest from the Admin tab — deals will appear right here.",
            ))
        else:
            col_a, col_b = st.columns(2, gap="medium")
            for i, deal in enumerate(items):
                col = col_a if i % 2 == 0 else col_b
                with col:
                    st.html(card_html(deal, i))
                    # Feedback row — View deal primary; Save secondary; Wrong/Expired receded
                    fb0, fb1, fb2, fb3 = st.columns([2.5, 1.5, 1, 1.2])
                    with fb0:
                        if st.button("View deal", key=f"vd_{deal['id']}_{i}",
                                     type="primary", use_container_width=True):
                            deal_modal(deal)
                    with fb1:
                        if st.button("Save", key=f"sv_{deal['id']}_{i}", use_container_width=True):
                            post_event("save", deal["id"])
                            st.toast("Saved")
                    with fb2:
                        if st.button("Wrong?", key=f"wr_{deal['id']}_{i}"):
                            post_event("report_incorrect", deal["id"])
                            st.toast("Reported")
                    with fb3:
                        if st.button("Expired?", key=f"ex_{deal['id']}_{i}"):
                            post_event("report_expired", deal["id"])
                            st.toast("Reported")

        


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 · NEARBY
# ══════════════════════════════════════════════════════════════════════════════

with tab_nearby:
    st.html("""
    <div class="pb-hero">
      <div class="pb-hero__body">
        <p class="pb-kicker pb-kicker--mint">◎ location-aware</p>
        <h1 class="pb-h1">Great deals,
          <span class="pb-h1-line2 pb-h1-line2--mint">near you.</span>
        </h1>
        <p class="pb-sub">Ranked by value, freshness, and how close they are.</p>
      </div>
      <div class="pb-hero-shape pb-hs1" style="background:radial-gradient(circle,rgba(45,212,191,0.15) 0%,transparent 70%)"></div>
      <div class="pb-hero-shape pb-hs2" style="background:radial-gradient(circle,rgba(107,70,193,0.12) 0%,transparent 70%)"></div>
    </div>
    """)

    with st.container():
        

        # ── City presets ──────────────────────────────────────────────────────
        preset = st.radio(
            "City",
            ["San Francisco", "New York", "Los Angeles", "Austin", "Custom"],
            horizontal=True,
            label_visibility="collapsed",
        )

        if preset == "Custom":
            lc1, lc2 = st.columns(2)
            with lc1:
                nb_lat = st.number_input("Latitude", value=37.7749, format="%.4f")
            with lc2:
                nb_lng = st.number_input("Longitude", value=-122.4194, format="%.4f")
        else:
            nb_lat, nb_lng = CITY_PRESETS[preset]

        # ── Search controls ───────────────────────────────────────────────────
        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1:
            nb_radius = st.select_slider(
                "Radius (km)", options=[1, 2, 5, 10, 20, 50], value=10,
            )
        with sc2:
            nb_open = st.selectbox(
                "Availability",
                ["Any", "Open now", "Closed"],
                label_visibility="visible",
            )
        with sc3:
            nb_deal_type = st.selectbox(
                "Deal type",
                ["Any"] + DEAL_TYPES,
                label_visibility="visible",
            )
        with sc4:
            nb_debug = st.checkbox("Score breakdown", value=False)

        nb_search = st.button("Search deals", type="primary", use_container_width=False)

        if nb_search or "nb_results" in st.session_state:
            if nb_search:
                params: dict = {
                    "lat": nb_lat, "lng": nb_lng,
                    "radius_m": nb_radius * 1000,
                    "limit": 30, "offset": 0,
                }
                if nb_open == "Open now":
                    params["open_now"] = "true"
                elif nb_open == "Closed":
                    params["open_now"] = "false"
                if nb_deal_type != "Any":
                    params["category"] = nb_deal_type
                if nb_debug:
                    params["debug"] = "true"

                _nb_slot = st.empty()
                _nb_slot.html(skeleton_grid_html(4))
                nb_data = api_get("/deals/nearby", params=params)
                _nb_slot.empty()
                # Fall back to mock data when the API returns nothing
                if not nb_data or not nb_data.get("items"):
                    _mock_items = _MOCK_NEARBY.get(
                        preset if preset != "Custom" else "", []
                    )
                    nb_data = {"items": _mock_items, "total": len(_mock_items)}
                if nb_data is not None:
                    st.session_state["nb_results"] = nb_data
                    st.session_state["nb_debug"] = nb_debug

            nb_data = st.session_state.get("nb_results")
            show_debug = st.session_state.get("nb_debug", False)

            if nb_data:
                nb_items = nb_data.get("items", [])
                nb_total = nb_data.get("total", 0)
                st.html(f"""
                <div class="hb-w">
                  <div class="pb-sh">
                    <span class="pb-sh__bg">NEARBY</span>
                    <div class="pb-sh__fg">
                      <span class="pb-sh__kicker pb-sh__kicker--mint">within range</span>
                      <h2 class="pb-sh__title pb-sh__title--mint">Within {nb_radius} km</h2>
                    </div>
                    <span class="pb-sh__count">{nb_total} deals</span>
                  </div>
                </div>
                """)

                if not nb_items:
                    st.html(empty_state_html(
                        "No deals in this area",
                        "Try a larger radius or a different city.",
                    ))
                else:
                    nc_a, nc_b = st.columns(2, gap="medium")
                    for i, deal in enumerate(nb_items):
                        col = nc_a if i % 2 == 0 else nc_b
                        with col:
                            st.html(card_html(deal, i))
                            if st.button("View deal", key=f"nbvd_{deal['id']}_{i}",
                                         type="primary", use_container_width=True):
                                deal_modal(deal)
                            if show_debug and deal.get("rank_debug"):
                                with st.expander("Score breakdown"):
                                    rows = [
                                        {"Feature": k, "Score": f"{v:.4f}"}
                                        for k, v in sorted(
                                            deal["rank_debug"].items(),
                                            key=lambda x: -x[1],
                                        )
                                    ]
                                    st.dataframe(rows, hide_index=True, use_container_width=True)

        


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 · ADMIN
# ══════════════════════════════════════════════════════════════════════════════

with tab_profile:
    st.html("""
    <div class="pb-hero">
      <div class="pb-hero__body">
        <p class="pb-kicker pb-kicker--amber">◈ your account</p>
        <h1 class="pb-h1">Your
          <span class="pb-h1-line2 pb-h1-line2--amber">profile.</span>
        </h1>
        <p class="pb-sub">Manage your details, preferences, and reservation history.</p>
      </div>
      <div class="pb-hero-shape pb-hs1" style="background:radial-gradient(circle,rgba(245,158,11,0.13) 0%,transparent 70%)"></div>
      <div class="pb-hero-shape pb-hs2" style="background:radial-gradient(circle,rgba(107,70,193,0.10) 0%,transparent 70%)"></div>
    </div>
    """)

    # ── Mock reservation data ─────────────────────────────────────────────────
    _UPCOMING_RESERVATIONS = [
        {"id": "r001", "venue": "Zuni Café", "deal": "Happy Hour: $6 Cocktails & Half-Off Bites",
         "date": "Sat, Mar 14 2026", "time": "6:00 PM", "guests": 2, "city": "San Francisco"},
        {"id": "r002", "venue": "Balthazar", "deal": "Early Bird Dinner: 3-Course for $45",
         "date": "Sun, Mar 15 2026", "time": "6:00 PM", "guests": 4, "city": "New York"},
    ]
    _PAST_RESERVATIONS = [
        {"id": "r101", "venue": "La Barbecue", "deal": "BBQ Lunch Plate: $12 All-In",
         "date": "Tue, Feb 18 2026", "time": "12:30 PM", "guests": 2, "city": "Austin"},
        {"id": "r102", "venue": "Dragon Beaux", "deal": "Lunch Special: Dim Sum for Two",
         "date": "Sat, Feb 8 2026", "time": "1:00 PM", "guests": 2, "city": "San Francisco"},
        {"id": "r103", "venue": "Guerrilla Tacos", "deal": "Taco Tuesday: $2 Street Tacos",
         "date": "Tue, Jan 27 2026", "time": "12:00 PM", "guests": 3, "city": "Los Angeles"},
    ]

    with st.container():

        # ── Profile card ──────────────────────────────────────────────────────
        st.html("""
        <div class="hb-w">
          <div class="pb-sh">
            <span class="pb-sh__bg">PROFILE</span>
            <div class="pb-sh__fg">
              <span class="pb-sh__kicker pb-sh__kicker--amber">account</span>
              <h2 class="pb-sh__title pb-sh__title--amber">Your info</h2>
            </div>
          </div>
        </div>
        """)

        pf_col, form_col = st.columns([1, 2], gap="large")

        with pf_col:
            st.html("""<style>
            .pf-avatar-wrap {
              display:flex;flex-direction:column;align-items:center;gap:14px;
              padding:28px 20px;
              background:var(--glass);backdrop-filter:blur(18px) saturate(140%);
              border:1px solid var(--glass-border);border-radius:var(--r-xl);
              box-shadow:var(--shadow-md);
            }
            .pf-avatar {
              width:96px;height:96px;border-radius:50%;
              background:var(--grad-brand);
              display:flex;align-items:center;justify-content:center;
              font-size:36px;font-weight:900;color:white;
              box-shadow:var(--shadow-btn);
              border:3px solid rgba(255,255,255,.70);
            }
            .pf-name  {font-size:16px;font-weight:800;color:var(--ink);letter-spacing:-.3px}
            .pf-email {font-size:12px;color:var(--muted);margin-top:2px}
            .pf-badge {
              font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
              background:rgba(107,70,193,.10);color:var(--primary);
              border:1px solid rgba(107,70,193,.22);border-radius:var(--r-full);
              padding:3px 11px;
            }
            </style>
            <div class="pf-avatar-wrap">
              <div class="pf-avatar">AJ</div>
              <div style="text-align:center">
                <div class="pf-name">Alex Johnson</div>
                <div class="pf-email">alex@example.com</div>
              </div>
              <span class="pf-badge">Member since 2025</span>
            </div>""")
            st.html("<div style='height:12px'></div>")
            uploaded = st.file_uploader(
                "Change photo", type=["png", "jpg", "jpeg", "webp"],
                label_visibility="visible",
            )
            if uploaded:
                st.toast("Photo updated (demo — not saved)")

        with form_col:
            with st.form("profile_form"):
                st.html("""<style>
                .pf-form-card {
                  background:var(--glass);backdrop-filter:blur(18px) saturate(140%);
                  border:1px solid var(--glass-border);border-radius:var(--r-xl);
                  box-shadow:var(--shadow-md);padding:24px 24px 8px;
                }
                </style>
                <div class="pf-form-card">""")

                fc1, fc2 = st.columns(2)
                with fc1:
                    st.text_input("First name", value="Alex")
                with fc2:
                    st.text_input("Last name", value="Johnson")

                st.text_input("Email", value="alex@example.com")
                st.text_input("Location", value="San Francisco, CA",
                              placeholder="City, State")
                st.selectbox("Preferred city",
                             ["San Francisco", "New York", "Los Angeles", "Austin"],
                             index=0)

                pref_c1, pref_c2 = st.columns(2)
                with pref_c1:
                    st.multiselect(
                        "Preferred deal types",
                        DEAL_TYPES,
                        default=DEAL_TYPES,
                    )
                with pref_c2:
                    st.number_input("Max price ($)", min_value=0, value=100, step=5)

                st.html("</div>")
                save_btn = st.form_submit_button(
                    "Save changes", type="primary", use_container_width=False,
                )
                if save_btn:
                    st.toast("Profile saved (demo — not persisted)")

        # ── Upcoming reservations ─────────────────────────────────────────────
        st.html("""
        <div class="hb-w" style="margin-top:32px">
          <div class="pb-sh">
            <span class="pb-sh__bg">UPCOMING</span>
            <div class="pb-sh__fg">
              <span class="pb-sh__kicker pb-sh__kicker--mint">reservations</span>
              <h2 class="pb-sh__title pb-sh__title--mint">Coming up</h2>
            </div>
          </div>
        </div>
        """)

        st.html("""<style>
        .res-card {
          display:flex;align-items:center;gap:16px;
          padding:16px 20px;margin-bottom:12px;
          background:var(--glass);backdrop-filter:blur(18px) saturate(140%);
          border:1px solid var(--glass-border);border-radius:var(--r-lg);
          box-shadow:var(--shadow-sm);
        }
        .res-dot {
          width:44px;height:44px;border-radius:var(--r-md);flex-shrink:0;
          background:var(--grad-brand);
          display:flex;align-items:center;justify-content:center;
          font-size:20px;
        }
        .res-dot--past { background:rgba(124,110,138,.14); }
        .res-venue  {font-size:14px;font-weight:800;color:var(--ink);letter-spacing:-.2px}
        .res-deal   {font-size:12px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:340px}
        .res-meta   {font-size:11px;font-weight:600;color:var(--primary);margin-top:6px;letter-spacing:.2px}
        .res-meta--past {color:var(--muted)}
        .res-guests {
          margin-left:auto;font-size:11px;font-weight:700;color:var(--muted);
          background:rgba(107,70,193,.08);border:1px solid rgba(107,70,193,.14);
          border-radius:var(--r-full);padding:3px 10px;flex-shrink:0;white-space:nowrap;
        }
        </style>""")

        for r in _UPCOMING_RESERVATIONS:
            st.html(f"""
            <div class="res-card">
              <div class="res-dot">📅</div>
              <div style="flex:1;min-width:0">
                <div class="res-venue">{esc(r['venue'])}</div>
                <div class="res-deal">{esc(r['deal'])}</div>
                <div class="res-meta">{esc(r['date'])} · {esc(r['time'])} · {esc(r['city'])}</div>
              </div>
              <div class="res-guests">{r['guests']} guests</div>
            </div>""")

        # ── Past reservations ─────────────────────────────────────────────────
        st.html("""
        <div class="hb-w" style="margin-top:32px">
          <div class="pb-sh">
            <span class="pb-sh__bg">HISTORY</span>
            <div class="pb-sh__fg">
              <span class="pb-sh__kicker pb-sh__kicker--amber">past visits</span>
              <h2 class="pb-sh__title pb-sh__title--amber">History</h2>
            </div>
          </div>
        </div>
        """)

        for r in _PAST_RESERVATIONS:
            st.html(f"""
            <div class="res-card">
              <div class="res-dot res-dot--past">✓</div>
              <div style="flex:1;min-width:0">
                <div class="res-venue">{esc(r['venue'])}</div>
                <div class="res-deal">{esc(r['deal'])}</div>
                <div class="res-meta res-meta--past">{esc(r['date'])} · {esc(r['time'])} · {esc(r['city'])}</div>
              </div>
              <div class="res-guests">{r['guests']} guests</div>
            </div>""")

