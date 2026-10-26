"""Attendance: count how many session groups each person is in.

The group list is every group this app made (from records.json) plus groups the
captain added by hand, minus any they removed. Each group is matched to a
session-date column in the sheet ("27 Aug") by its date.

The club's sheet can't be shared outside SMU, so the app doesn't write to it.
Instead it copies the results, and a script inside the sheet
(static/attendance_sheet.gs, running as the captain) ticks them off.
"""
import json
import re
from datetime import datetime

import store

_DATE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s*([A-Za-z]{3,9})\b", re.I)


def session_date(text):
    """'28 Oct 730pm @B+ Aperia' -> '28 Oct', '4th Sept' -> '4 Sep'; '' if there's no date in it."""
    for m in _DATE.finditer(text or ""):
        try:
            d = datetime.strptime(f"2000 {m.group(1)} {m.group(2)[:3].title()}", "%Y %d %b")  # leap year: 29 Feb is fine
        except ValueError:
            continue
        return f"{d.day} {d.strftime('%b')}"
    return ""


# ---------------------------------------------------------------- group list

def _settings():
    return store.load_config().get("attendance", {})


def _save(**changes):
    s = _settings()
    s.update(changes)
    store.update_config(attendance=s)


def group_key(group_id, basic):
    return f"{'chat' if basic else 'channel'}:{group_id}"


def groups():
    """Groups to count, oldest first: dicts with key, id, basic, title, date, auto."""
    s = _settings()
    hidden, dates = set(s.get("hidden", [])), s.get("dates", {})
    found = {}
    for rec in store.all_records().values():
        if not rec.get("group_id"):
            continue
        key = group_key(rec["group_id"], rec.get("basic"))
        title = rec.get("title") or rec.get("option", "")
        found[key] = {"key": key, "id": rec["group_id"], "basic": bool(rec.get("basic")), "title": title,
                      "auto": True, "sort": rec.get("poll_date", ""),
                      "guess": session_date(rec.get("option", "")) or session_date(title)}
    for g in s.get("added", []):
        key = group_key(g["id"], g.get("basic"))
        found.setdefault(key, {"key": key, "id": g["id"], "basic": bool(g.get("basic")), "title": g["title"],
                               "auto": False, "sort": g.get("date", ""), "guess": session_date(g["title"])})
    rows = [g for k, g in found.items() if k not in hidden]
    for g in rows:
        typed = dates.get(g["key"])
        g["date"] = (session_date(typed) or typed) if typed else g["guess"]  # older saves kept "19th Aug" as typed
    rows.sort(key=lambda g: g["sort"])
    return rows


def add_group(group):
    """group: {id, basic, title, date} from tg.find_group_chat()."""
    s = _settings()
    key = group_key(group["id"], group["basic"])
    added = [g for g in s.get("added", []) if group_key(g["id"], g.get("basic")) != key]
    _save(added=added + [group], hidden=[k for k in s.get("hidden", []) if k != key])


def remove_group(key):
    s = _settings()
    _save(added=[g for g in s.get("added", []) if group_key(g["id"], g.get("basic")) != key],
          hidden=sorted(set(s.get("hidden", [])) | {key}))


def set_dates(dates):
    """{group key: '28 Oct'} typed on the page; blank goes back to the guess."""
    saved = dict(_settings().get("dates", {}))
    for key, text in dates.items():
        text = text.strip()
        if text:
            saved[key] = session_date(text) or text
        else:
            saved.pop(key, None)
    _save(dates=saved)


# ---------------------------------------------------------------- counting

def handle_of(user):
    return getattr(user, "username", None) or ""


def name_of(user):
    return " ".join(p for p in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if p) \
        or "(no name)"


def tally(groups, members):
    """Each person and the groups they're in, most sessions first.

    members: group key -> list of Telegram users in that group.
    """
    people = {}
    for g in groups:
        for u in members.get(g["key"], []):
            p = people.setdefault(u.id, {"id": u.id, "name": name_of(u), "handle": handle_of(u), "groups": []})
            p["groups"].append(g)
    return sorted(people.values(), key=lambda p: (-len(p["groups"]), p["name"].lower()))


def as_tsv(groups, people):
    """The results as tab-separated text, to paste into any spreadsheet."""
    lines = ["\t".join(["Tele Handle", "Name", *(g["date"] or g["title"] for g in groups), "Total"])]
    for p in people:
        mine = {g["key"] for g in p["groups"]}
        lines.append("\t".join([f"@{p['handle']}" if p["handle"] else "(no handle)", p["name"],
                                *("1" if g["key"] in mine else "" for g in groups), str(len(p["groups"]))]))
    return "\n".join(lines)


def full_date(group):
    """'2026-08-19' for a group whose session date is '19 Aug', using the year it was made; '' if unknown."""
    date = session_date(group["date"])
    if not date:
        return ""
    try:
        made = datetime.fromisoformat(group["sort"]) if group.get("sort") else datetime.now()
        day = datetime.strptime(f"2000 {date}", "%Y %d %b").replace(year=made.year)
    except ValueError:
        return ""
    if day.month < made.month - 6:  # a January session from a poll posted in December
        day = day.replace(year=made.year + 1)
    return day.strftime("%Y-%m-%d")


def as_sheet_data(groups, people):
    """What 'Copy for sheet' copies: read by the script in the Google Sheet (static/attendance_sheet.gs)."""
    return json.dumps({
        "app": "recre-attendance",
        "sessions": [{"date": g["date"], "title": g["title"], "day": full_date(g)} for g in groups],
        "people": [{"handle": p["handle"], "name": p["name"],
                    "dates": sorted({g["date"] for g in p["groups"] if g["date"]})} for p in people],
    }, ensure_ascii=False)
