"""Welcome messages posted in each new session group.

Templates use {placeholders}. Their values are guessed from the poll option
text (date, time, place) and remembered per place (MRT, short name, meeting
point), and can all be edited on the page before posting.
"""
import re
from datetime import datetime, timedelta

import store

PLACEHOLDERS = {
    "day": "Day of the week, e.g. Friday",
    "date": "e.g. 28 Oct",
    "time": "e.g. 7.30pm-9.30pm",
    "start": "Start time, e.g. 7.30pm",
    "location": "Full place name, e.g. Ground Up",
    "loc_short": "Short place name, e.g. GU",
    "mrt": "Nearest MRT, e.g. NE8 Farrer Park",
    "meet_point": "Where to meet in school, e.g. Bencoolen Exit C",
    "meet_time": "When to meet in school, e.g. 3.30pm",
}

DEFAULTS = {
    "welcome": """HII gang! Thanks for taking the time to join this week recre even though yall have mid terms coming up! Here are some impt info for this {day}'s session!

Date & Location

[{date} {time}] @ {location}

Nearest MRT: ({mrt})

Things to bring

- Bring socks for shoe rentals ($6)!! 🧦
- SMU Student Card
- (Optional) Recommended to trim your finger and toe nails 💅
- (Optional) Wear long pants (easy to move in) to prevent/minimise abrasions👖
- (Optional) A set of clothes to change into 👕👚

SAFETY STUFF:

- Remove hard objects before you start climbing!!
- Fall on both legs then roll onto your back, pls don't fall on your hands/tailbone/one foot
- Look underneath you before you fall, don't fall on anyone!
- Be careful where you stand/walk, don't stand / walk near a wall where people are climbing!
- Let people finish their climb before attempting one near them!
- Remember to take a break and drink water when tired
- Avoid hogging the wall when trying a route!""",
    "meet": "You can either meet us directly at {loc_short} @ {start} or meet in school at {meet_point} @ {meet_time}! We'll be taking the MRT over :)",
    "poll_question": "Meet where!!!",
    "poll_options": "{meet_point} @ {meet_time}\n{loc_short} @ {start}",
}

DEFAULT_MEET_POINT = "Bencoolen Exit C"
MEET_EARLY = timedelta(minutes=30)


def templates():
    saved = store.load_config().get("welcome_templates", {})
    return {k: saved.get(k, v) for k, v in DEFAULTS.items()}


def save_templates(**values):
    store.update_config(welcome_templates={k: values[k] for k in DEFAULTS})


def fill(template, values):
    for k, v in values.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def _parse_time(token, ampm_fallback=None):
    m = re.match(r"(\d{1,2})(?:[.:]?(\d{2}))?\s*(am|pm)?$", token.strip().lower())
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3) or ampm_fallback
    if not ampm or hour > 12 or minute > 59:
        return None
    return datetime(2000, 1, 1, hour % 12 + (12 if ampm == "pm" else 0), minute)


def _fmt(t):
    return f"{t.hour % 12 or 12}.{t.minute:02d}{'am' if t.hour < 12 else 'pm'}"


def guess(option_text, poll_date):
    """Placeholder values from e.g. '28 Oct 730pm-930pm @B+ Aperia w/Darryl'."""
    values = {k: "" for k in PLACEHOLDERS}
    text = option_text.strip()

    date = re.match(r"(\d{1,2})\s*([A-Za-z]{3,9})", text)
    if date:
        values["date"] = f"{date.group(1)} {date.group(2)}"
        for year in (poll_date.year, poll_date.year + 1):
            try:
                d = datetime.strptime(f"{date.group(1)} {date.group(2)[:3]} {year}", "%d %b %Y")
            except ValueError:
                break
            if d.date() >= poll_date.date() - timedelta(days=60):
                values["day"] = d.strftime("%A")
                break

    times = re.search(r"(\d[\d.:]*\s*(?:am|pm)?)\s*-\s*(\d[\d.:]*\s*(?:am|pm))", text, re.I)
    if times:
        end = _parse_time(times.group(2))
        start = _parse_time(times.group(1), "pm" if end and end.hour >= 12 else "am")
        if start and end and start > end and start.hour >= 12:  # "10-12pm" means 10am
            start -= timedelta(hours=12)
        if start and end:
            values["time"] = f"{_fmt(start)}-{_fmt(end)}"
            values["start"] = _fmt(start)
            values["meet_time"] = _fmt(start - MEET_EARLY)

    place = re.search(r"@\s*(.+?)(?:\s+w/.*)?$", text)
    if place:
        values["location"] = place.group(1).strip()

    remembered = store.load_config().get("places", {}).get(values["location"].lower(), {})
    values["mrt"] = remembered.get("mrt", "")
    values["loc_short"] = remembered.get("loc_short", values["location"])
    values["meet_point"] = remembered.get("meet_point") or \
        store.load_config().get("meet_point", DEFAULT_MEET_POINT)
    return values


def remember_place(values):
    """Next time this place comes up, prefill its MRT, short name and meeting point."""
    cfg = store.load_config()
    places = cfg.get("places", {})
    if values.get("location"):
        places[values["location"].lower()] = {
            k: values.get(k, "") for k in ("mrt", "loc_short", "meet_point")}
    store.update_config(places=places, meet_point=values.get("meet_point") or DEFAULT_MEET_POINT)
