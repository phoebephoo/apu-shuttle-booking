"""Tests for driver notices, breakdown and backup bus: run with  python3 test_driver_notices.py"""
from bus_logic import BusSystem, to_minutes as t, SPARE_BUSES

def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    assert cond, name

def msgs(bus, person):
    return [text for who, text in bus.notifications if who == person]

bus = BusSystem()
trip = "APU-LRT@17:10"
early = t("15:00")
for person in ("TP111111", "TP222222"):
    bus.book_student(trip, person, early)
bus.book_lecturer(trip, "LEC-ONE", early)
bus.book_student("APU-LRT@17:20", "TP333333", early)            # a different bus

# ---------- late notice ----------
n = bus.notify_delay(trip, "traffic", 10, t("17:05"))
check("late notice reaches the 3 people on this bus", n == 3)
check("message says late, minutes, reason and plate",
      all(x in msgs(bus, "TP111111")[-1] for x in ("late", "10 minutes", "traffic", bus.trips[trip]["plate"])))
check("the message has a time stamp", msgs(bus, "TP111111")[-1].startswith("[17:05]"))
check("a person on another bus gets nothing", msgs(bus, "TP333333") == [])
check("the bus shows a notice for passengers", "late" in bus.trips[trip]["notice"].lower())

# ---------- 'almost there' ----------
bus.notify_arriving(trip, 5, t("17:12"))
check("'I will be there in 5 minutes' message",
      "5 minutes" in msgs(bus, "LEC-ONE")[-1] and "waiting area" in msgs(bus, "LEC-ONE")[-1])

# ---------- breakdown ----------
original_plate = bus.trips[trip]["plate"]
inc = bus.report_breakdown(trip, t("17:15"))
check("breakdown creates a request for the logistics team",
      inc is not None and inc["status"] == "open" and inc["passengers"] == 3)
check("passengers are told about the mechanical failure and the plate",
      "mechanical failure" in msgs(bus, "TP222222")[-1] and original_plate in msgs(bus, "TP222222")[-1])
check("reporting twice does not create a second request", bus.report_breakdown(trip, t("17:16")) is None)
check("a spare bus is available", bus.available_spares() == SPARE_BUSES)

# ---------- backup bus ----------
ok = bus.assign_backup(inc["id"], "BACKUP 2001", t("17:20"))
check("logistics assigns a backup bus", ok and inc["status"] == "assigned")
check("the trip now has the NEW plate", bus.trips[trip]["plate"] == "BACKUP 2001")
check("passengers are told the new plate", "BACKUP 2001" in msgs(bus, "TP111111")[-1])
check("that spare bus is no longer available", "BACKUP 2001" not in bus.available_spares())
check("the same request cannot be assigned twice", not bus.assign_backup(inc["id"], "BACKUP 2002", t("17:21")))

# old bookings still work (QR does not depend on the plate)
b = [x for x in bus.bookings if x["person"] == "TP111111"][0]
check("QR scan still works after the plate changed", bus.scan(bus.qr_text(b), trip, t("17:25"))[0])

# ---------- after departure ----------
bus.depart_trip(trip, t("17:40"))
check("notice is cleared when the bus leaves", bus.trips[trip]["notice"] == "")
check("no notices can be sent after the bus left",
      bus.notify_delay(trip, "traffic", 5, t("17:41")) is None and bus.report_breakdown(trip, t("17:41")) is None)
check("the spare bus is free again after the trip", "BACKUP 2001" in bus.available_spares())
check("journey-started message uses the backup plate",
      "BACKUP 2001" in msgs(bus, "TP111111")[-1])

# ---------- sample passengers are messaged too (every ID can be tested) ----------
bus2 = BusSystem()
from bus_logic import add_sample_bookings
add_sample_bookings(bus2)
before = len(bus2.notifications)
people = [b for b in bus2._active_passengers("APU-LRT@17:30")]
n = bus2.notify_delay("APU-LRT@17:30", "traffic", 10, t("17:00"))
check("every passenger on the bus is messaged, simulated ones too", n == len(people) and n > 0
      and len(bus2.notifications) - before == n)
sample = [b for b in people if b.get("sample")][0]
check("a simulated passenger has the message in their own list", any("late" in x for x in msgs(bus2, sample["person"])))

print("\nAll driver-notice tests passed.")
