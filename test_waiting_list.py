"""Tests for the waiting list: run with  python3 test_waiting_list.py"""
from bus_logic import BusSystem, setup_waiting_list_demo, to_minutes, WAIT_S1, WAIT_S2, WAIT_S3

def status(bus, person, trip):
    return [b["status"] for b in bus.bookings if b["person"] == person and b["trip"] == trip][-1]
def booking(bus, person):
    return [b for b in bus.bookings if b["person"] == person][0]
def check(name, condition):
    print(("PASS  " if condition else "FAIL  ") + name)
    assert condition, name

now = to_minutes("16:30")

# ---------- Scenario 1: the demo bus (S1 holds a seat, S2 and S3 wait) ----------
bus = BusSystem()
trip = setup_waiting_list_demo(bus, now)
check("demo bus is full for students", bus.seats_left_students(trip, now) == 0)
check("S1 holds a seat", status(bus, WAIT_S1, trip) == "booked")
check("S2 is waiting", status(bus, WAIT_S2, trip) == "waiting")
check("S2 is number 1, S3 is number 2",
      bus.waiting_position(booking(bus, WAIT_S2)) == 1 and bus.waiting_position(booking(bus, WAIT_S3)) == 2)

ok, _ = bus.cancel(booking(bus, WAIT_S1)["id"], now)
check("S1 cancels", ok and status(bus, WAIT_S1, trip) == "cancelled")
check("S2 got the seat automatically", status(bus, WAIT_S2, trip) == "booked")
check("S3 is still waiting and is now number 1",
      status(bus, WAIT_S3, trip) == "waiting" and bus.waiting_position(booking(bus, WAIT_S3)) == 1)
msgs_s2 = [t for who, t in bus.notifications if who == WAIT_S2]
check("S2 got a message with the bus plate", len(msgs_s2) == 1 and bus.trips[trip]["plate"] in msgs_s2[0])
check("S3 got no message yet", not [t for who, t in bus.notifications if who == WAIT_S3])
ok, _ = bus.scan(bus.qr_text(booking(bus, WAIT_S2)), trip, now)
check("S2's new booking works with the QR scan", ok)

# ---------- Scenario 2: the second person is promoted too ----------
bus = BusSystem()
trip = setup_waiting_list_demo(bus, now)
bus.cancel(booking(bus, WAIT_S1)["id"], now)
bus.cancel(booking(bus, WAIT_S2)["id"], now)
check("after S2 also cancels, S3 gets the seat", status(bus, WAIT_S3, trip) == "booked")

# ---------- Scenario 3: someone leaves the waiting list ----------
bus = BusSystem()
trip = setup_waiting_list_demo(bus, now)
bus.cancel(booking(bus, WAIT_S2)["id"], now)                # leaves the queue
check("S3 moves up to number 1", bus.waiting_position(booking(bus, WAIT_S3)) == 1)
bus.cancel(booking(bus, WAIT_S1)["id"], now)
check("S3 gets the seat, S2 (who left) does not",
      status(bus, WAIT_S3, trip) == "booked" and status(bus, WAIT_S2, trip) == "cancelled")

# ---------- Scenario 4: red seats and the waiting list ----------
small = BusSystem(capacity=5, red_seats=2)                  # 3 standard + 2 red seats
t = "APU-LRT@18:00"
early = to_minutes("15:00")
for n in ("A", "B", "C"):
    small.book_student(t, n, early)
small.book_student(t, "WAIT1", early)
lec, _ = small.book_lecturer(t, "LEC-X", early)
small.cancel(lec["id"], early)
check("lecturer cancels BEFORE the 1-hour mark: red seat stays red, no promotion",
      status(small, "WAIT1", t) == "waiting")
small.refresh(to_minutes("17:00"))
check("at the 1-hour mark unused red seats open and WAIT1 is promoted",
      status(small, "WAIT1", t) == "booked")

# ---------- Scenario 5: nobody can cancel after the driver closed the bus ----------
small.depart_trip(t, to_minutes("18:05"))
ok, _ = small.cancel(booking(small, "A")["id"], to_minutes("18:06"))
check("cancelling after the bus left is refused", not ok)

print("\nAll waiting-list tests passed.")
