"""Prefilling session details and filling the welcome templates."""
import random
import string
from datetime import datetime, timezone

import pytest

import welcome

OCT = datetime(2026, 10, 24, tzinfo=timezone.utc)


@pytest.mark.parametrize("text,date,time,start,meet,day,location", [
    ("28 Oct 730pm-930pm @B+ Aperia w/Darryl", "28 Oct", "7.30pm-9.30pm", "7.30pm", "7.00pm", "Wednesday", "B+ Aperia"),
    ("30 Oct 4pm-6pm @BP TS w/Irina", "30 Oct", "4.00pm-6.00pm", "4.00pm", "3.30pm", "Friday", "BP TS"),
    ("25 Sept 4.00pm-6.00pm @Ground Up", "25 Sept", "4.00pm-6.00pm", "4.00pm", "3.30pm", "", "Ground Up"),
    ("2 Nov 7.30pm - 9.30pm @ Boulder Planet", "2 Nov", "7.30pm-9.30pm", "7.30pm", "7.00pm", "Monday", "Boulder Planet"),
    ("5 Nov 1030am-1230pm @Z", "5 Nov", "10.30am-12.30pm", "10.30am", "10.00am", "Thursday", "Z"),
    ("6 Nov 10-12pm @GU", "6 Nov", "10.00am-12.00pm", "10.00am", "9.30am", "Friday", "GU"),
    ("7 Nov 11am-1pm @GU", "7 Nov", "11.00am-1.00pm", "11.00am", "10.30am", "Saturday", "GU"),
    ("8 Nov 12pm-2pm @GU", "8 Nov", "12.00pm-2.00pm", "12.00pm", "11.30am", "Sunday", "GU"),
    ("9 Nov 7:30pm-9:30pm @GU", "9 Nov", "7.30pm-9.30pm", "7.30pm", "7.00pm", "Monday", "GU"),
    ("10 November 8PM-10PM @GU", "10 November", "8.00pm-10.00pm", "8.00pm", "7.30pm", "Tuesday", "GU"),
    ("12 Nov 12am-2am @GU", "12 Nov", "12.00am-2.00am", "12.00am", "11.30pm", "Thursday", "GU"),
])
def test_guess_formats(fake, text, date, time, start, meet, day, location):
    v = welcome.guess(text, OCT)
    assert (v["date"], v["time"], v["start"], v["meet_time"], v["location"]) == (date, time, start, meet, location)
    if day:
        assert v["day"] == day


def test_sept_spelling_still_gets_a_weekday(fake):
    # "Sept" isn't a standard month abbreviation; the weekday may be blank but must not crash
    v = welcome.guess("25 Sept 4pm-6pm @GU", datetime(2026, 9, 20, tzinfo=timezone.utc))
    assert v["date"] == "25 Sept"


def test_january_session_in_december_poll_uses_next_year(fake):
    v = welcome.guess("3 Jan 4pm-6pm @GU", datetime(2026, 12, 26, tzinfo=timezone.utc))
    assert v["day"] == datetime(2027, 1, 3).strftime("%A")


@pytest.mark.parametrize("text", [
    "", "Can't make it", "TBC", "@", "@@@", "28 Oct", "4pm-6pm", "99 Zzz 99pm-99pm @x", "31 Feb 4pm-6pm @GU",
    "28 Oct 25pm-26pm @GU", "28 Oct 4.75pm-6pm @GU", "🧗🧗🧗", "x" * 10000, "28 Oct 4pm-6pm @",
])
def test_weird_options_never_crash(fake, text):
    v = welcome.guess(text, OCT)
    assert set(v) == set(welcome.PLACEHOLDERS)


def test_fuzz_guess_and_fill(fake):
    rng = random.Random(7)
    alphabet = string.ascii_letters + string.digits + " @-.:/w{}😀"
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        v = welcome.guess(text, OCT)
        welcome.fill(welcome.DEFAULTS["welcome"], v)


def test_remember_place(fake):
    welcome.remember_place({"location": "Ground Up", "mrt": "NE8 Farrer Park", "loc_short": "GU",
                            "meet_point": "Bencoolen Exit C"})
    v = welcome.guess("25 Sept 4pm-6pm @ground up", OCT)
    assert (v["mrt"], v["loc_short"], v["meet_point"]) == ("NE8 Farrer Park", "GU", "Bencoolen Exit C")
    other = welcome.guess("25 Sept 4pm-6pm @Somewhere New", OCT)
    assert other["mrt"] == "" and other["loc_short"] == "Somewhere New"
    assert other["meet_point"] == "Bencoolen Exit C"


def test_remember_place_without_location(fake):
    welcome.remember_place({"location": "", "meet_point": "SOE Exit"})
    assert welcome.guess("x", OCT)["meet_point"] == "SOE Exit"


def test_fill_leaves_unknown_placeholders(fake):
    assert welcome.fill("{date} {nope} {", {"date": "28 Oct"}) == "28 Oct {nope} {"


def test_templates_save_and_defaults(fake):
    assert welcome.templates() == welcome.DEFAULTS
    welcome.save_templates(**dict(welcome.DEFAULTS, meet="custom"), extra="ignored")
    assert welcome.templates()["meet"] == "custom"
    assert welcome.templates()["welcome"] == welcome.DEFAULTS["welcome"]


def test_default_welcome_fills_completely(fake):
    v = welcome.guess("25 Oct 4pm-6pm @Ground Up", OCT)
    v.update(mrt="NE8 Farrer Park", loc_short="GU")
    text = welcome.fill(welcome.DEFAULTS["welcome"], v)
    assert "{" not in text
    assert "[25 Oct 4.00pm-6.00pm] @ Ground Up" in text and "(NE8 Farrer Park)" in text
    assert welcome.fill(welcome.DEFAULTS["meet"], v) == (
        "You can either meet us directly at GU @ 4.00pm or meet in school at Bencoolen Exit C @ 3.30pm! "
        "We'll be taking the MRT over :)")
    assert welcome.fill(welcome.DEFAULTS["poll_options"], v).splitlines() == [
        "Bencoolen Exit C @ 3.30pm", "GU @ 4.00pm"]


def test_with_examples_fills_only_empty_boxes(fake):
    v, ex = welcome.with_examples(welcome.guess("28 Oct 730pm-930pm @B+ Aperia", OCT))
    assert v["date"] == "28 Oct" and v["location"] == "B+ Aperia"
    assert v["mrt"] == welcome.EXAMPLES["mrt"] and ex == ["mrt"]
    assert all(v[k].strip() for k in welcome.PLACEHOLDERS if k not in welcome.OPTIONAL)


def test_unreadable_option_is_all_examples_except_meet_point(fake):
    v, ex = welcome.with_examples(welcome.guess("Can't make it", OCT))
    assert set(ex) == set(welcome.PLACEHOLDERS) - {"meet_point"} - welcome.OPTIONAL
    assert "{" not in welcome.fill(welcome.DEFAULTS["welcome"], v)


# ---------------------------------------------------------------- map links

MAP = "https://maps.app.goo.gl/AbC123"


def test_fill_links_location_when_map_link_given(fake):
    v = {"date": "28 Oct", "time": "4.00pm-6.00pm", "location": "Ground Up", "map_link": MAP}
    assert welcome.fill("[{date} {time}] @ {location}", v) == f"[28 Oct 4.00pm-6.00pm] @ [Ground Up]({MAP})"


@pytest.mark.parametrize("link", ["", "   ", "not a link", "https://", "ground up", "maps", "https://nodot", "a b.com"])
def test_fill_without_valid_map_link_keeps_plain_location(fake, link):
    assert welcome.fill("@ {location}", {"location": "Ground Up", "map_link": link}) == "@ Ground Up"


def test_parse_links_basic(fake):
    plain, links = welcome.parse_links(f"[28 Oct 4.00pm-6.00pm] @ [Ground Up]({MAP})\nNearest MRT")
    assert plain == "[28 Oct 4.00pm-6.00pm] @ Ground Up\nNearest MRT"
    assert links == [(len("[28 Oct 4.00pm-6.00pm] @ "), len("Ground Up"), MAP)]


def test_parse_links_offsets_count_emoji_as_two(fake):
    plain, links = welcome.parse_links(f"🧗🧦 [GU]({MAP}) and [BP](https://x.com/y)")
    assert plain == "🧗🧦 GU and BP"
    assert links == [(5, 2, MAP), (5 + 2 + 5, 2, "https://x.com/y")]


@pytest.mark.parametrize("text", [
    "no links here", "[just brackets]", "(just parens)", "[text](not-a-url)", "[a]\n(https://x.com)",
    "Bring socks ($6)!! 🧦", "[28 Oct 4.00pm-6.00pm] @ Ground Up",
])
def test_text_without_links_is_unchanged(fake, text):
    assert welcome.parse_links(text) == (text, [])


def test_strip_links(fake):
    assert welcome.strip_links(f"[GU]({MAP}) @ 4.00pm") == "GU @ 4.00pm"


def test_default_welcome_with_map_link_end_to_end(fake):
    v = welcome.guess("28 Oct 4pm-6pm @Ground Up", OCT)
    v.update(mrt="NE8 Farrer Park", map_link=MAP)
    plain, links = welcome.parse_links(welcome.fill(welcome.DEFAULTS["welcome"], v))
    assert "[28 Oct 4.00pm-6.00pm] @ Ground Up" in plain and MAP not in plain
    (offset, length, url), = links
    assert plain.encode("utf-16-le")[offset * 2:(offset + length) * 2].decode("utf-16-le") == "Ground Up"
    assert url == MAP


def test_map_link_remembered_per_place(fake):
    welcome.remember_place({"location": "Ground Up", "map_link": MAP, "mrt": "NE8"})
    assert welcome.guess("1 Nov 4pm-6pm @Ground Up", OCT)["map_link"] == MAP
    assert welcome.guess("1 Nov 4pm-6pm @Elsewhere", OCT)["map_link"] == ""


def test_map_link_never_gets_an_example_value(fake):
    _, ex = welcome.with_examples(welcome.guess("Can't make it", OCT))
    assert "map_link" not in ex


USER_LINK = ("google.com/maps/place/Fat+Cow+-+Japanese+Wagyu+@+Camden+Medical+Centre/@1.2998376,103.8548992,15z/"
             "data=!3m1!5s0x31da198b8e323299:0x8a271da618c8886!4m6!3m5!1s0x31da19898122216d:0x924451ca79d17f5d!8m2!"
             "3d1.3033039!4d103.8239218!16s%2Fg%2F1vcjjs6m?entry=ttu&g_ep=EgoyMDI2MTAyMC4wIKXMDSoASAFQAw%3D%3D")


@pytest.mark.parametrize("link,expected", [
    (USER_LINK, "https://" + USER_LINK),
    ("maps.app.goo.gl/AbC123", "https://maps.app.goo.gl/AbC123"),
    ("www.google.com/maps/place/GU", "https://www.google.com/maps/place/GU"),
    ("  https://maps.app.goo.gl/AbC123  ", "https://maps.app.goo.gl/AbC123"),
    ("HTTP://Example.com/x", "HTTP://Example.com/x"),
    ("https://www.google.com/maps/place/Climb+(Central)", "https://www.google.com/maps/place/Climb+%28Central%29"),
])
def test_normalize_link(link, expected):
    assert welcome.normalize_link(link) == expected


def test_users_google_maps_link_end_to_end(fake):
    v = welcome.guess("28 Oct 4pm-6pm @Ground Up", OCT)
    v["map_link"] = USER_LINK
    plain, links = welcome.parse_links(welcome.fill(welcome.DEFAULTS["welcome"], v))
    assert "[28 Oct 4.00pm-6.00pm] @ Ground Up" in plain and "google.com" not in plain
    (offset, length, url), = links
    assert url == "https://" + USER_LINK
    assert plain.encode("utf-16-le")[offset * 2:(offset + length) * 2].decode("utf-16-le") == "Ground Up"


def test_link_with_brackets_is_not_cut_short(fake):
    v = {"location": "Climb Central", "map_link": "https://www.google.com/maps/place/Climb+(Central)/@1,2"}
    plain, links = welcome.parse_links(welcome.fill("@ {location}!", v))
    assert plain == "@ Climb Central!"
    assert links[0][2] == "https://www.google.com/maps/place/Climb+%28Central%29/@1,2"


def test_link_saved_with_https(fake):
    welcome.remember_place({"location": "Fat Cow", "map_link": USER_LINK})
    assert welcome.guess("1 Nov 4pm-6pm @Fat Cow", OCT)["map_link"] == "https://" + USER_LINK
