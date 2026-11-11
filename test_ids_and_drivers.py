"""Tests for ID formats and driver-bus assignment: run with  python3 test_ids_and_drivers.py"""
import re
from bus_logic import (BusSystem, add_sample_bookings, setup_waiting_list_demo, DRIVER_PLATES, FLEET,
                       DEMO_STUDENT, DEMO_LECTURER, DEMO_DRIVER, DEMO_STAFF, DEMO_LOGISTICS, to_minutes as t)

def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    assert cond, name

STUDENT = re.compile(r"TP\d{6}"); LECTURER = re.compile(r"LEC-\d{4}")

bus = BusSystem()
add_sample_bookings(bus)
setup_waiting_list_demo(bus, t("16:00"))
students = {b["person"] for b in bus.bookings if b["role"] == "student"}
lecturers = {b["person"] for b in bus.bookings if b["role"] == "lecturer"}
check("every sample student ID is TP + 6 digits", all(STUDENT.fullmatch(x) for x in students))
check("every sample lecturer ID is LEC- + 4 digits", all(LECTURER.fullmatch(x) for x in lecturers))
check("demo accounts use the same formats",
      STUDENT.fullmatch(DEMO_STUDENT) and LECTURER.fullmatch(DEMO_LECTURER)
      and re.fullmatch(r"DRV-\d{4}", DEMO_DRIVER) and re.fullmatch(r"STAFF-\d{4}", DEMO_STAFF)
      and re.fullmatch(r"LOG-\d{4}", DEMO_LOGISTICS))
check("no demo account clashes with a sample passenger",
      DEMO_STUDENT not in students and DEMO_LECTURER not in lecturers)

check("driver DRV-1001 drives DEMO 1006", DRIVER_PLATES["DRV-1001"] == "DEMO 1006")
check("every fleet bus has a driver", set(FLEET) <= set(DRIVER_PLATES.values()))
check("every driver ID is DRV- + 4 digits", all(re.fullmatch(r"DRV-\d{4}", d) for d in DRIVER_PLATES))

mine = bus.driver_trips("DEMO 1006", t("06:00"))
check("DEMO 1006 has trips", len(mine) > 5)
check("a driver only sees the trips of his own bus", all(x["plate"] == "DEMO 1006" for x in mine))
check("the list is in time order", [x["depart"] for x in mine] == sorted(x["depart"] for x in mine))

# one bus is never on two trips at the same time
seen = {}
clash = False
for trip in bus.trips.values():
    key = (trip["plate"], trip["depart"])
    clash = clash or key in seen
    seen[key] = True
check("no bus is on two trips at the same minute", not clash)
check("all 6 buses are used all day", {x["plate"] for x in bus.trips.values()} == set(FLEET))

# after a breakdown the backup driver gets the trip
tid = mine[0]["id"]
inc = bus.report_breakdown(tid, t("06:30"))
bus.assign_backup(inc["id"], "BACKUP 2001", t("06:35"))
check("backup driver DRV-2001 now sees the trip",
      tid in [x["id"] for x in bus.driver_trips(DRIVER_PLATES["DRV-2001"], t("06:36"))])
check("the broken bus no longer has that trip",
      tid not in [x["id"] for x in bus.driver_trips("DEMO 1006", t("06:36"))])
print("\nAll ID and driver tests passed.")
