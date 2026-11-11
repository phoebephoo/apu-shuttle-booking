"""
Bus booking logic for the Shuttle Booking project.
Features:
  1. Book / cancel a seat on a trip
  2. Waiting list (first in, first out) with automatic promotion
  3. Red seats for lecturers, released to students 1 hour before departure
  4. QR code check (one booking = one scan)
  5. The DRIVER presses "bus has left": passengers who boarded are told their journey
     started, passengers who did not scan are told they missed the bus
  6. Demand summary (booked / waiting / no-show per trip)
"""
import csv
import hashlib
import hmac

# ---- Settings (assumptions, easy to change) ----
CAPACITY = 40            # assumption: seats in one bus
RED_SEATS = 4            # seats reserved for lecturers
RELEASE_MINUTES = 60     # unused red seats open to students this long before departure
BOOKING_GRACE_MINUTES = None  # None = bookings stay open until the bus leaves (the agreed logic).
                         # A number (e.g. 0) would close NEW bookings that many minutes after the scheduled time.
AUTO_CLOSE_MINUTES = 30  # safety net: a bus is closed this long after its scheduled time
                         # if the driver forgot to press "bus has left"
TRIP_MINUTES = 15        # assumption: how long the (simulated) trip between the two stops takes
APPROACH_MINUTES = 8     # assumption: how long a bus needs to reach the waiting area (simulation)
BACKUP_ARRIVAL_MINUTES = 10   # assumption: a backup bus reaches the waiting area this fast
SECRET_KEY = b"demo-secret-key"   # used to sign QR codes (prototype only)

# SAMPLE plate numbers (made up). A "plate" column in bus_trips.csv overrides them.
FLEET = ["DEMO 1001", "DEMO 1002", "DEMO 1003", "DEMO 1004", "DEMO 1005", "DEMO 1006"]

# Reasons the driver can pick (a drop-down: drivers cannot type while driving)
DELAY_REASONS = ["traffic", "road works", "bad weather", "an accident ahead"]
# SAMPLE backup buses the logistics team can send (made-up plates)
SPARE_BUSES = ["BACKUP 2001", "BACKUP 2002", "BACKUP 2003"]

# ID formats:  student TP + 6 digits | lecturer LEC- + 4 digits | driver DRV- + 4 digits
#              staff STAFF- + 4 digits | logistics LOG- + 4 digits
# Made-up demo IDs. Do not use the IDs of real students in the demo.
DEMO_STUDENT = "TP999001"
DEMO_LECTURER = "LEC-1001"
DEMO_DRIVER = "DRV-1001"
DEMO_STAFF = "STAFF-1001"
DEMO_LOGISTICS = "LOG-1001"
# Which driver drives which bus (made-up). DRV-1001 drives DEMO 1006, as agreed.
DRIVER_PLATES = {
    "DRV-1001": "DEMO 1006", "DRV-1002": "DEMO 1001", "DRV-1003": "DEMO 1002",
    "DRV-1004": "DEMO 1003", "DRV-1005": "DEMO 1004", "DRV-1006": "DEMO 1005",
    "DRV-2001": "BACKUP 2001", "DRV-2002": "BACKUP 2002", "DRV-2003": "BACKUP 2003",
}
WAIT_S1, WAIT_S2, WAIT_S3 = "TP999011", "TP999012", "TP999013"


def to_minutes(time_text):
    """'17:30' -> 1050 minutes from midnight."""
    hours, minutes = time_text.strip().split(":")
    return int(hours) * 60 + int(minutes)


def to_text(total_minutes):
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


class BusSystem:
    def __init__(self, trips_file="bus_trips.csv", capacity=CAPACITY, red_seats=RED_SEATS):
        self.capacity = capacity
        self.red_seats = red_seats
        self.trips = {}            # trip_id -> trip info
        self.bookings = []         # every booking (a dictionary each)
        self.notifications = []    # messages: (person_id, text)
        self.incidents = []        # breakdowns reported by drivers (for the logistics team)
        self._incident_counter = 0
        self._counter = 0          # gives each booking a number (also the queue order)
        self._load_trips(trips_file)

    # ---------- loading ----------
    def _load_trips(self, filename):
        with open(filename, newline="") as file:
            for row in csv.DictReader(file):
                if not row["route"].strip():
                    continue
                trip_id = f'{row["route"].strip()}@{row["time"].strip()}'
                self.trips[trip_id] = {
                    "id": trip_id,
                    "route": row["route"].strip(),
                    "depart": to_minutes(row["time"]),
                    "source": (row.get("source") or "").strip(),
                    "plate": (row.get("plate") or "").strip(),
                    "left": False,        # becomes True when the driver presses "bus has left"
                    "left_at": None,
                    "notice": "",         # short status the passengers can see (late, breakdown...)
                    "arrival_override": None,   # minute the bus will reach the waiting area (late notice, backup bus)
                    "arrived_at": None,   # minute the driver pressed "arrived at the waiting area"
                    "break_until": None,  # minute a driver break ends
                    "frozen_progress": 1.0,     # where a broken-down bus stands on its approach
                    "completed": False,   # driver pressed "Trip completed"
                    "completed_at": None,
                }
        # trips without a plate in the CSV get a sample plate. We go through ALL trips of both
        # routes in time order and rotate through the fleet, so the same bus is not on two trips at once.
        for i, trip in enumerate(sorted(self.trips.values(), key=lambda t: (t["depart"], t["route"]))):
            if not trip["plate"]:
                trip["plate"] = FLEET[i % len(FLEET)]
        for trip in self.trips.values():
            trip["original_plate"] = trip["plate"]

    # ---------- counting seats ----------
    def _count(self, trip_id, status, role=None):
        return sum(1 for b in self.bookings
                   if b["trip"] == trip_id and b["status"] == status
                   and (role is None or b["role"] == role))

    def _occupied(self, trip_id, role=None):
        """Seats in use: people who booked AND people who already boarded (scanned)."""
        return self._count(trip_id, "booked", role) + self._count(trip_id, "used", role)

    def red_released(self, trip_id, now):
        """True when unused red seats are open to students."""
        return now >= self.trips[trip_id]["depart"] - RELEASE_MINUTES

    def student_capacity(self, trip_id, now):
        """How many seats students may use right now."""
        normal = self.capacity - self.red_seats
        if self.red_released(trip_id, now):
            lecturers = self._occupied(trip_id, "lecturer")
            return normal + (self.red_seats - lecturers)
        return normal

    def seats_left_students(self, trip_id, now):
        return self.student_capacity(trip_id, now) - self._occupied(trip_id, "student")

    def red_seats_left(self, trip_id):
        return self.red_seats - self._occupied(trip_id, "lecturer")

    def waiting_count(self, trip_id):
        return self._count(trip_id, "waiting")

    def has_departed(self, trip_id, now):
        """The bus has left when the driver says so. The clock is only a safety net,
        because buses are often late."""
        trip = self.trips[trip_id]
        return trip["left"] or now >= trip["depart"] + AUTO_CLOSE_MINUTES

    def booking_open(self, trip_id, now):
        """Can someone make a NEW booking (or join the waiting list) on this trip?"""
        trip = self.trips[trip_id]
        if self.has_departed(trip_id, now):
            return False
        if BOOKING_GRACE_MINUTES is None:
            return True
        return now < trip["depart"] + BOOKING_GRACE_MINUTES

    def open_trips(self, route, now):
        """Trips of a route that have not left yet (a late bus stays in the list)."""
        return [t for t in self.trips_for_route(route) if not self.has_departed(t["id"], now)]

    # ---------- booking ----------
    def _student_seat_kind(self, trip_id):
        """Is the next student seat a standard seat or a red seat released to students?"""
        normal = self.capacity - self.red_seats
        if self._occupied(trip_id, "student") >= normal:
            return "red seat (released)"
        return "standard seat"

    def _new_booking(self, trip_id, person, role, status, kind=""):
        self._counter += 1
        booking = {"id": self._counter, "trip": trip_id, "person": person,
                   "role": role, "status": status, "kind": kind}
        self.bookings.append(booking)
        return booking

    def _active(self, trip_id, person):
        """Is this person already booked or waiting on this trip?"""
        return any(b["trip"] == trip_id and b["person"] == person
                   and b["status"] in ("booked", "waiting") for b in self.bookings)

    def book_student(self, trip_id, student_id, now):
        """Returns (booking or None, message)."""
        if self.has_departed(trip_id, now):
            return None, "This bus has already left."
        if not self.booking_open(trip_id, now):
            return None, "Booking for this bus is closed: its scheduled time has passed."
        if self._active(trip_id, student_id):
            return None, "You already have a booking or a waiting place on this trip."
        
        # Check if student already has an active confirmed booking on another bus
        has_other_confirmed = any(
            b["person"] == student_id and b["status"] == "booked" and b["trip"] != trip_id 
            for b in self.bookings
        )

        if self.seats_left_students(trip_id, now) > 0:
            if has_other_confirmed:
                return None, "You can only have one active confirmed bus booking at a time. Please cancel your existing booking first."
            b = self._new_booking(trip_id, student_id, "student", "booked",
                                  self._student_seat_kind(trip_id))
            return b, "Seat booked."
            
        # Joining the waiting list is still allowed even if they have an active booking
        b = self._new_booking(trip_id, student_id, "student", "waiting")
        position = self._waiting_position(b)
        return b, f"Bus is full. You are number {position} on the waiting list."
    
    def _has_other_confirmed_booking(self, person, trip_id):
        """A person may hold only one confirmed seat across all trips."""
        return any(b["person"] == person and b["trip"] != trip_id
                   and b["status"] == "booked" for b in self.bookings)

    def book_lecturer(self, trip_id, lecturer_id, now):
        """Lecturers book red seats or join this trip's shared waiting list."""
        if self.has_departed(trip_id, now):
            return None, "This bus has already left."
        if not self.booking_open(trip_id, now):
            return None, "Booking for this bus is closed: its scheduled time has passed."
        if self._active(trip_id, lecturer_id):
            return None, "You already have a booking or a waiting place on this trip."

        has_other_confirmed = self._has_other_confirmed_booking(lecturer_id, trip_id)
        can_take_red_seat = (self.red_seats_left(trip_id) > 0
                             and self._occupied(trip_id) < self.capacity)
        if can_take_red_seat and not has_other_confirmed:
            b = self._new_booking(trip_id, lecturer_id, "lecturer", "booked", "red seat (lecturer)")
            return b, "Red seat booked."

        # Waiting is allowed even while the person holds a confirmed seat on another trip.
        b = self._new_booking(trip_id, lecturer_id, "lecturer", "waiting")
        position = self._waiting_position(b)
        if has_other_confirmed:
            return b, (f"You already have a confirmed booking on another bus. "
                       f"You are number {position} on this bus's waiting list; cancel your other booking "
                       "before accepting another seat.")
        return b, f"No red seat is available. You are number {position} on the waiting list."

    # ---------- waiting list ----------
    def _waiting_position(self, booking):
        queue = [b for b in self.bookings
                 if b["trip"] == booking["trip"] and b["status"] == "waiting"]
        # Lecturer priority applies to the red-seat queue; FIFO within each role.
        queue.sort(key=lambda b: (0 if b["role"] == "lecturer" else 1, b["id"]))
        return queue.index(booking) + 1

    def promote_waiting(self, trip_id, now, released_red_seat=False):
        """Promote lecturers to vacant red seats first, then students to eligible seats.

        A red seat explicitly cancelled by a lecturer can pass immediately to a student
        when no lecturer is waiting, even before the normal one-hour release time.
        """
        promoted = []
        while not self.has_departed(trip_id, now):
            waiting = [b for b in self.bookings
                       if b["trip"] == trip_id and b["status"] == "waiting"]
            if not waiting:
                break

            # A released lecturer red seat always goes to the earliest waiting lecturer first.
            lecturer_queue = sorted((b for b in waiting if b["role"] == "lecturer"),
                                    key=lambda b: b["id"])
            if (lecturer_queue and self.red_seats_left(trip_id) > 0
                    and self._occupied(trip_id) < self.capacity):
                first = lecturer_queue[0]
                seat_kind = "red seat (lecturer)"
            else:
                # If no lecturer is waiting for a red seat, use the ordinary student queue.
                student_queue = sorted((b for b in waiting if b["role"] == "student"),
                                       key=lambda b: b["id"])
                student_seats_available = self.seats_left_students(trip_id, now)
                if released_red_seat and self._occupied(trip_id) < self.capacity:
                    student_seats_available = max(student_seats_available, 1)
                if not student_queue or student_seats_available <= 0:
                    break
                first = student_queue[0]
                # The released red seat is now eligible for a student, even before the
                # normal one-hour opening window, because a lecturer explicitly freed it.
                released_red_seat = False
                seat_kind = self._student_seat_kind(trip_id)

            # Enforce one confirmed booking across trips. A waiting-list promotion
            # replaces the person's older confirmed booking, with an explicit notice.
            other_active = next(
                (b for b in self.bookings if b["person"] == first["person"]
                 and b["status"] == "booked" and b["trip"] != trip_id), None)
            if other_active:
                other_active["status"] = "cancelled"
                other_trip_time = to_text(self.trips[other_active["trip"]]["depart"])
                self.notifications.append(
                    (first["person"],
                     f"Your booking for the {other_trip_time} bus was automatically cancelled because "
                     f"you received a seat from the waiting list for the "
                     f"{to_text(self.trips[trip_id]['depart'])} bus.")
                )

            first["kind"] = seat_kind
            first["status"] = "booked"
            promoted.append(first)
            self.notifications.append(
                (first["person"],
                 f"A seat is now yours on the {to_text(self.trips[trip_id]['depart'])} bus "
                 f"(plate {self.trips[trip_id]['plate']}).")
            )
        return promoted

    def refresh(self, now):
        """Call this when time moves on: ends finished driver breaks, releases red seats, promotes the queue."""
        for trip_id, trip in self.trips.items():
            if trip["break_until"] is not None and now >= trip["break_until"] and not trip["left"]:
                trip["break_until"] = None
                trip["notice"] = ""
                self._tell_all(trip_id, f"The driver break is over. Boarding at the waiting area now "
                                        f"(plate {trip['plate']}).", now)
        for trip_id in self.trips:
            if not self.has_departed(trip_id, now):
                self.promote_waiting(trip_id, now)

    # ---------- cancelling ----------
    def cancel(self, booking_id, now):
        for b in self.bookings:
            if b["id"] == booking_id and b["status"] in ("booked", "waiting"):
                if self.has_departed(b["trip"], now):
                    return False, "This bus has already left."
                b["status"] = "cancelled"
                self.promote_waiting(b["trip"], now, released_red_seat=(b["role"] == "lecturer" and b["kind"] == "red seat (lecturer)"))
                return True, "Booking cancelled."
        return False, "Booking not found."

    # ---------- QR code ----------
    def qr_text(self, booking):
        """The text stored inside the QR code. The signature stops fake codes."""
        body = f'{booking["id"]}|{booking["trip"]}'
        signature = hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).hexdigest()[:10]
        return f"{body}|{signature}"

    def scan(self, code, trip_id, now):
        """What the driver's device does. Returns (ok, message)."""
        if self.has_departed(trip_id, now):
            return False, "This bus has already left."
        parts = code.split("|")
        if len(parts) != 3:
            return False, "Not a valid code."
        booking_id, code_trip, signature = parts
        body = f"{booking_id}|{code_trip}"
        expected = hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).hexdigest()[:10]
        if not hmac.compare_digest(signature, expected):
            return False, "Fake or changed code."
        if code_trip != trip_id:
            return False, "Wrong bus: this code is for another trip."
        for b in self.bookings:
            if str(b["id"]) == booking_id:
                if b["status"] == "used":
                    return False, "Code already used."
                if b["status"] != "booked":
                    return False, f'Booking is {b["status"]}.'
                b["status"] = "used"
                if not b.get("boarding_source"):
                    b["boarding_source"] = "qr_scan"
                return True, f'Welcome on board, {b["person"]} ({b["role"]}).'
        return False, "Booking not found."

    # ---------- the bus leaves ----------
    def depart_trip(self, trip_id, now):
        """The driver presses "bus has left". Everyone on this trip gets a message:
        boarded -> journey started, not scanned -> missed the bus, waiting -> no seat.
        Returns the counts, or None if the bus was already closed."""
        trip = self.trips[trip_id]
        if trip["left"]:
            return None
        trip["left"] = True
        trip["left_at"] = now
        trip["notice"] = ""
        trip["break_until"] = None
        if trip["arrived_at"] is None:
            trip["arrived_at"] = now
        depart = to_text(trip["depart"])
        plate = trip["plate"]
        counts = {"boarded": 0, "missed": 0, "waiting": 0}

        for b in self.bookings:
            if b["trip"] != trip_id:
                continue
            tell = True                                 # everyone on the bus gets a message
            if b["status"] == "booked" and b.get("sim_show"):
                b["status"] = "used"                    # demo only: simulated people who did show up
                b["boarding_source"] = "simulated"
            if b["status"] == "used":
                counts["boarded"] += 1
                if tell:
                    self.notifications.append(
                        (b["person"], f"Your journey has started on the {depart} bus (plate {plate}). Have a safe trip."))
            elif b["status"] == "booked":
                b["status"] = "no_show"
                counts["missed"] += 1
                if tell:
                    tag = " (red seat)" if b["role"] == "lecturer" else ""
                    self.notifications.append(
                        (b["person"], f"You missed your {depart} bus{tag}. Please book another trip."))
            elif b["status"] == "waiting":
                b["status"] = "expired"
                counts["waiting"] += 1
                if tell:
                    self.notifications.append(
                        (b["person"], f"You did not get a seat on the {depart} bus. Please try another trip."))
        return counts

    def close_departed_trips(self, now):
        """Safety net: close buses whose scheduled time passed long ago and the driver never confirmed."""
        for trip_id, trip in self.trips.items():
            if not trip["left"] and now >= trip["depart"] + AUTO_CLOSE_MINUTES:
                self.depart_trip(trip_id, now)
                trip["left_at"] = trip["depart"]      # unknown: assume it left on time
                trip["completed"] = True               # history, not a trip the driver still has to close
                trip["completed_at"] = now

    # ---------- data for the university ----------
    def demand_summary(self):
        """Rows: one per trip, with counts. Useful to decide where to add buses."""
        rows = []
        for trip_id in self.trips:
            rows.append({
                "trip": trip_id,
                "booked": self._count(trip_id, "booked") + self._count(trip_id, "used"),
                "waiting": self._count(trip_id, "waiting") + self._count(trip_id, "expired"),
                "no_show": self._count(trip_id, "no_show"),
            })
        return rows

    # ---------- driver notices, breakdowns and backup buses ----------
    def _active_passengers(self, trip_id):
        return [b for b in self.bookings
                if b["trip"] == trip_id and b["status"] in ("booked", "used", "waiting")]

    def _tell_all(self, trip_id, text, now):
        """Send a message to everyone on the trip."""
        people = self._active_passengers(trip_id)
        for b in people:
            self.notifications.append((b["person"], f"[{to_text(now)}] {text}"))
        return len(people)

    def notify_delay(self, trip_id, reason, minutes, now):
        """Driver: 'the bus is coming but will be late'. Returns how many people were told."""
        trip = self.trips[trip_id]
        if trip["left"] or self.at_waiting_area(trip_id, now):
            return None
        trip["arrival_override"] = trip["depart"] + minutes
        trip["notice"] = f"Running late (about {minutes} min) due to {reason}"
        return self._tell_all(
            trip_id,
            f"Your {to_text(trip['depart'])} bus (plate {trip['plate']}) is coming but will be late, "
            f"about {minutes} minutes, due to {reason}.", now)

    def notify_arriving(self, trip_id, minutes, now):
        """Driver: 'I will be there in a few minutes, please wait at the waiting area'."""
        trip = self.trips[trip_id]
        if trip["left"] or self.at_waiting_area(trip_id, now):
            return None
        trip["arrival_override"] = now + minutes
        trip["notice"] = f"Driver is about {minutes} min away"
        return self._tell_all(
            trip_id,
            f"I am your driver. I will be there in {minutes} minutes. Please wait at the waiting area. "
            f"(Bus plate {trip['plate']})", now)

    def report_breakdown(self, trip_id, now):
        """Driver: mechanical failure. Tells the passengers and opens a request for the logistics team.
        Returns the incident, or None (bus already left, or a request is already open)."""
        trip = self.trips[trip_id]
        if trip["left"]:
            return None
        if any(i["trip"] == trip_id and i["status"] == "open" for i in self.incidents):
            return None
        trip["frozen_progress"] = 1.0 if self.at_waiting_area(trip_id, now) else self._approach_progress(trip_id, now)
        self._incident_counter += 1
        incident = {
            "id": self._incident_counter, "trip": trip_id, "status": "open",
            "plate": trip["plate"], "created": now,
            "passengers": len(self._active_passengers(trip_id)),
            "backup_plate": "", "assigned_at": None,
        }
        self.incidents.append(incident)
        trip["notice"] = "Mechanical failure: backup bus requested"
        self._tell_all(
            trip_id,
            f"Due to a mechanical failure, your {to_text(trip['depart'])} bus (plate {trip['plate']}) "
            "will not arrive on time. We will assign you a backup bus in a short time.", now)
        return incident

    def available_spares(self):
        """Backup buses that are not already working a trip that has not left."""
        busy = {i["backup_plate"] for i in self.incidents
                if i["status"] == "assigned" and not self.trips[i["trip"]]["left"]}
        return [p for p in SPARE_BUSES if p not in busy]

    def assign_backup(self, incident_id, backup_plate, now):
        """Logistics team: send a backup bus. The trip gets the new plate and everyone is told."""
        for incident in self.incidents:
            if incident["id"] == incident_id and incident["status"] == "open":
                trip = self.trips[incident["trip"]]
                incident["status"] = "assigned"
                incident["backup_plate"] = backup_plate
                incident["assigned_at"] = now
                trip["plate"] = backup_plate
                trip["arrival_override"] = now + BACKUP_ARRIVAL_MINUTES    # the backup bus drives to the stop
                trip["arrived_at"] = None
                trip["break_until"] = None
                trip["notice"] = f"Backup bus assigned: new plate {backup_plate}"
                self._tell_all(
                    incident["trip"],
                    f"A backup bus has been assigned for your {to_text(trip['depart'])} trip. "
                    f"New bus plate: {backup_plate}. Please check the plate before you board.", now)
                return True
        return False

    # ---------- simulated bus position and driver actions ----------
    def _open_incident(self, trip_id):
        return any(i["trip"] == trip_id and i["status"] == "open" for i in self.incidents)

    def expected_arrival(self, trip_id):
        """Minute when the bus is expected at the waiting area."""
        trip = self.trips[trip_id]
        return trip["arrival_override"] if trip["arrival_override"] is not None else trip["depart"]

    def at_waiting_area(self, trip_id, now):
        """True only after the driver confirmed the arrival (a real version: the bus GPS).
        The clock alone never puts a bus at the stop: a late bus is simply late."""
        trip = self.trips[trip_id]
        return (not trip["left"]) and trip["arrived_at"] is not None

    def _approach_progress(self, trip_id, now):
        left = self.expected_arrival(trip_id) - now
        return max(0.0, min(1.0, 1 - left / APPROACH_MINUTES))

    def bus_state(self, trip_id, now):
        """Where the bus is and what to tell passengers. THE POSITION IS SIMULATED from the
        schedule and the driver's buttons. A real version would read the bus GPS."""
        trip = self.trips[trip_id]
        state = {"phase": "", "segment": "approach", "progress": 0.0, "eta_min": None,
                 "resume": None, "late": False, "text": "", "updated": now}
        if trip["completed"]:
            state.update(phase="completed", segment="trip", progress=1.0, text="Trip completed")
        elif trip["left"]:
            elapsed = max(0, now - trip["left_at"])
            if elapsed >= TRIP_MINUTES:
                state.update(phase="arrived", segment="trip", progress=1.0, text="Arrived at the destination")
            else:
                state.update(phase="on_the_way", segment="trip", progress=elapsed / TRIP_MINUTES,
                             eta_min=max(1, round(TRIP_MINUTES - elapsed)), text="On the way")
        elif trip["break_until"] is not None and now < trip["break_until"]:
            state.update(phase="on_break", progress=1.0, resume=trip["break_until"],
                         text="Parked at the waiting area: driver break")
        elif self._open_incident(trip_id):
            state.update(phase="breakdown", progress=trip["frozen_progress"],
                         text="Mechanical failure: backup bus requested")
        elif self.at_waiting_area(trip_id, now):
            state.update(phase="at_stop", progress=1.0, text="At the waiting area")
        else:
            expected = self.expected_arrival(trip_id)
            wait = expected - now
            late = now > expected
            # the bus drives towards the stop but never reaches it until the driver confirms
            state.update(phase="approaching", progress=min(0.92, self._approach_progress(trip_id, now)),
                         eta_min=int(wait + 0.999) if wait >= 1 else None, late=late,
                         text="Late: not arrived yet" if late else "On its way to the waiting area")
        return state

    def mark_arrived(self, trip_id, now):
        """Driver: 'the bus has arrived at the waiting area'."""
        trip = self.trips[trip_id]
        if trip["left"] or self._open_incident(trip_id):
            return None
        trip["arrived_at"] = now
        trip["notice"] = "The bus is at the waiting area"
        return self._tell_all(
            trip_id, f"Your {to_text(trip['depart'])} bus (plate {trip['plate']}) has arrived at the waiting area. "
                     "Please check the plate before you board.", now)

    def start_break(self, trip_id, minutes, now):
        """Driver: short break (for example lunch) while the bus is parked at the waiting area."""
        trip = self.trips[trip_id]
        if trip["left"] or self._open_incident(trip_id) or not self.at_waiting_area(trip_id, now):
            return None
        if trip["arrived_at"] is None:
            trip["arrived_at"] = now
        trip["break_until"] = now + minutes
        trip["notice"] = f"Driver break: boarding resumes about {to_text(now + minutes)}"
        return self._tell_all(
            trip_id, f"Your {to_text(trip['depart'])} bus (plate {trip['plate']}) is at the waiting area, but the "
                     f"driver is on a short break. Boarding resumes at about {to_text(now + minutes)}.", now)

    def end_break(self, trip_id, now):
        trip = self.trips[trip_id]
        if trip["break_until"] is None or trip["left"]:
            return None
        trip["break_until"] = None
        trip["notice"] = "The bus is at the waiting area"
        return self._tell_all(
            trip_id, f"The driver break is over. Boarding at the waiting area now (plate {trip['plate']}).", now)

    def complete_trip(self, trip_id, now):
        """Driver: 'the trip has completed'. Passengers who boarded are thanked."""
        trip = self.trips[trip_id]
        if not trip["left"] or trip["completed"]:
            return None
        trip["completed"] = True
        trip["completed_at"] = now
        trip["notice"] = ""
        people = [b for b in self.bookings if b["trip"] == trip_id and b["status"] == "used"]
        for b in people:
            self.notifications.append(
                (b["person"], f"[{to_text(now)}] Your trip has completed ({to_text(trip['depart'])} bus, "
                              f"plate {trip['plate']}). Thank you for riding with us."))
        return len(people)

    # ---------- helpers for the app ----------
    def bookings_of(self, person):
        return [b for b in self.bookings if b["person"] == person]

    def waiting_position(self, booking):
        return self._waiting_position(booking)

    def active_booking(self, trip_id, person):
        """The person's booked/waiting booking on this trip, or None."""
        for b in self.bookings:
            if b["trip"] == trip_id and b["person"] == person and b["status"] in ("booked", "waiting"):
                return b
        return None

    def driver_trips(self, plate, now):
        """The trips (not left yet) that this bus has to drive, in time order."""
        result = []
        for t in self.trips.values():
            if t["plate"] != plate:
                continue
            running = t["left"] and not t["completed"] and now <= t["left_at"] + 120
            if running or not self.has_departed(t["id"], now):
                result.append(t)
        return sorted(result, key=lambda t: (t["depart"], t["route"]))

    def is_sample_person(self, person_id):
        """True if this ID belongs to a simulated sample passenger."""
        return any(b["person"] == person_id and b.get("sample") for b in self.bookings)

    def trips_for_route(self, route):
        return sorted((t for t in self.trips.values() if t["route"] == route),
                      key=lambda t: t["depart"])


def add_sample_bookings(bus, seed=7):
    """DEMO ONLY: fill busy trips with simulated bookings so the problem is visible.
    Busy times: morning LRT->APU, early afternoon, and evening. These people are marked
    sample=True, use made-up IDs (students TP9xxxxx, lecturers LEC-5xxx / LEC-6xxx) and get no messages."""
    import random
    rng = random.Random(seed)
    early = 6 * 60                       # book "in the morning" so every trip is still open
    student_seats = bus.capacity - bus.red_seats
    n = 0
    lec_n = 0
    for trip_id, trip in bus.trips.items():
        m = trip["depart"]
        if trip["route"] == "LRT-APU" and 450 <= m <= 540:
            level = rng.uniform(0.95, 1.1)
        elif 840 <= m <= 930:
            level = rng.uniform(0.8, 1.0)
        elif 1020 <= m <= 1140:
            level = rng.uniform(0.95, 1.2)
        else:
            level = rng.uniform(0.1, 0.45)
        for _ in range(int(level * student_seats)):
            n += 1
            b, _msg = bus.book_student(trip_id, f"TP9{n:05d}", early)
            if b:
                b["sample"] = True
                b["sim_show"] = rng.random() < 0.9      # 10% will be no-shows
        for _ in range(rng.randint(0, 3)):              # some lecturers book red seats
            lec_n += 1
            b, _msg = bus.book_lecturer(trip_id, f"LEC-{5000 + lec_n}", early)
            if b:
                b["sample"] = True
                b["sim_show"] = rng.random() < 0.85
    return bus


def setup_waiting_list_demo(bus, now):
    """DEMO ONLY: one full APU->LRT bus to show the waiting list.
    WAIT_S1 holds the last seat; WAIT_S2 is waiting number 1; WAIT_S3 is number 2.
    Returns the trip id (or None if no bus is left today)."""
    upcoming = [t for t in bus.open_trips("APU-LRT", now) if t["depart"] > now + 5]
    if not upcoming:
        return None
    trip_id = upcoming[0]["id"]
    bus.bookings = [b for b in bus.bookings if b["trip"] != trip_id]     # clean start for this bus
    for i in range(bus.red_seats):                                        # red seats taken by lecturers
        b, _ = bus.book_lecturer(trip_id, f"LEC-{6001 + i}", now)
        if b:
            b["sample"] = True
            b["sim_show"] = True
    for i in range(bus.capacity - bus.red_seats - 1):                     # students fill the standard seats
        b, _ = bus.book_student(trip_id, f"TP98{i + 1:04d}", now)
        if b:
            b["sample"] = True
            b["sim_show"] = True
    bus.book_student(trip_id, WAIT_S1, now)                               # the last seat
    bus.book_student(trip_id, WAIT_S2, now)                               # waiting #1
    bus.book_student(trip_id, WAIT_S3, now)                               # waiting #2
    return trip_id
