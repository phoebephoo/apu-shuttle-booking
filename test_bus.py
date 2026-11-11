"""Core tests: run with  python3 test_bus.py"""
from bus_logic import BusSystem, to_minutes

def t(x): return to_minutes(x)
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    assert cond, name

# Small bus so the test is short: 5 seats, 2 red seats -> 3 student seats
bus = BusSystem(capacity=5, red_seats=2)
trip = "APU-LRT@18:00"
early = t("15:00")          # more than 1 hour before departure

for name in ["S1", "S2", "S3"]:
    bus.book_student(trip, name, early)
check("students fill the 3 standard seats", bus.seats_left_students(trip, early) == 0)
bus.book_student(trip, "S4", early)
bus.book_student(trip, "S5", early)
check("full bus -> waiting list", bus.waiting_count(trip) == 2)
check("same student cannot book twice", bus.book_student(trip, "S1", early)[0] is None)

s2 = [b for b in bus.bookings if b["person"] == "S2"][0]
bus.cancel(s2["id"], early)
check("S2 cancels -> S4 (first in the queue) gets the seat",
      [b["status"] for b in bus.bookings if b["person"] == "S4"][0] == "booked")

lec, _ = bus.book_lecturer(trip, "L1", early)
check("lecturer books a red seat", lec is not None)
bus.refresh(t("17:00"))
check("1 hour before: unused red seat opens, S5 promoted",
      [b["status"] for b in bus.bookings if b["person"] == "S5"][0] == "booked")

# ---- QR checks
s1 = [b for b in bus.bookings if b["person"] == "S1"][0]
code = bus.qr_text(s1)
check("QR scan works once", bus.scan(code, trip, t("17:55"))[0])
check("same QR twice is refused", not bus.scan(code, trip, t("17:56"))[0])
s3 = [b for b in bus.bookings if b["person"] == "S3"][0]
check("QR for another bus is refused", not bus.scan(bus.qr_text(s3), "APU-LRT@18:30", t("17:57"))[0])
check("fake QR is refused", not bus.scan("1|APU-LRT@18:00|abcdef1234", trip, t("17:58"))[0])

# a student joins the waiting list BEFORE the scheduled time (bus is full)
check("full bus: late joiner is waiting", bus.book_student(trip, "LATE1", t("17:50"))[0]["status"] == "waiting")

# ---- the bus is LATE: scheduled 18:00, still not left at 18:12
check("bus is still open at 18:12 (late bus)", not bus.has_departed(trip, t("18:12")))
s4 = [b for b in bus.bookings if b["person"] == "S4"][0]
check("a passenger can still be scanned on a late bus (before the driver presses the button)",
      bus.scan(bus.qr_text(s4), trip, t("18:12"))[0])
import bus_logic as bl
check("agreed logic: a bus that is late but has not left still accepts bookings",
      bus.book_student("APU-LRT@18:10", "LATEX", t("18:12"))[0] is not None)
bl.BOOKING_GRACE_MINUTES = 0                                  # optional stricter rule
check("optional rule (grace 0): new bookings close at the scheduled time",
      bus.book_student("APU-LRT@18:10", "LATEY", t("18:12"))[0] is None)
bl.BOOKING_GRACE_MINUTES = None                               # back to the agreed logic

# ---- the driver presses "bus has left" at 18:12
counts = bus.depart_trip(trip, t("18:12"))
msgs = {}
for who, text in bus.notifications:
    msgs.setdefault(who, []).append(text)
check("S1 (scanned) is told the journey started", "journey has started" in msgs["S1"][-1])
check("S3 (did not scan) is told they missed the bus", "missed" in msgs["S3"][-1])
check("L1 (lecturer, did not scan) is told they missed the bus", "missed" in msgs["L1"][-1] and "red seat" in msgs["L1"][-1])
check("waiting student is told there was no seat", "did not get a seat" in msgs["LATE1"][-1])
check("counts are right", counts == {"boarded": 2, "missed": 3, "waiting": 1})
check("pressing the button twice does nothing", bus.depart_trip(trip, t("18:13")) is None)
check("booking after the bus left is refused", bus.book_student(trip, "LATE2", t("18:14"))[0] is None)
check("scanning after the bus left is refused", not bus.scan(bus.qr_text(s3), trip, t("18:14"))[0])

# ---- the driver forgets: safety net closes the bus 30 min after the scheduled time
other = "APU-LRT@18:30"
bus.book_student(other, "FORGOT", early)
bus.close_departed_trips(t("18:59"))
check("safety net does not close the bus too early", not bus.trips[other]["left"])
bus.close_departed_trips(t("19:01"))
check("safety net closes a bus 30 min after its scheduled time", bus.trips[other]["left"])
check("the student on that bus is told they missed it",
      any("missed" in text for who, text in bus.notifications if who == "FORGOT"))

print("\nAll core tests passed.")
