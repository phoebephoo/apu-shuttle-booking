"""
APU Shuttle Booking prototype (Streamlit).
Run with:  python3 -m streamlit run app.py
All booking rules live in bus_logic.py. This file draws the screens.
"""
import base64
import hashlib
import io
import os
import re
import datetime as dt
import queue
import threading

import pandas as pd
import streamlit as st
from PIL import Image

from bus_logic import (BusSystem, add_sample_bookings, setup_waiting_list_demo, to_text,
                       CAPACITY, RED_SEATS, AUTO_CLOSE_MINUTES, DELAY_REASONS, TRIP_MINUTES,
                       DEMO_STUDENT, DEMO_LECTURER, DEMO_DRIVER, DEMO_STAFF, DEMO_LOGISTICS,
                       DRIVER_PLATES, WAIT_S1, WAIT_S2, WAIT_S3)

try:
    import qrcode
except ImportError:          # the app still works without the picture
    qrcode = None

try:
    import cv2
    from streamlit_webrtc import WebRtcMode, webrtc_streamer
except ImportError:          # install requirements.txt to enable continuous scanning
    cv2 = None
    WebRtcMode = None
    webrtc_streamer = None

ROUTES = {
    "APU → LRT Bukit Jalil": "APU-LRT",
    "LRT Bukit Jalil → APU": "LRT-APU",
}

# Prototype sign-in. A booking is always saved under the signed-in ID.
# Every role has one exact ID format; an ID in any other format cannot sign in.
ROLES = ["Student", "Lecturer", "Driver", "University staff", "Logistics"]
ID_PATTERNS = {
    "Student": (r"TP\d{6}", "TP + 6 digits, e.g. TP999001"),
    "Lecturer": (r"LEC-\d{4}", "LEC- + 4 digits, e.g. LEC-1001"),
    "Driver": (r"DRV-\d{4}", "DRV- + 4 digits, e.g. DRV-1001"),
    "University staff": (r"STAFF-\d{4}", "STAFF- + 4 digits, e.g. STAFF-1001"),
    "Logistics": (r"LOG-\d{4}", "LOG- + 4 digits, e.g. LOG-1001"),
}
DEMO_ACCOUNTS = {
    "Student": DEMO_STUDENT,
    "Lecturer": DEMO_LECTURER,
    "Driver": DEMO_DRIVER,
    "University staff": DEMO_STAFF,
    "Logistics": DEMO_LOGISTICS,
}
ROLE_ICONS = {
    "Student": ":material/school:",
    "Lecturer": ":material/person:",
    "Driver": ":material/directions_bus:",
    "University staff": ":material/bar_chart:",
    "Logistics": ":material/local_shipping:",
}


def valid_id(role, text):
    return re.fullmatch(ID_PATTERNS[role][0], text) is not None


def id_hint(role):
    return ID_PATTERNS[role][1]


# ---------- page setup, icon, fonts and colours ----------
_here = os.path.dirname(os.path.abspath(__file__))
_icon_path = os.path.join(_here, "bus_icon.png")
st.set_page_config(
    page_title="APU Shuttle Booking",
    page_icon=Image.open(_icon_path) if os.path.exists(_icon_path) else None,
    layout="wide",
)


def bus_svg(size=40):
    """Red shuttle bus icon (own drawing, in the style of the APSpace shuttle icon)."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}" '
        f'style="vertical-align:middle;flex-shrink:0">'
        '<rect x="10" y="8" width="44" height="42" rx="9" fill="#D9363E"/>'
        '<rect x="15" y="14" width="34" height="15" rx="4" fill="#fff"/>'
        '<rect x="15" y="33" width="34" height="3" rx="1.5" fill="#fff" opacity=".85"/>'
        '<circle cx="20" cy="43" r="3.4" fill="#fff"/><circle cx="44" cy="43" r="3.4" fill="#fff"/>'
        '<rect x="14" y="50" width="9" height="9" rx="2.5" fill="#444"/>'
        '<rect x="41" y="50" width="9" height="9" rx="2.5" fill="#444"/></svg>'
    )


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
html, body, .stApp, button, input, select, textarea, p, li, label, div[data-testid="stMarkdownContainer"] {
    font-family: 'Roboto', 'Helvetica Neue', Arial, sans-serif !important;
}
.stApp { background: #F7F7F7; }
h1, h2, h3, h4 { font-weight: 700 !important; color: #2B2B2B; letter-spacing: -0.2px; }
.stAppDeployButton, [data-testid="stMainMenu"], #MainMenu, footer { display: none !important; }
[data-testid="stExpandSidebarButton"], [data-testid="collapsedControl"] { display: flex !important; visibility: visible !important; }
header[data-testid="stHeader"] { background: transparent !important; }
.block-container { padding-top: 3.5rem; max-width: 1150px; }

/* cards */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #FFFFFF; border-radius: 16px !important; border: 1px solid #ECECEC !important;
    box-shadow: 0 2px 10px rgba(0,0,0,.06);
}
/* buttons */
.stButton > button { border-radius: 12px; font-weight: 500; border: 1px solid #DDDDDD; }
.stButton > button:hover { border-color: #F28C38; color: #F28C38; }
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] {
    background: #F28C38; border-color: #F28C38; color: #FFFFFF;
}
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: #E07A26; border-color: #E07A26; color: #FFFFFF;
}
.stButton > button:disabled { opacity: .55; }
[data-testid="stAlert"] { border-radius: 12px; }

/* header */
.hero img { height: 58px; width: auto; }
.hero-sep { width: 1px; height: 50px; background: #E3E3E3; }
.hero { flex-wrap: wrap; display: flex; align-items: center; gap: 16px; background: #FFFFFF; border-radius: 18px;
        padding: 16px 22px; box-shadow: 0 2px 10px rgba(0,0,0,.06); border-left: 8px solid #F28C38; margin-bottom: 8px; }
.hero-title { font-size: 1.7rem; font-weight: 700; color: #2B2B2B; line-height: 1.15; }
.hero-sub { color: #757575; font-size: .95rem; margin-top: 2px; }
.chips { margin: 6px 0 14px 0; }
.chip { display: inline-block; background: #FDEBDD; color: #B85C0F; border-radius: 999px;
        padding: 3px 12px; font-size: .8rem; font-weight: 500; margin-right: 6px; }
.side-title { display: flex; align-items: center; gap: 10px; font-size: 1.25rem; font-weight: 700; margin-bottom: 6px; }

/* trip rows */
.time { font-size: 1.55rem; font-weight: 700; color: #2B2B2B; line-height: 1.1; }
.sub { color: #757575; font-size: .85rem; }
.pill { display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: .85rem; font-weight: 500; }
.pill-green { background: #E6F4EA; color: #1E7B3A; }
.pill-orange { background: #FDEBDD; color: #B85C0F; }
.pill-red { background: #FDE7E7; color: #B3261E; }
.bar { height: 7px; background: #EEEEEE; border-radius: 6px; overflow: hidden; margin-top: 8px; }
.bar > div { height: 100%; border-radius: 6px; }
.notice { background: #FFF6E5; color: #8A5A00; border-radius: 10px; padding: 6px 12px; font-size: .88rem; margin-top: 4px; }
.plate { display: inline-flex; align-items: center; gap: 8px; background: #FFFFFF; border: 2px solid #D9363E;
         border-radius: 10px; padding: 3px 14px 3px 8px; font-weight: 700; letter-spacing: 1px; color: #2B2B2B; }
.trackcard { background: #FFFFFF; border-radius: 16px; padding: 14px 16px; border: 1px solid #ECECEC; }
.trackrow { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 10px; }
.eta { text-align: right; }
.eta-label { color: #757575; font-size: .9rem; }
.eta-big { font-size: 2.1rem; font-weight: 700; line-height: 1.1; }
.good { color: #2E9E5B; } .warn { color: #B85C0F; } .bad { color: #D9363E; }
.st-key-complete_button button { background: #2E9E5B !important; border-color: #2E9E5B !important; color: #FFFFFF !important; }
.st-key-complete_button button:hover { background: #25834B !important; border-color: #25834B !important; color: #FFFFFF !important; }
@media (max-width: 640px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 3rem; }
    .hero { padding: 12px 14px; gap: 10px; }
    .hero img { height: 38px; }
    .hero svg { width: 38px; height: 38px; }
    .hero-sep { height: 34px; }
    .hero-title { font-size: 1.25rem; }
    .hero-sub { font-size: .85rem; }
    .time { font-size: 1.3rem; }
    .eta-big { font-size: 1.7rem; }
    .chip { font-size: .72rem; padding: 2px 9px; }
}
.msg { background: #FFFFFF; border-left: 5px solid #F28C38; border-radius: 10px; padding: 10px 14px;
       margin-bottom: 8px; box-shadow: 0 1px 6px rgba(0,0,0,.06); font-size: .92rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


ROUTE_STOPS = {"APU-LRT": ("APU waiting area", "LRT Bukit Jalil"),
               "LRT-APU": ("LRT Bukit Jalil", "APU")}
APPROACH_PTS = [(40, 190), (130, 190), (190, 140), (260, 140)]
TRIP_PTS = [(260, 140), (340, 140), (400, 80), (480, 80), (540, 140), (600, 140)]


def point_on(points, fraction):
    """The point at `fraction` (0 to 1) of the way along a line made of straight pieces."""
    pieces = list(zip(points, points[1:]))
    lengths = [((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for (x1, y1), (x2, y2) in pieces]
    target = max(0.0, min(1.0, fraction)) * sum(lengths)
    for ((x1, y1), (x2, y2)), length in zip(pieces, lengths):
        if target <= length:
            r = target / length if length else 0
            return x1 + (x2 - x1) * r, y1 + (y2 - y1) * r
        target -= length
    return points[-1]


def bus_map_svg(state, origin, dest):
    """A simple route map. The bus position is SIMULATED (see bus_logic.bus_state)."""
    pts = APPROACH_PTS if state["segment"] == "approach" else TRIP_PTS
    x, y = point_on(pts, state["progress"])
    line = lambda p: " ".join(f"{a},{b}" for a, b in p)
    badge = ""
    if state["phase"] in ("on_break", "breakdown"):
        text, colour = ("ON BREAK", "#F28C38") if state["phase"] == "on_break" else ("BREAKDOWN", "#D9363E")
        badge = (f'<rect x="{x - 50:.0f}" y="{y - 74:.0f}" width="100" height="24" rx="12" fill="{colour}"/>'
                 f'<text x="{x:.0f}" y="{y - 57:.0f}" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">{text}</text>')
    return (
        '<svg viewBox="0 0 640 250" xmlns="http://www.w3.org/2000/svg" '
        'style="width:100%;height:auto;background:#EEF3F7;border-radius:14px;display:block">'
        f'<polyline points="{line(APPROACH_PTS)}" fill="none" stroke="#B0B7BE" stroke-width="8" stroke-dasharray="2 12" stroke-linecap="round"/>'
        f'<polyline points="{line(TRIP_PTS)}" fill="none" stroke="#F2B27A" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="260" cy="140" r="11" fill="#fff" stroke="#2B2B2B" stroke-width="4"/>'
        '<circle cx="600" cy="140" r="11" fill="#2B2B2B"/>'
        f'<text x="260" y="112" text-anchor="middle" font-size="15" font-weight="700" fill="#2B2B2B">{origin}</text>'
        f'<text x="628" y="178" text-anchor="end" font-size="15" font-weight="700" fill="#2B2B2B">{dest}</text>'
        f'<circle cx="{x:.0f}" cy="{y - 8:.0f}" r="26" fill="#fff" opacity=".92"/>'
        f'<g transform="translate({x - 19:.0f},{y - 32:.0f}) scale(.6)">'
        '<rect x="10" y="8" width="44" height="42" rx="9" fill="#D9363E"/>'
        '<rect x="15" y="14" width="34" height="15" rx="4" fill="#fff"/>'
        '<circle cx="20" cy="43" r="3.4" fill="#fff"/><circle cx="44" cy="43" r="3.4" fill="#fff"/>'
        '<rect x="14" y="50" width="9" height="9" rx="2.5" fill="#444"/>'
        '<rect x="41" y="50" width="9" height="9" rx="2.5" fill="#444"/></g>'
        f'{badge}</svg>'
    )


def tracking_panel(trip_id):
    """What a passenger sees: plate, ETA or status, and the (simulated) bus on a map."""
    trip = bus.trips[trip_id]
    state = bus.bus_state(trip_id, now)
    origin, dest = ROUTE_STOPS[trip["route"]]
    phase = state["phase"]
    if phase == "approaching" and state["late"]:
        label, big, cls, sub = "Bus is", "LATE", "warn", "Not arrived yet. The driver will confirm when it reaches the waiting area"
    elif phase == "approaching" and state["eta_min"] is None:
        label, big, cls, sub = "Bus is", "ARRIVING", "good", "Almost at the waiting area"
    elif phase == "approaching":
        label, big, cls, sub = "Pick up in", f'{state["eta_min"]} MIN', "good", f"On its way to {origin}"
    elif phase == "at_stop":
        label, big, cls, sub = "Your bus is", "HERE", "good", "Boarding at the waiting area"
    elif phase == "on_break":
        label, big, cls, sub = "Boarding resumes", to_text(state["resume"]), "warn", "The driver is on a short break"
    elif phase == "breakdown":
        label, big, cls, sub = "Bus status", "DELAYED", "bad", "Mechanical failure: backup bus requested"
    elif phase == "on_the_way":
        label, big, cls, sub = "Arrives in", f'{state["eta_min"]} MIN', "good", f"On the way to {dest}"
    elif phase == "arrived":
        label, big, cls, sub = "Bus has", "ARRIVED", "good", "Waiting for the driver to confirm"
    else:
        label, big, cls, sub = "Trip", "DONE", "good", "Thank you for riding with us"
    st.markdown(
        '<div class="trackcard"><div class="trackrow"><div>'
        f'{plate_html(trip["plate"])}<div class="sub" style="margin-top:6px">{sub}</div></div>'
        f'<div class="eta"><div class="eta-label">{label}</div><div class="eta-big {cls}">{big}</div></div></div>'
        f'{bus_map_svg(state, origin, dest)}'
        f'<div class="sub" style="margin-top:8px">Pick-up: {origin} · Drop-off: {dest} · '
        f'Trip duration: about {TRIP_MINUTES} min (sample)</div>'
        f'<div class="sub"><b>Simulated position</b> for this prototype. A real version would use the bus GPS. '
        f'Last updated: {to_text(now)}</div></div>',
        unsafe_allow_html=True,
    )


def trip_time_note(trip):
    """Short note under the time of a trip, based on what the bus is really doing."""
    state = bus.bus_state(trip["id"], now)
    phase = state["phase"]
    if phase == "approaching" and state["late"]:
        return "Late · not arrived yet"
    if phase == "at_stop":
        return "At the waiting area"
    if phase == "on_break":
        return "Driver break"
    if phase == "breakdown":
        return "Breakdown · backup requested"
    return minutes_until(trip["depart"])


def logo_html():
    """The APU logo for the header (the file apu_logo.png next to app.py)."""
    path = os.path.join(_here, "apu_logo.png")
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return (f'<img src="data:image/png;base64,{data}" alt="APU logo"/>'
            '<div class="hero-sep"></div>')


def seat_status_html(seats, capacity_now, waiting):
    """Coloured status pill + bar for the seats on a trip."""
    if seats <= 0:
        pill, text, colour, used = "pill-red", f"FULL · {waiting} waiting", "#D9363E", 100
    elif seats <= 5:
        word = "seat" if seats == 1 else "seats"
        pill, text, colour = "pill-orange", f"Only {seats} {word} left", "#F28C38"
        used = (capacity_now - seats) / capacity_now * 100
    else:
        pill, text, colour = "pill-green", f"{seats} seats left", "#2E9E5B"
        used = (capacity_now - seats) / capacity_now * 100
    return (f'<span class="pill {pill}">{text}</span>'
            f'<div class="bar"><div style="width:{used:.0f}%;background:{colour}"></div></div>')


def plate_html(plate):
    return f'<span class="plate">{bus_svg(24)}<span>{plate}</span></span>'


def notice_html(text):
    return f'<div class="notice"><b>Notice:</b> {text}</div>'


# ---------- start-up: create the system once and keep it in session_state ----------
def new_system(with_samples=True):
    bus = BusSystem()
    if with_samples:
        add_sample_bookings(bus)
    return bus


if "bus" not in st.session_state:
    st.session_state.bus = new_system(True)
if "flash" not in st.session_state:
    st.session_state.flash = None
if "scenario_trip" not in st.session_state:
    st.session_state.scenario_trip = None   # set by the waiting-list demo button
if "user" not in st.session_state:
    st.session_state.user = None            # {"id": ..., "role": ...} after sign-in

bus: BusSystem = st.session_state.bus


def qr_image(text):
    """Make a QR code picture (PNG bytes) from text."""
    if qrcode is None:
        return None
    img = qrcode.make(text)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def decode_qr(image_bytes):
    """Read the text of a QR code from a photo (computer vision with OpenCV).
    Returns the text, or None if no QR code was found. Raises ImportError if OpenCV is missing."""
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return None
    detector = cv2.QRCodeDetector()
    for scale in (1.0, 0.5, 2.0):            # phone photos vary in size, so try a few sizes
        picture = frame if scale == 1.0 else cv2.resize(frame, None, fx=scale, fy=scale)
        text, _, _ = detector.detectAndDecode(picture)
        if text:
            return text
    return None



def _new_live_scan_state():
    """Create a thread-safe queue and QR callback for one selected trip."""
    state = {"codes": queue.Queue(maxsize=1), "lock": threading.Lock(),
             "pending": False, "seen": set(), "callback": None,
             "last_result": None}
    detector = cv2.QRCodeDetector() if cv2 is not None else None

    def video_frame_callback(frame):
        # Runs on the WebRTC worker thread. Never call Streamlit APIs here.
        if detector is None:
            return frame
        try:
            image = frame.to_ndarray(format="bgr24")
            code, _, _ = detector.detectAndDecode(image)
            if code:
                with state["lock"]:
                    if code not in state["seen"] and not state["pending"]:
                        try:
                            state["codes"].put_nowait(code)
                            state["pending"] = True
                        except queue.Full:
                            pass
        except Exception:
            # A malformed frame should not stop the camera stream.
            pass
        return frame

    state["callback"] = video_frame_callback
    return state


@st.fragment(run_every=0.5)
def live_qr_scanner(trip_id, now):
    """Continuously scan camera frames and automatically board valid passengers."""
    if webrtc_streamer is None or cv2 is None:
        st.error("Live scanning needs the packages in requirements.txt. Install them and restart the app.")
        return

    states = st.session_state.setdefault("live_qr_scan_states", {})
    if trip_id not in states:
        states[trip_id] = _new_live_scan_state()
    state = states[trip_id]

    st.caption("Aim the camera at a passenger's QR code. A valid scan updates boarding automatically; then present the next passenger's code.")
    webrtc_streamer(
        key=f"live-qr-camera-{trip_id}",
        mode=WebRtcMode.SENDONLY,
        video_frame_callback=state["callback"],
        media_stream_constraints={"video": True, "audio": False},
        async_processing=True,
    )

    try:
        code = state["codes"].get_nowait()
    except queue.Empty:
        code = None

    if code is not None:
        ok, message = bus.scan(code, trip_id, now)
        with state["lock"]:
            state["pending"] = False
            state["seen"].add(code)  # avoid repeatedly reporting the same QR while it remains in view
            # Keep the result in session state so it survives the dashboard rerun.
            state["last_result"] = ("success" if ok else "error", message)

        if ok:
            # Recalculate the dashboard metric immediately. The stored result
            # is rendered again after the full-app rerun.
            st.rerun()

    # Show the most recent scan result beneath the live camera. Keeping it in
    # the per-trip state prevents the half-second fragment refresh from hiding it.
    with state["lock"]:
        last_result = state.get("last_result")

    if last_result:
        result_kind, result_message = last_result
        if result_kind == "success":
            st.success(result_message)
        else:
            st.error(result_message)


def flash(message, kind="info"):
    st.session_state.flash = (kind, message)
    st.rerun()


def messages_box(person_id):
    """Show notifications addressed to the signed-in student or lecturer."""
    person_messages = [
        message for recipient_id, message in bus.notifications
        if recipient_id == person_id
    ]

    st.subheader("Messages and notifications")
    if not person_messages:
        st.caption("You have no messages yet.")
        return

    st.caption(f"You have {len(person_messages)} message(s).")
    for message in reversed(person_messages):
        st.info(message)


def minutes_until(depart):
    diff = depart - now
    if diff == 0:
        return "scheduled time is now"
    if diff < 0:
        return "scheduled time passed"
    return f"in {diff} min" if diff < 60 else f"in {diff // 60} h {diff % 60:02d} min"


# ---------- sidebar: demo clock + account ----------
st.sidebar.markdown(f'<div class="side-title">{bus_svg(30)} Demo controls</div>', unsafe_allow_html=True)
def bump_clock(minutes):
    cur = st.session_state.demo_clock
    total = min(22 * 60, cur.hour * 60 + cur.minute + minutes)
    st.session_state.demo_clock = dt.time(total // 60, total % 60)


if "demo_clock" not in st.session_state:
    st.session_state.demo_clock = dt.time(17, 0)
demo_time = st.sidebar.slider(
    "Demo clock (Mon-Fri)",
    min_value=dt.time(6, 0), max_value=dt.time(22, 0),
    step=dt.timedelta(minutes=1), format="HH:mm", key="demo_clock",
)
clock_a, clock_b = st.sidebar.columns(2)
clock_a.button("+1 min", on_click=bump_clock, args=(1,), key="clock_plus1")
clock_b.button("+5 min", on_click=bump_clock, args=(5,), key="clock_plus5")
now = demo_time.hour * 60 + demo_time.minute
st.sidebar.caption(
    "Sets the time of day for the whole app, so you can test any moment of the day. "
    "Move it **forward** to see red seats open to students."
)

# time moves on -> release red seats, promote the waiting list, close very old buses
bus.refresh(now)
bus.close_departed_trips(now)

user = st.session_state.user
st.sidebar.markdown("---")
if user:
    extra = f" · bus {DRIVER_PLATES[user['id']]}" if user["role"] == "Driver" and user["id"] in DRIVER_PLATES else ""
    st.sidebar.markdown(f"**Signed in:** {user['id']}  \n*Role: {user['role']}{extra}*")
    if st.sidebar.button("Sign out", icon=":material/logout:"):
        st.session_state.user = None
        st.rerun()
else:
    st.sidebar.caption("Not signed in.")

st.sidebar.markdown("---")
if st.sidebar.button("Load waiting-list demo (one full bus)"):
    scenario = setup_waiting_list_demo(bus, now)
    st.session_state.scenario_trip = scenario
    if scenario:
        flash(f"Waiting-list demo ready: the {to_text(bus.trips[scenario]['depart'])} APU → LRT bus is full. "
              f"Sign in as {WAIT_S1}, {WAIT_S2} or {WAIT_S3} (see the sign-in page).", "success")
    else:
        flash("No more APU → LRT buses today. Move the demo clock back.", "warning")
if st.sidebar.button("Reset demo (with sample bookings)"):
    st.session_state.bus = new_system(True)
    st.session_state.scenario_trip = None
    st.rerun()
if st.sidebar.button("Reset demo (empty, no sample data)"):
    st.session_state.bus = new_system(False)
    st.session_state.scenario_trip = None
    st.rerun()
with st.sidebar.expander("About this prototype"):
    st.markdown(
        f"- {CAPACITY} seats per bus, {RED_SEATS} of them red seats for lecturers\n"
        "- Red seats are for lecturers; if they are not booked, students can book them one hour before departure\n"
        f"- A bus closes when the driver presses *Bus has left* "
        f"(or {AUTO_CLOSE_MINUTES} min after its scheduled time, as a safety net)\n"
        "- Bus times come from APSpace (Mon-Fri). Bus plates and backup buses are samples\n"
        "- Busy-time bookings are **simulated sample data**. Their IDs (TP9xxxxx, LEC-5xxx) can sign in, so you can test any passenger\n"
        "- Messages appear inside this app. A real version would use APSpace notifications"
    )

# ---------- header ----------
st.markdown(
    f'<div class="hero">{logo_html()}{bus_svg(54)}<div><div class="hero-title">APU Shuttle Booking</div>'
    '<div class="hero-sub">Book your seat, know your bus, skip the long queue</div></div></div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="chips"><span class="chip">Demo clock {to_text(now)}</span>'
    '<span class="chip">Student prototype · not an official APU service</span>'
    '<span class="chip">Sample data</span>'
    '<span class="chip">Times from APSpace (Mon-Fri)</span></div>',
    unsafe_allow_html=True,
)

if user:
    who, out = st.columns([6, 1.6])
    extra_main = (f" · bus {DRIVER_PLATES[user['id']]}"
                  if user["role"] == "Driver" and user["id"] in DRIVER_PLATES else "")
    who.markdown(f'<span class="chip">Signed in: {user["id"]} · {user["role"]}{extra_main}</span>',
                 unsafe_allow_html=True)
    if out.button("Sign out", key="signout_main", icon=":material/logout:"):
        st.session_state.user = None
        st.rerun()

if st.session_state.flash:
    kind, message = st.session_state.flash
    {"success": st.success, "warning": st.warning, "error": st.error}.get(kind, st.info)(message)
    st.session_state.flash = None


# =====================================================================
# SIGN-IN SCREEN
# =====================================================================
def sign_in_error(role, raw):
    """Returns a message if this ID cannot sign in, otherwise None. Used by EVERY sign-in button."""
    clean = raw.strip().upper()
    if not valid_id(role, clean):
        return f"This is not a valid {role.lower()} ID. The format is: {id_hint(role)}"
    if role == "Driver" and clean not in DRIVER_PLATES:
        return "Unknown driver ID. Registered drivers: " + ", ".join(DRIVER_PLATES)
    return None


def try_sign_in(role, raw):
    error = sign_in_error(role, raw)
    if error:
        st.error(error)
        return
    st.session_state.user = {"id": raw.strip().upper(), "role": role}
    st.rerun()


def sign_in_screen():
    st.subheader("Sign in")
    st.write(
        "Prototype sign-in: choose a role and use a demo ID (no password). "
        "Every booking is saved under the ID you sign in with."
    )
    st.caption("A real version would use the APSpace account instead.")
    st.markdown("**Quick demo accounts**")
    cols = st.columns(len(DEMO_ACCOUNTS))
    for col, (role, account) in zip(cols, DEMO_ACCOUNTS.items()):
        if col.button(f"{role}\n{account}", key=f"quick_{role}", icon=ROLE_ICONS[role]):
            try_sign_in(role, account)

    if st.session_state.scenario_trip:
        st.markdown("**Waiting-list demo accounts (students)**")
        s1, s2, s3 = st.columns(3)
        for col, (acc, note) in zip((s1, s2, s3),
                                    ((WAIT_S1, "holds the last seat"),
                                     (WAIT_S2, "waiting list #1"),
                                     (WAIT_S3, "waiting list #2"))):
            if col.button(f"{acc}\n{note}", key=f"quick_{acc}", icon=ROLE_ICONS["Student"]):
                try_sign_in("Student", acc)

    st.markdown("**Or sign in with your own demo ID**")
    c1, c2, c3 = st.columns([1.3, 2, 1])
    role = c1.selectbox("Role", ROLES, key="login_role")
    entered = c2.text_input(f"ID ({id_hint(role)})", key="login_id")
    c3.write("")
    c3.write("")
    if c3.button("Sign in", key="login_button", type="primary"):
        try_sign_in(role, entered)

# =====================================================================
# STUDENT VIEW
# =====================================================================
def student_view(student_id):
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Book a shuttle seat")
        if st.session_state.scenario_trip and st.session_state.scenario_trip in bus.trips:
            t = bus.trips[st.session_state.scenario_trip]
            st.info(f"Waiting-list demo: the {to_text(t['depart'])} APU → LRT bus is full. "
                    f"{WAIT_S1} holds a seat, {WAIT_S2} is waiting #1 and {WAIT_S3} is waiting #2. "
                    f"When {WAIT_S1} cancels, {WAIT_S2} gets the seat automatically.")
        route_name = st.radio("Route", list(ROUTES), horizontal=True, key="student_route")
        route = ROUTES[route_name]

        upcoming = bus.open_trips(route, now)
        show_all = st.checkbox("Show all upcoming trips", value=False, key="student_showall")
        shown = upcoming if show_all else upcoming[:10]

        if not upcoming:
            st.info("No more buses on this route today. Move the demo clock back.")

        # Check if student currently holds an active confirmed seat on any bus
        has_active_booking = any(b["status"] == "booked" for b in bus.bookings_of(student_id))

        for trip in shown:
            tid = trip["id"]
            seats = bus.seats_left_students(tid, now)
            capacity_now = bus.student_capacity(tid, now)
            
            # Fetch any non-cancelled booking for this trip
            trip_bookings = [b for b in bus.bookings_of(student_id) if b["trip"] == tid and b["status"] != "cancelled"]
            mine = trip_bookings[0] if trip_bookings else None

            with st.container(border=True):
                c1, c2, c3 = st.columns([1.3, 3, 1.9])
                c1.markdown(f'<div class="time">{to_text(trip["depart"])}</div>'
                            f'<div class="sub">{trip_time_note(trip)}</div>', unsafe_allow_html=True)
                c2.markdown(seat_status_html(seats, capacity_now, bus.waiting_count(tid)), unsafe_allow_html=True)

                if mine:
                    if mine["status"] == "booked":
                        if c3.button("Cancel booking", key=f"cancel_{tid}"):
                            ok, msg = bus.cancel(mine["id"], now)
                            flash(msg, "success" if ok else "error")
                    elif mine["status"] == "waiting":
                        pos = bus.waiting_position(mine)
                        if c3.button(f"Leave waiting list (#{pos})", key=f"leave_{tid}"):
                            ok, msg = bus.cancel(mine["id"], now)
                            flash(msg, "success" if ok else "error")
                    elif mine["status"] == "used":
                        c3.markdown('<span class="pill pill-green">Boarded</span>', unsafe_allow_html=True)
                else:
                    if seats > 0:
                        pressed = c3.button("Book", key=f"book_{tid}", type="primary", disabled=has_active_booking)
                    else:
                        pressed = c3.button("Join waiting list", key=f"book_{tid}")
                    if pressed:
                        booking, msg = bus.book_student(tid, student_id, now)
                        if booking and booking["status"] == "booked":
                            flash(f"{msg} Your bus plate: {trip['plate']}", "success")
                        else:
                            flash(msg, "warning")

                if trip.get("notice"):
                    st.markdown(notice_html(trip["notice"]), unsafe_allow_html=True)

        st.caption("Red seats are for lecturers. If the red seats are not booked, students can book them "
                   "one hour before departure. A bus that is late stays in the list until the driver "
                   "confirms it has left.")

    with right:
        st.subheader("My bookings")
        mine_all = [b for b in bus.bookings_of(student_id) if b["status"] != "cancelled"]
        if not mine_all:
            st.caption("No bookings yet. Book a trip on the left.")
        for b in sorted(mine_all, key=lambda b: bus.trips[b["trip"]]["depart"]):
            trip = bus.trips[b["trip"]]
            with st.container(border=True):
                st.markdown(f'**{to_text(trip["depart"])} · {trip["route"].replace("-", " → ")}**')
                if b["status"] == "booked":
                    st.success(f'Booked ({b.get("kind") or "standard seat"}). Show this QR code to the driver.')
                    st.markdown("Bus plate: " + plate_html(trip["plate"]), unsafe_allow_html=True)
                    st.caption("Check the plate before you board. A bus can arrive a few minutes after the timetable.")
                    code = bus.qr_text(b)
                    img = qr_image(code)
                    if img:
                        st.image(img, width=170)
                    st.code(code, language=None)
                elif b["status"] == "waiting":
                    st.warning(f"On the waiting list, number {bus.waiting_position(b)}")
                elif b["status"] == "used":
                    st.success("Boarded")
                elif b["status"] == "no_show":
                    st.error("Missed (no-show)")
                elif b["status"] == "expired":
                    st.error("No seat was available")

                if b["status"] in ("booked", "used"):
                    with st.expander("Track my bus", expanded=not trip["completed"]):
                        tracking_panel(trip["id"])

        messages_box(student_id)
# =====================================================================
# LECTURER VIEW
# =====================================================================
def lecturer_view(lecturer_id):
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Book a red seat")
        st.write(
            "Red seats are for lecturers. If a red seat is not booked, students can book it "
            "**one hour before departure**. If all red seats are occupied, lecturers can join the waiting list. "
            "When a red seat is released, the earliest waiting lecturer gets priority; if none are waiting, "
            "the earliest waiting student gets the seat. You can hold only one confirmed booking across buses."
        )
        route_name = st.radio("Route", list(ROUTES), horizontal=True, key="lecturer_route")
        route = ROUTES[route_name]
        upcoming = bus.open_trips(route, now)
        show_all = st.checkbox("Show all upcoming trips", value=False, key="lecturer_showall")
        shown = upcoming if show_all else upcoming[:10]

        if not upcoming:
            st.info("No more buses on this route today. Move the demo clock back.")

        # Check if lecturer currently holds an active confirmed red seat on any bus
        has_active_booking = any(b["status"] == "booked" for b in bus.bookings_of(lecturer_id))

        for trip in shown:
            tid = trip["id"]
            released = bus.red_released(tid, now)
            open_at = to_text(trip["depart"] - 60)
            left_n = bus.red_seats_left(tid)
            
            # Fetch any non-cancelled booking for this trip
            trip_bookings = [b for b in bus.bookings_of(lecturer_id) if b["trip"] == tid and b["status"] != "cancelled"]
            mine = trip_bookings[0] if trip_bookings else None

            with st.container(border=True):
                c1, c2, c3 = st.columns([1.3, 3, 1.9])
                c1.markdown(f'<div class="time">{to_text(trip["depart"])}</div>'
                            f'<div class="sub">{trip_time_note(trip)}</div>', unsafe_allow_html=True)
                pill = "pill-green" if left_n > 1 else ("pill-orange" if left_n == 1 else "pill-red")
                
                # Check if red seats are left, but the bus itself is completely full
                if left_n > 0 and bus._occupied(tid) >= bus.capacity:
                    note = "Bus is full (red seats claimed by students)"
                elif released:
                    note = "open to students now"
                else:
                    note = f"open to students at {open_at}"

                c2.markdown(f'<span class="pill {pill}">Red seats left: {left_n}/{bus.red_seats}</span>'
                            f'<div class="sub" style="margin-top:6px">{note}</div>',
                            unsafe_allow_html=True)
                
                if mine:
                    if mine["status"] == "booked":
                        if c3.button("Cancel red seat", key=f"lcancel_{tid}"):
                            ok, msg = bus.cancel(mine["id"], now)
                            flash(msg, "success" if ok else "error")
                    elif mine["status"] == "waiting":
                        pos = bus.waiting_position(mine)
                        if c3.button(f"Leave waiting list (#{pos})", key=f"lleave_{tid}"):
                            ok, msg = bus.cancel(mine["id"], now)
                            flash(msg, "success" if ok else "error")
                    elif mine["status"] == "used":
                        c3.markdown('<span class="pill pill-green">Boarded</span>', unsafe_allow_html=True)
                else:
                    can_book_seat = (left_n > 0 and bus._occupied(tid) < bus.capacity)
                    if can_book_seat:
                        pressed = c3.button("Book red seat", key=f"lbook_{tid}", type="primary", disabled=has_active_booking)
                    else:
                        pressed = c3.button("Join waiting list", key=f"lbook_{tid}")
                    
                    if pressed:
                        booking, msg = bus.book_lecturer(tid, lecturer_id, now)
                        if booking and booking["status"] == "booked":
                            flash(f"{msg} Your bus plate: {trip['plate']}", "success")
                        else:
                            flash(msg, "warning")

                if trip.get("notice"):
                    st.markdown(notice_html(trip["notice"]), unsafe_allow_html=True)

    with right:
        st.subheader("My red seats")
        my = [b for b in bus.bookings_of(lecturer_id) if b["status"] != "cancelled"]
        if not my:
            st.caption("None yet.")
        for b in sorted(my, key=lambda b: bus.trips[b["trip"]]["depart"]):
            trip = bus.trips[b["trip"]]
            with st.container(border=True):
                st.markdown(f'**{to_text(trip["depart"])} · {trip["route"].replace("-", " → ")}**')
                if b["status"] == "booked":
                    st.success("Red seat booked. Show this QR code to the driver.")
                    st.markdown("Bus plate: " + plate_html(trip["plate"]), unsafe_allow_html=True)
                    code = bus.qr_text(b)
                    img = qr_image(code)
                    if img:
                        st.image(img, width=150)
                    st.code(code, language=None)
                elif b["status"] == "waiting":
                    st.warning(f"On the waiting list, number {bus.waiting_position(b)}")
                elif b["status"] == "used":
                    st.success("Boarded")
                elif b["status"] == "no_show":
                    st.error("Missed (no-show)")

                if b["status"] in ("booked", "used"):
                    with st.expander("Track my bus", expanded=not trip["completed"]):
                        tracking_panel(trip["id"])

        messages_box(lecturer_id)


# =====================================================================
# DRIVER VIEW
# =====================================================================
def driver_view():
    st.subheader("Driver: scanner, departure and updates")
    st.write(
        "Scan each passenger's QR code while boarding. When the bus leaves, press **Bus has left**: "
        "passengers who boarded are told their journey started, passengers who did not scan are told they "
        "missed the bus. At the end, press **Trip completed**. The driver decides, not the clock, "
        "because buses are not always on time."
    )
    my_plate = DRIVER_PLATES[user["id"]]
    st.markdown("You are driving: " + plate_html(my_plate), unsafe_allow_html=True)
    trips = bus.driver_trips(my_plate, now)
    if not trips:
        st.info("No open trips for your bus right now. Move the demo clock back or reset the demo.")
        return

    def trip_label(tid):
        t = bus.trips[tid]
        extra = " · on the way" if t["left"] else ""
        return f'{to_text(t["depart"])} · {t["route"].replace("-", " → ")}{extra}'

    trip_id = st.selectbox("Your trips (scheduled departure)", [t["id"] for t in trips[:20]],
                           format_func=trip_label, key="driver_trip")
    trip = bus.trips[trip_id]
    chosen = to_text(trip["depart"])
    st.caption(f'Left at {to_text(trip["left_at"])}' if trip["left"] else trip_time_note(trip))

    on_trip = [b for b in bus.bookings if b["trip"] == trip_id]
    boarded = sum(1 for b in on_trip if b["status"] == "used")
    # Keep no-shows in the denominator after departure: they were confirmed bookings too.
    confirmed = sum(1 for b in on_trip if b["status"] in ("booked", "used", "no_show"))
    missed = sum(1 for b in on_trip if b["status"] == "no_show")
    actual_scans = sum(1 for b in on_trip
                       if b["status"] == "used" and b.get("boarding_source") == "qr_scan")
    manual_boardings = sum(1 for b in on_trip
                           if b["status"] == "used" and b.get("boarding_source") == "manual")
    simulated_boardings = sum(1 for b in on_trip
                              if b["status"] == "used" and b.get("boarding_source") == "simulated")

    st.metric("Boarded / confirmed bookings", f"{boarded} / {confirmed}")
    stat_cols = st.columns(4)
    stat_cols[0].metric("Verified QR/code scans", actual_scans)
    stat_cols[1].metric("Manual backup", manual_boardings)
    stat_cols[2].metric("Simulated boardings", simulated_boardings)
    stat_cols[3].metric("Missed the bus", missed)
    if simulated_boardings or any(b.get("sample") for b in on_trip):
        st.caption("Demo transparency: simulated boardings are generated sample activity, not camera scans. "
                   "Verified QR/code scans and manual backup boardings are counted separately.")

    with st.expander("What the passengers see (map and status)", expanded=False):
        tracking_panel(trip_id)

    if trip["left"]:
        with st.container(border=True):
            st.markdown("**Trip in progress**")
            st.caption("When you reach the destination, press the green button. "
                       "Passengers who boarded get a message that their trip has completed.")
            if st.button("Trip completed · notify passengers", type="primary", key="complete_button",
                         icon=":material/check_circle:"):
                n = bus.complete_trip(trip_id, now)
                flash(f"Trip completed. {n} passengers who boarded were thanked.", "success")
    else:
        with st.container(border=True):
            st.markdown("**Scan a passenger** · demo shortcut: the passenger holds their QR code to the scanner")
            pickable = [b for b in on_trip if b["status"] == "booked"]
            # real demo users first, simulated sample bookings after them
            pickable = sorted(pickable, key=lambda b: (bool(b.get("sample")), b["id"]))
            if pickable:
                options = {f'{b["person"]} ({b["role"]})': b for b in pickable}
                pick = st.selectbox("Passenger", list(options), key="driver_pick")
                if st.button("Scan this booking", type="primary", icon=":material/qr_code_scanner:"):
                    ok, msg = bus.scan(bus.qr_text(options[pick]), trip_id, now)
                    if ok:
                        options[pick]["boarding_source"] = "manual"
                    flash(msg, "success" if ok else "error")
            else:
                st.caption("No unscanned bookings on this bus.")

            typed = st.text_input("Or type / paste a QR code text", key="driver_typed",
                                  placeholder="e.g. 12|APU-LRT@18:00|abc123def0")
            if st.button("Check typed code"):
                ok, msg = bus.scan(typed.strip(), trip_id, now)
                flash(msg, "success" if ok else "error")

            with st.expander("Live QR scanner (phone or laptop)", expanded=True):
                live_qr_scanner(trip_id, now)

        with st.container(border=True):
            st.markdown("**At the waiting area**")
            state = bus.bus_state(trip_id, now)
            st.caption(f"Passengers see: {state['text']}")
            w1, w2, w3 = st.columns([2.2, 1.6, 1.8])
            if w1.button("Bus has arrived at the waiting area", key="arrive_button", icon=":material/place:",
                         disabled=trip["arrived_at"] is not None):
                n = bus.mark_arrived(trip_id, now)
                if n is None:
                    flash("Cannot confirm arrival right now (a breakdown request is open).", "warning")
                flash(f"Arrival confirmed. {n} passengers were told that the bus is at the waiting area.", "success")
            minutes = w2.selectbox("Break (minutes)", [10, 20, 30, 45, 60], index=2, key="break_minutes")
            w3.write("")
            w3.write("")
            if state["phase"] == "on_break":
                if w3.button("End break now", key="end_break", icon=":material/play_arrow:"):
                    n = bus.end_break(trip_id, now)
                    flash(f"Break ended. {n} passengers were told.", "success")
            else:
                if w3.button("Start driver break", key="start_break", icon=":material/restaurant:",
                             disabled=not bus.at_waiting_area(trip_id, now)):
                    n = bus.start_break(trip_id, minutes, now)
                    if n is None:
                        flash("A break can start only after you pressed 'Bus has arrived at the waiting area'.", "warning")
                    flash(f"Break started. {n} passengers were told when boarding resumes.", "success")
            st.caption("Press 'arrived' when the bus reaches the waiting area: only then do passengers see "
                       "'Your bus is HERE'. A break can start after that. While the bus is parked on a break, "
                       "the map shows it parked and the ETA stops counting.")

        with st.container(border=True):
            st.markdown("**When the bus leaves**")
            if st.button("Bus has left · notify passengers", type="primary", key="depart_button",
                         icon=":material/directions_bus:"):
                result = bus.depart_trip(trip_id, now)
                if result is None:
                    flash("This bus was already closed.", "warning")
                else:
                    flash(f"Bus {chosen} marked as departed. Messages sent: {result['boarded']} boarded "
                          f"(journey started), {result['missed']} missed the bus, "
                          f"{result['waiting']} still on the waiting list (no seat).", "success")

        with st.container(border=True):
            st.markdown("**Tell the passengers** (tap, no typing)")
            if trip.get("notice"):
                st.markdown(notice_html(trip["notice"]), unsafe_allow_html=True)

            d1, d2, d3 = st.columns([2, 2, 2])
            reason = d1.selectbox("Reason for the delay", DELAY_REASONS, key="delay_reason")
            delay = d2.selectbox("How late (minutes)", [5, 10, 15, 20, 30], index=1, key="delay_minutes")
            d3.write("")
            d3.write("")
            if d3.button("Send late notice", key="send_late", icon=":material/schedule:"):
                n = bus.notify_delay(trip_id, reason, delay, now)
                if n is None:
                    flash("The bus has already arrived at the waiting area, so a late notice is not needed.", "warning")
                flash(f"Late notice sent to {n} passengers.", "success")

            e1, e2 = st.columns([2, 4])
            eta = e1.selectbox("I will arrive in (minutes)", [2, 5, 10], index=1, key="eta_minutes")
            e2.write("")
            e2.write("")
            if e2.button("I'm almost there, please wait at the waiting area", key="send_arriving",
                         icon=":material/location_on:"):
                n = bus.notify_arriving(trip_id, eta, now)
                if n is None:
                    flash("The bus is already at the waiting area.", "warning")
                flash(f"Message sent to {n} passengers.", "success")

        with st.container(border=True):
            st.markdown("**Breakdown**")
            open_incident = next((i for i in bus.incidents if i["trip"] == trip_id and i["status"] == "open"), None)
            done_incident = next((i for i in bus.incidents if i["trip"] == trip_id and i["status"] == "assigned"), None)
            if open_incident:
                st.warning(f"Backup bus requested at {to_text(open_incident['created'])}. Waiting for the logistics team.")
            elif done_incident:
                st.success(f"Backup bus assigned: plate {done_incident['backup_plate']}.")
            else:
                confirm = st.checkbox("Confirm: this bus has a mechanical failure", key="confirm_breakdown")
                if st.button("Mechanical failure · request a backup bus", disabled=not confirm,
                             key="send_breakdown", icon=":material/build:"):
                    incident = bus.report_breakdown(trip_id, now)
                    if incident:
                        flash(f"Passengers told. The logistics team was asked to prepare a backup bus "
                              f"({incident['passengers']} passengers on this bus).", "success")
                    else:
                        flash("A request is already open for this bus.", "warning")

    with st.expander("All bookings on this bus (to check the data)"):
        table = pd.DataFrame(
            [{"person": b["person"], "role": b["role"], "seat": b.get("kind", ""), "status": b["status"],
              "boarding source": {"qr_scan": "Verified QR/code", "manual": "Manual backup",
                                  "simulated": "Simulated demo"}.get(b.get("boarding_source"),
                                                                         "Not boarded / not recorded"),
              "data type": "Sample" if b.get("sample") else "Demo user"} for b in on_trip]
        )
        if not table.empty:
            table["_sort"] = table["data type"].eq("Sample")
            table = table.sort_values(["_sort"], kind="stable").drop(columns="_sort")
        st.dataframe(table, hide_index=True)


# =====================================================================
# LOGISTICS VIEW
# =====================================================================
def logistics_view():
    st.subheader("Logistics team: backup bus requests")
    st.write(
        "When a driver reports a mechanical failure, a request appears here at once. "
        "Assign a backup bus: the trip gets the new plate and every passenger is told."
    )
    if not bus.incidents:
        st.caption("No requests yet. A driver can send one from the Driver page.")
    for incident in reversed(bus.incidents):
        trip = bus.trips[incident["trip"]]
        with st.container(border=True):
            if incident["status"] == "open":
                badge = '<span class="pill pill-red">OPEN</span>'
            else:
                badge = '<span class="pill pill-green">Backup assigned</span>'
            st.markdown(f"{badge} &nbsp; **{to_text(trip['depart'])} · {trip['route'].replace('-', ' → ')}**",
                        unsafe_allow_html=True)
            st.markdown("Broken bus: " + plate_html(incident["plate"]) +
                        f" &nbsp; reported at {to_text(incident['created'])} · "
                        f"passengers on this bus: **{incident['passengers']}**", unsafe_allow_html=True)
            if incident["status"] == "open":
                spares = bus.available_spares()
                if not spares:
                    st.error("No spare bus is free right now.")
                else:
                    pick = st.selectbox("Backup bus", spares, key=f"spare_{incident['id']}")
                    if st.button("Assign this backup bus", key=f"assign_{incident['id']}", type="primary"):
                        bus.assign_backup(incident["id"], pick, now)
                        flash(f"{pick} assigned. Passengers were told the new plate.", "success")
            else:
                st.markdown("Backup bus: " + plate_html(incident["backup_plate"]) +
                            f" &nbsp; assigned at {to_text(incident['assigned_at'])}", unsafe_allow_html=True)


# =====================================================================
# UNIVERSITY VIEW
# =====================================================================
def university_view():
    st.subheader("Demand insights")
    st.write(
        "Booking data shows the university **which trips need extra buses**: "
        "long waiting lists mean not enough seats; many no-shows mean unused seats."
    )
    rows = pd.DataFrame(bus.demand_summary())
    rows["route"] = rows["trip"].str.split("@").str[0]
    rows["time"] = rows["trip"].str.split("@").str[1]
    route_name = st.radio("Route", list(ROUTES), horizontal=True, key="uni_route")
    view = rows[rows["route"] == ROUTES[route_name]].sort_values("time")

    with st.container(border=True):
        st.markdown("**Bookings, waiting list and no-shows per trip**")
        st.bar_chart(view.set_index("time")[["booked", "waiting", "no_show"]],
                     color=["#2E9E5B", "#F28C38", "#D9363E"])

    with st.container(border=True):
        st.markdown("**Trips with the longest waiting lists**")
        top = view.sort_values("waiting", ascending=False).head(5)[["time", "booked", "waiting", "no_show"]]
        st.dataframe(top, hide_index=True)
        st.caption("Sample data is simulated for the demo. Real numbers would come from real bookings.")


# =====================================================================
# SHOW THE RIGHT SCREEN FOR THE SIGNED-IN ROLE
# =====================================================================
if not user:
    sign_in_screen()
elif user["role"] == "Student":
    student_view(user["id"])
elif user["role"] == "Lecturer":
    lecturer_view(user["id"])
elif user["role"] == "Driver":
    driver_view()
elif user["role"] == "Logistics":
    logistics_view()
else:
    university_view()
