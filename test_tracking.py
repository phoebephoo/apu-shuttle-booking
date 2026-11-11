"""Tests for the simulated bus position, driver break, arrival and trip completed:
run with  python3 test_tracking.py"""
from bus_logic import BusSystem, to_minutes as t, TRIP_MINUTES, APPROACH_MINUTES

def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    assert cond, name

def msgs(bus, who):
    return [text for w, text in bus.notifications if w == who]

def fresh():
    bus = BusSystem()
    trip = "APU-LRT@17:10"
    bus.book_student(trip, "TP111111", t("15:00"))
    bus.book_student(trip, "TP222222", t("15:00"))
    return bus, trip

# ---------- approaching and arriving ----------
bus, trip = fresh()
s = bus.bus_state(trip, t("17:00"))
check("10 min before: bus is far away, ETA 10 min", s["phase"] == "approaching" and s["eta_min"] == 10 and s["progress"] == 0.0)
s = bus.bus_state(trip, t("17:06"))
check("closer: ETA 4 min, bus has moved", s["phase"] == "approaching" and s["eta_min"] == 4 and 0.4 < s["progress"] < 0.6)
check("the bus moves forward as time passes",
      bus.bus_state(trip, t("17:08"))["progress"] > bus.bus_state(trip, t("17:06"))["progress"])
s = bus.bus_state(trip, t("17:10"))
check("at the scheduled time the bus is only ARRIVING (the driver has not confirmed)",
      s["phase"] == "approaching" and s["eta_min"] is None and not s["late"])
s = bus.bus_state(trip, t("17:40"))
check("a bus that has not arrived is LATE and never 'here': the clock alone does not put it at the stop",
      s["phase"] == "approaching" and s["late"] and s["progress"] <= 0.92)

# ---------- late notice moves the arrival ----------
bus, trip = fresh()
bus.notify_delay(trip, "traffic", 10, t("17:00"))
check("late notice: not at the stop at 17:12", bus.bus_state(trip, t("17:12"))["phase"] == "approaching")
check("late notice: ETA now counts to 17:20", bus.bus_state(trip, t("17:12"))["eta_min"] == 8)
check("late notice: at 17:20 it is only arriving until the driver confirms", bus.bus_state(trip, t("17:20"))["phase"] == "approaching")
bus.mark_arrived(trip, t("17:21"))
check("after the driver confirms, the bus is at the stop", bus.bus_state(trip, t("17:21"))["phase"] == "at_stop")
check("a late notice is refused when the bus has already arrived", bus.notify_delay(trip, "traffic", 5, t("17:22")) is None)

# ---------- driver confirms arrival ----------
bus, trip = fresh()
n = bus.mark_arrived(trip, t("17:04"))
check("driver confirms arrival: passengers told", n == 2 and "has arrived" in msgs(bus, "TP111111")[-1])
check("after confirming, the bus is at the stop even before the scheduled time", bus.bus_state(trip, t("17:05"))["phase"] == "at_stop")

# ---------- lunch break ----------
bus, trip = fresh()
check("a break is refused while the bus is still on its way", bus.start_break(trip, 20, t("17:00")) is None)
bus.mark_arrived(trip, t("17:10"))
n = bus.start_break(trip, 20, t("17:10"))
check("a break at the waiting area tells the passengers", n == 2 and "short break" in msgs(bus, "TP111111")[-1])
s = bus.bus_state(trip, t("17:20"))
check("during the break the bus is parked: no movement, no ETA",
      s["phase"] == "on_break" and s["progress"] == 1.0 and s["eta_min"] is None and s["resume"] == t("17:30"))
check("the passengers see a notice with the time", "17:30" in bus.trips[trip]["notice"])
bus.refresh(t("17:25"))
check("break still running at 17:25", bus.trips[trip]["break_until"] is not None)
bus.refresh(t("17:30"))
check("break ends by itself at 17:30 and passengers are told", bus.trips[trip]["break_until"] is None
      and "break is over" in msgs(bus, "TP111111")[-1])
check("after the break the bus is at the stop again", bus.bus_state(trip, t("17:31"))["phase"] == "at_stop")

bus, trip = fresh()
bus.mark_arrived(trip, t("17:10"))
bus.start_break(trip, 30, t("17:10"))
check("driver can end the break early", bus.end_break(trip, t("17:15")) == 2 and bus.bus_state(trip, t("17:16"))["phase"] == "at_stop")

# ---------- leaving, riding, arriving, completing ----------
bus, trip = fresh()
b1 = [b for b in bus.bookings if b["person"] == "TP111111"][0]
bus.scan(bus.qr_text(b1), trip, t("17:09"))                          # only TP111111 boards
check("trip cannot be completed before the bus has left", bus.complete_trip(trip, t("17:10")) is None)
bus.depart_trip(trip, t("17:12"))
s = bus.bus_state(trip, t("17:17"))
check("after leaving, the bus travels: 5 of 15 minutes", s["phase"] == "on_the_way" and abs(s["progress"] - 5 / TRIP_MINUTES) < 1e-9 and s["eta_min"] == 10)
check("the trip is still the driver's until it is completed",
      trip in [x["id"] for x in bus.driver_trips(bus.trips[trip]["plate"], t("17:20"))])
check("the simulated bus arrives after the trip time", bus.bus_state(trip, t("17:12") + TRIP_MINUTES)["phase"] == "arrived")
n = bus.complete_trip(trip, t("17:30"))
check("trip completed: only the passenger who boarded gets the message", n == 1
      and "trip has completed" in msgs(bus, "TP111111")[-1]
      and not any("completed" in x for x in msgs(bus, "TP222222")))
check("state is completed", bus.bus_state(trip, t("17:31"))["phase"] == "completed")
check("completing twice does nothing", bus.complete_trip(trip, t("17:32")) is None)
check("a completed trip leaves the driver's list",
      trip not in [x["id"] for x in bus.driver_trips(bus.trips[trip]["plate"], t("17:33"))])

# ---------- breakdown and backup bus ----------
bus, trip = fresh()
bus.report_breakdown(trip, t("17:06"))
s = bus.bus_state(trip, t("17:08"))
frozen = s["progress"]
check("breakdown: the bus stops moving", s["phase"] == "breakdown" and frozen == bus.bus_state(trip, t("17:09"))["progress"])
inc = bus.incidents[0]
bus.assign_backup(inc["id"], "BACKUP 2001", t("17:15"))
s = bus.bus_state(trip, t("17:15"))
check("backup bus assigned: it drives to the stop (ETA 10 min)", s["phase"] == "approaching" and s["eta_min"] == 10)
check("backup bus is only 'late' until the driver confirms it arrived", bus.bus_state(trip, t("17:30"))["late"])
bus.mark_arrived(trip, t("17:30"))
check("backup bus at the stop once confirmed", bus.bus_state(trip, t("17:30"))["phase"] == "at_stop")

# ---------- old trips are history, not the driver's job ----------
bus = BusSystem()
bus.close_departed_trips(t("20:00"))
plate = "DEMO 1006"
mine = bus.driver_trips(plate, t("20:00"))
check("trips closed by the safety net are not shown as running trips",
      all(not x["left"] for x in mine))
print("\nAll tracking tests passed.")
