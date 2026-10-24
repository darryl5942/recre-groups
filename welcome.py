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
    "map_link": "Google Maps link (optional): makes the place name clickable",
    "loc_short": "Short place name, e.g. GU",
    "mrt": "Nearest MRT, e.g. NE8 Farrer Park",
    "meet_point": "Where to meet in school, e.g. Bencoolen Exit C",
    "meet_time": "When to meet in school, e.g. 3.30pm",
}

# Shown in any box that couldn't be worked out, so the messages always read
# sensibly. Marked on the page as examples to replace.
EXAMPLES = {
    "day": "Friday",
    "date": "28 Oct",
    "time": "4.00pm-6.00pm",
    "start": "4.00pm",
    "location": "Ground Up",
    "loc_short": "GU",
    "mrt": "NE8 Farrer Park",
    "meet_point": "Bencoolen Exit C",
    "meet_time": "3.30pm",
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

OPTIONAL = {"map_link"}  # fine to leave empty

DEFAULT_MEET_POINT = "Bencoolen Exit C"
_LINK = re.compile(r"\[([^\[\]\n]+)\]\((https?://[^\s()]+)\)")  # [text](https://...)
MEET_EARLY = timedelta(minutes=30)


def templates():
    saved = store.load_config().get("welcome_templates", {})
    return {k: saved.get(k, v) for k, v in DEFAULTS.items()}


def save_templates(**values):
    current = templates()
    store.update_config(welcome_templates={k: values.get(k, current[k]) for k in DEFAULTS})


def is_link(url):
    return bool(re.match(r"https?://\S+$", (url or "").strip()))


def fill(template, values):
    """Put the session details into a template. With a map link, the location
    becomes [Ground Up](https://...), which is sent as a clickable link."""
    values = dict(values)
    if is_link(values.get("map_link")) and values.get("location"):
        values["location"] = f"[{values['location']}]({values['map_link'].strip()})"
    for k, v in values.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def _utf16_len(text):
    return len(text.encode("utf-16-le")) // 2  # Telegram counts emoji as 2


def parse_links(text):
    """'[Ground Up](https://...)' -> ('Ground Up', [(offset, length, url)]).

    Only this link form is special; everything else is sent exactly as typed.
    Offsets are in UTF-16 units, as Telegram expects.
    """
    plain, links, last = [], [], 0
    for m in _LINK.finditer(text):
        plain.append(text[last:m.start()])
        offset = _utf16_len("".join(plain))
        plain.append(m.group(1))
        links.append((offset, _utf16_len(m.group(1)), m.group(2)))
        last = m.end()
    plain.append(text[last:])
    return "".join(plain), links


def strip_links(text):
    """Polls can't contain links: keep just the link text."""
    return _LINK.sub(lambda m: m.group(1), text)


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
    values["map_link"] = remembered.get("map_link", "")
    values["loc_short"] = remembered.get("loc_short", values["location"])
    values["meet_point"] = remembered.get("meet_point") or \
        store.load_config().get("meet_point", DEFAULT_MEET_POINT)
    return values


def with_examples(values):
    """Fill empty boxes with example values; returns (values, names of boxes that are examples)."""
    filled, examples = dict(values), []
    for k, example in EXAMPLES.items():
        if not filled.get(k, "").strip():
            filled[k] = example
            examples.append(k)
    return filled, examples


def remember_place(values):
    """Next time this place comes up, prefill its MRT, short name and meeting point."""
    cfg = store.load_config()
    places = cfg.get("places", {})
    if values.get("location"):
        places[values["location"].lower()] = {
            k: values.get(k, "") for k in ("mrt", "loc_short", "meet_point", "map_link")}
    store.update_config(places=places, meet_point=values.get("meet_point") or DEFAULT_MEET_POINT)
