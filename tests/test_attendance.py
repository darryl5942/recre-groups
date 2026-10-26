"""Attendance: the group list, counting, and the script that fills in the Google Sheet."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import app as webapp
import attendance
import store
import tg
from conftest import ME, OPT_A, run_option, user

SCRIPT = Path(__file__).resolve().parent.parent / "static" / "attendance_sheet.gs"


class FakeSheet:
    """A tab laid out like the club's attendance sheet; .import_() runs the sheet script on it."""

    def __init__(self, dates=("27 Aug", "29 Aug", "28 Oct", "30 Oct"), rows=6, formulas=None):
        width = 2 + len(dates) + 1
        self.grid = [["Aug-25"] + [""] * (width - 1),
                     ["", "", *dates, ""],
                     ["", "TOTAL PAX", *["0"] * len(dates), ""],
                     ["Tele Handle", "Name", *["Attendance"] * len(dates), "Total Attendance"]]
        self.grid += [[""] * width for _ in range(rows)]
        self.formulas = formulas or {}  # (row, col) -> formula already in the sheet
        self.writes = []

    def import_(self, groups, people):
        formulas = [[self.formulas.get((r, c), "") for c in range(len(row))] for r, row in enumerate(self.grid)]
        data = json.loads(attendance.as_sheet_data(groups, people))
        plan = run_script("planAttendance", self.grid, formulas, data)
        while len(self.grid) < plan["rowsNeeded"]:
            self.grid.append([""] * len(self.grid[0]))
        for u in plan["updates"]:
            self.grid[u["row"]][u["col"]] = str(u["value"]).removeprefix("'")  # Sheets hides the ' (text marker)
            self.writes.append((u["row"], u["col"], u["value"]))
        return plan


class ScriptError(Exception):
    pass


def run_script(fn, *args):
    """Call a function from the sheet script with Node, as Google would."""
    js = ("const m = require(process.argv[1]); const args = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
          f"try {{ console.log(JSON.stringify({{ok: m.{fn}(...args)}})); }}"
          "catch (e) { console.log(JSON.stringify({error: e.message})); }")
    out = subprocess.run(["node", "-e", js, str(SCRIPT)], input=json.dumps(args), capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    res = json.loads(out)
    if "error" in res:
        raise ScriptError(res["error"])
    return res["ok"]


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js to run the sheet script")


def group(key, date, title=None, sort="2026-08-01T00:00:00+00:00"):
    return {"key": key, "title": title or key, "date": date, "sort": sort}


def person(uid, handle, *groups):
    return {"id": uid, "name": f"Climber{uid}", "handle": handle, "groups": list(groups)}

# ---------------------------------------------------------------- dates

@pytest.mark.parametrize("text,date", [
    ("28 Oct 730pm-930pm @B+ Aperia w/Darryl", "28 Oct"),
    ("28 Oct Recre @ B+ Aperia", "28 Oct"),
    ("3 September", "3 Sep"),
    ("WEEK 11 RECRE 30 oct", "30 Oct"),
    ("4pm-6pm @BP TS", ""),
    ("", ""),
])
def test_session_date(text, date):
    assert attendance.session_date(text) == date


# ---------------------------------------------------------------- group list

def test_groups_made_by_the_app_are_listed_automatically(fake):
    r = run_option(fake)
    groups = attendance.groups()
    assert [(g["title"], g["date"], g["auto"]) for g in groups] == [(r["title"], "28 Oct", True)]


def test_add_remove_and_date_override(fake):
    run_option(fake)
    fake.make_group("Bouldering social 2 Nov", members={7, 8})
    attendance.add_group(tg.run(tg.find_group_chat("Bouldering social")))
    assert [g["date"] for g in attendance.groups()] == ["28 Oct", "2 Nov"]

    auto, added = attendance.groups()
    attendance.set_dates({added["key"]: "5 november"})
    assert attendance.groups()[1]["date"] == "5 Nov"
    attendance.set_dates({added["key"]: ""})  # blank goes back to the guess
    assert attendance.groups()[1]["date"] == "2 Nov"

    attendance.remove_group(auto["key"])
    assert [g["key"] for g in attendance.groups()] == [added["key"]]
    attendance.remove_group(added["key"])
    assert attendance.groups() == []


def test_adding_a_non_group_fails(fake):
    with pytest.raises(tg.TgError):
        tg.run(tg.find_group_chat("no such chat"))


# ---------------------------------------------------------------- counting

def test_count_leaves_out_me_and_bots_and_counts_each_group(fake):
    a = fake.make_group("A 27 Aug", members={1, 2, 3})
    b = fake.make_group("B 29 Aug", members={2, 3, 99})
    fake.users[99] = user(99)
    fake.users[99].bot = True
    for g in (a, b):
        attendance.add_group(tg.run(tg.find_group_chat(g.title)))
    groups = attendance.groups()
    members, problems = tg.run(tg.attendance_members(groups))
    assert problems == {}
    people = attendance.tally(groups, members)
    assert [(p["handle"], len(p["groups"])) for p in people] == \
        [("climber2", 2), ("climber3", 2), ("climber1", 1)]
    assert ME not in {p["id"] for p in people}


def test_deleted_group_is_reported_not_fatal(fake):
    g = fake.make_group("Gone 27 Aug", members={1})
    attendance.add_group(tg.run(tg.find_group_chat(g.title)))
    del fake.groups[g.id]
    members, problems = tg.run(tg.attendance_members(attendance.groups()))
    assert members == {} and len(problems) == 1

# ---------------------------------------------------------------- the sheet script

@needs_node
@pytest.mark.parametrize("text,date", [("27 Aug", "27 Aug"), ("3 September", "3 Sep"), ("31 Feb", ""),
                                       ("Aug-25", ""), ("TOTAL PAX", ""), ("19th Aug", "19 Aug"),
                                       ("4th Sept", "4 Sep"), ("18th Septc", "18 Sep"), ("1st oct", "1 Oct"),
                                       ("22nd Oct", "22 Oct"), ("3rd Nov", "3 Nov"), ("730pm-930pm", "")])
def test_script_reads_dates_like_the_app(text, date):
    assert run_script("sessionDate", text) == date
    assert attendance.session_date(text) == date


@needs_node
def test_import_ticks_dates_and_adds_new_people():
    ws = FakeSheet()
    aug27, oct28 = group("g1", "27 Aug"), group("g2", "28 Oct")
    plan = ws.import_([aug27, oct28], [person(1, "alice", aug27, oct28), person(2, "bob", oct28)])
    assert ws.grid[4][:7] == ["@alice", "Climber1", "1", "", "1", "", "=SUM(C5:F5)"]
    assert ws.grid[5][:7] == ["@bob", "Climber2", "", "", "1", "", "=SUM(C6:F6)"]
    assert plan["summary"] == "✓ 3 new ticks, 2 new people."


@needs_node
def test_import_finds_existing_handles_and_keeps_hand_ticks():
    ws = FakeSheet()
    ws.grid[4][0], ws.grid[4][3] = "@Alice", "1"  # ticked by hand for 29 Aug
    oct28 = group("g2", "28 Oct")
    ws.import_([oct28], [person(1, "alice", oct28)])
    assert ws.grid[4][:6] == ["@Alice", "Climber1", "", "1", "1", ""]
    assert all(v == "" for v in ws.grid[5])


@needs_node
def test_importing_twice_changes_nothing():
    ws = FakeSheet()
    g = group("g1", "27 Aug")
    ws.import_([g], [person(1, "alice", g)])
    ws.writes.clear()
    plan = ws.import_([g], [person(1, "alice", g)])
    assert ws.writes == [] and plan["summary"] == "✓ 0 new ticks, 0 new people."


@needs_node
def test_formulas_already_in_the_sheet_are_left_alone():
    ws = FakeSheet(formulas={(4, 1): "=VLOOKUP(A5,Members!A:B,2,0)", (4, 6): "=COUNT(C5:F5)"})
    g = group("g1", "27 Aug")
    ws.import_([g], [person(1, "alice", g)])
    assert {(r, c) for r, c, _ in ws.writes} == {(4, 0), (4, 2)}


@needs_node
def test_sessions_without_a_column_and_people_without_handles_are_reported():
    ws = FakeSheet()
    ws.grid[4][0], ws.grid[4][2] = "@old_member", "1"  # the tab is in use, so its dates are left alone
    aug27, nov = group("g1", "27 Aug"), group("g9", "5 Nov", title="5 Nov Recre")
    plan = ws.import_([aug27, nov], [person(1, "alice", aug27, nov), person(2, "", aug27), person(3, "bob", nov)])
    assert "No date column in this tab for: 5 Nov Recre" in plan["summary"]
    assert "not added: Climber2" in plan["summary"]
    assert "1 person was only at those sessions" in plan["summary"]
    assert ws.grid[5][:3] == ["@alice", "Climber1", "1"]
    assert all(v == "" for v in ws.grid[6])  # bob: nothing to tick here, so no empty row
    assert ws.grid[1][2:6] == ["27 Aug", "29 Aug", "28 Oct", "30 Oct"]


@needs_node
def test_wrong_tab_in_use_is_refused():
    ws = FakeSheet(dates=("16 Jan", "21 Jan"))
    ws.grid[4][0], ws.grid[4][2] = "@old_member", "1"
    nov = group("g9", "5 Nov")
    with pytest.raises(ScriptError, match="Nothing was changed"):
        ws.import_([nov], [person(1, "alice", nov)])


@needs_node
def test_fresh_tab_gets_this_semesters_dates_and_months():
    """A tab copied from last semester (Jan-Apr dates, no ticks) is set to the sessions' dates."""
    ws = FakeSheet(dates=("16 Jan", "21 Jan", "23 Jan", "4 Feb", "6 Feb"))
    ws.grid[0] = ["", "", "Jan-26", "", "", "Feb-26", "", ""]
    ws.grid[4][:2] = ["@alice", "Alice"]  # handles and names already there are fine
    aug19 = group("g1", "19th Aug", sort="2026-08-16T05:44:01+00:00")
    sep4 = group("g2", "4 Sep", sort="2026-09-01T09:20:44+00:00")
    sep18 = group("g3", "18 Sep", sort="2026-09-14T14:47:41+00:00")
    plan = ws.import_([sep18, aug19, sep4], [person(1, "alice", aug19, sep18), person(2, "bob", sep4)])
    assert ws.grid[1][2:7] == ["19 Aug", "4 Sep", "18 Sep", "", ""]
    assert ws.grid[4][:7] == ["@alice", "Alice", "1", "", "1", "", ""]
    assert ws.grid[5][:5] == ["@bob", "Climber2", "", "1", ""]
    assert plan["layout"]["row"] == 0
    assert plan["layout"]["months"] == [{"col": 2, "span": 1, "label": "Aug-26"},
                                        {"col": 3, "span": 2, "label": "Sep-26"}]
    assert "Set this tab's dates to your sessions (19 Aug to 18 Sep)" in plan["summary"]


def test_dates_typed_as_19th_aug_are_tidied(fake):
    run_option(fake)
    [g] = attendance.groups()
    store.update_config(attendance={"dates": {g["key"]: "18th Septc"}})  # saved before ordinals were understood
    assert attendance.groups()[0]["date"] == "18 Sep"


def test_full_date_uses_the_year_the_group_was_made():
    assert attendance.full_date(group("g", "19 Aug", sort="2026-08-16T05:44:01+00:00")) == "2026-08-19"
    assert attendance.full_date(group("g", "8 Jan", sort="2026-12-28T00:00:00+00:00")) == "2027-01-08"
    assert attendance.full_date(group("g", "", sort="2026-08-16")) == ""


@needs_node
def test_rows_are_added_when_the_sheet_is_full():
    ws = FakeSheet(rows=1)
    g = group("g1", "27 Aug")
    ws.import_([g], [person(i, f"climber{i}", g) for i in range(1, 4)])
    assert [r[0] for r in ws.grid[4:]] == ["@climber1", "@climber2", "@climber3"]


@needs_node
def test_tab_without_headings_is_rejected():
    ws = FakeSheet()
    ws.grid[3][0] = "Something else"
    with pytest.raises(ScriptError, match="Tele Handle"):
        ws.import_([], [])


@needs_node
def test_dates_in_the_heading_row_with_ordinals():
    """The club's real tab: dates like '19th Aug' sit in the same row as 'Tele Handle'."""
    ws = FakeSheet()
    ws.grid = [["Tele Handle", "Name", "19th Aug", "4th Sept", "18th Septc", "Total"],
               ["@ojkiat", "Jun Kiat", "1", "", "", "1"],
               ["", "", "", "", "", ""]]
    sep4 = group("g1", "4 Sep")
    plan = ws.import_([sep4], [person(1, "ojkiat", sep4), person(2, "newbie", sep4)])
    assert ws.grid[1] == ["@ojkiat", "Jun Kiat", "1", "1", "", "1"]
    assert ws.grid[2] == ["@newbie", "Climber2", "", "1", "", "=SUM(C3:E3)"]
    assert plan["summary"] == "✓ 2 new ticks, 1 new person."


@needs_node
def test_club_semester_tab_layout():
    """Laid out like '26/27 Attendance SEM 2': months, dates, TOTAL PAX, headings, a gap, then Total."""
    ws = FakeSheet()
    ws.grid = [["", "", "Jan-26", "", "", "Feb-26", "", "Points For Priority for Welfare"],
               ["", "", "16 Jan", "21 Jan", "23 Jan", "4 Feb", "", ""],
               ["", "TOTAL PAX", "rst Week of Scho", "9", "17", "10", "", ""],
               ["Tele Handle", "Name", "Attendance", "", "", "Attendance", "", "Total Attendance"],
               ["@KaiserLow", "Kaiser Low", "", "", "1", "", "", ""],
               ["", "", "", "", "", "", "", ""],
               ["", "", "", "", "", "", "", ""]]
    jan21, jan23, feb4 = group("g1", "21 Jan"), group("g2", "23 Jan"), group("g3", "4 Feb")
    people = [person(1, "Late_Comer", feb4, jan23),      # most sessions, but first came 23 Jan
              person(2, "kaiserlow", jan23, feb4),       # already in the sheet, different capitals
              person(3, "EarlyBird", jan21)]             # first came 21 Jan, so goes first
    ws.import_([jan21, jan23, feb4], people)
    assert ws.grid[4] == ["@KaiserLow", "Kaiser Low", "", "", "1", "1", "", "=SUM(C5:F5)"]
    assert ws.grid[5] == ["@EarlyBird", "Climber3", "", "1", "", "", "", "=SUM(C6:F6)"]
    assert ws.grid[6] == ["@Late_Comer", "Climber1", "", "", "1", "1", "", "=SUM(C7:F7)"]
    assert ws.grid[2] == ["", "TOTAL PAX", "rst Week of Scho", "9", "17", "10", "", ""]


@needs_node
def test_column_letters_past_z():
    assert run_script("columnLetter", 25) == "Z" and run_script("columnLetter", 27) == "AB"


# ---------------------------------------------------------------- the page

@pytest.fixture
def client(fake):
    store.update_config(api_id="1", api_hash="x" * 32)
    webapp.app.config["TESTING"] = True
    return webapp.app.test_client()


def test_page_lists_groups_and_offers_the_script(client, fake):
    run_option(fake)
    page = client.get("/attendance").get_data(as_text=True)
    assert "28 Oct Recre @ B+ Aperia" in page and 'value="28 Oct"' in page
    assert "function importAttendance" in page


def test_run_counts_and_gives_data_for_the_sheet(client, fake):
    fake.vote(OPT_A, [1, 2])
    run_option(fake)
    page = client.post("/attendance/run").get_data(as_text=True)
    assert "@climber1" in page and "2 people across 1 groups" in page
    assert "Copy for sheet" in page and "recre-attendance" in page

def test_add_and_remove_from_page(client, fake):
    fake.make_group("Extra 30 Oct", members={5})
    client.post("/attendance/groups", data={"add": "Extra 30 Oct"})
    [g] = attendance.groups()
    assert g["date"] == "30 Oct"
    client.post("/attendance/groups", data={"remove": g["key"], f"date:{g['key']}": "30 Oct"})
    assert attendance.groups() == []
