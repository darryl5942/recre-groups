"""The web pages, driven through Flask's test client against the fake Telegram."""
import time

import pytest

import app as webapp
import store
import tg
import welcome
from conftest import CHAT, OPT_A, POLL_MSG


@pytest.fixture
def client(fake, monkeypatch):
    store.update_config(api_id="123", api_hash="a" * 32)
    webapp._jobs.clear()
    webapp.app.config["TESTING"] = False  # show errors the way users would see them
    return webapp.app.test_client()


def run_form(**over):
    form = {"chat": str(CHAT), "msg": str(POLL_MSG), "opt": OPT_A.hex(), "title": "28 Oct Recre @ B+ Aperia",
            "cap": "20", "dm": "Hi {name} {link}", "post_welcome": "1", "welcome_text": "Welcome!",
            "meet_text": "Meet!", "poll_question": "Meet where!!!", "poll_options": "A\nB",
            **{k: "" for k in welcome.PLACEHOLDERS}}
    form.update(over)
    return form


def wait_for_job(client, location, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(location + "/status").get_json()
        if s["done"]:
            return s
        time.sleep(0.05)
    raise AssertionError("job never finished")


# ---------------------------------------------------------------- setup and login

def test_no_keys_goes_to_setup(fake):
    c = webapp.app.test_client()
    assert c.get("/").headers["Location"].endswith("/setup")


@pytest.mark.parametrize("api_id,api_hash,ok", [
    ("123", "a" * 32, True), ("abc", "a" * 32, False), ("123", "short", False), ("", "", False),
    ("  456  ", "  " + "b" * 32 + "  ", True),
])
def test_setup_validation(fake, monkeypatch, api_id, api_hash, ok):
    async def noop():
        pass
    monkeypatch.setattr(tg, "reset_client", noop)
    r = webapp.app.test_client().post("/setup", data={"api_id": api_id, "api_hash": api_hash})
    assert r.headers["Location"].endswith("/login" if ok else "/setup")
    if ok:
        assert store.load_config()["api_id"] == api_id.strip()


def test_code_step_without_phone_restarts_login(client):
    r = client.post("/login?step=code", data={"code": "12345"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")


def test_logged_out_redirects_to_login(client, fake):
    async def no():
        return False
    fake.is_user_authorized = no
    assert client.get("/").headers["Location"].endswith("/login")


# ---------------------------------------------------------------- choosing chat and poll

def test_index_lists_polls(client, fake):
    fake.vote(OPT_A, [1, 2])
    store.update_config(chat_id=CHAT)
    html = client.get("/").get_data(as_text=True)
    assert "WEEK 11 RECRE" in html and "28 Oct 730pm-930pm" in html


def test_index_typed_chat(client):
    html = client.get("/?q=climbing").get_data(as_text=True)
    assert "WEEK 11 RECRE" in html
    assert store.load_config()["chat_id"] == CHAT


def test_index_unknown_typed_chat(client):
    html = client.get("/?q=does-not-exist").get_data(as_text=True)
    assert "No chat found" in html


def test_index_chat_we_left_shows_error_not_crash(client, fake):
    async def broken(*a, **k):
        raise ValueError("Could not find the input entity for PeerChannel")
        yield
    fake.iter_messages = broken
    r = client.get(f"/?chat={CHAT}")
    assert r.status_code < 500 or "went wrong" in r.get_data(as_text=True)
    assert "Traceback" not in r.get_data(as_text=True)


def test_option_page_prefills(client, fake):
    fake.vote(OPT_A, range(1, 25))
    html = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}").get_data(as_text=True)
    assert "cut-off: first 20" in html
    assert 'value="28 Oct Recre @ B+ Aperia"' in html
    assert "Welcome message" not in html  # that's on its own page now
    assert "Create group and add 20 people" in html


def test_option_page_with_no_voters(client):
    html = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}").get_data(as_text=True)
    assert "Nobody has voted" in html


def test_option_page_bad_cap_falls_back(client, fake):
    fake.vote(OPT_A, [1])
    r = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}&cap=abc")
    assert r.status_code == 200


def test_option_page_vote_required(client, fake):
    fake.vote_required = True
    r = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}")
    assert r.status_code == 400 and "voted in this poll yourself" in r.get_data(as_text=True)


@pytest.mark.parametrize("query", ["chat=x&msg=5&opt=00", f"chat={CHAT}&msg=5", f"chat={CHAT}&msg=5&opt=zz"])
def test_option_page_bad_urls_dont_crash(client, query):
    r = client.get("/option?" + query)
    assert r.status_code in (400, 404)


def test_html_in_names_is_escaped(client, fake):
    fake.vote(OPT_A, [1])
    fake.users[1].first_name = "<script>alert(1)</script>"
    html = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


# ---------------------------------------------------------------- running

def test_full_run_with_progress_and_results(client, fake):
    fake.vote(OPT_A, range(1, 26))
    fake.privacy_block = {3}
    r = client.post("/run", data=run_form())
    loc = r.headers["Location"]
    assert "/job/" in loc
    s = wait_for_job(client, loc)
    assert s["error"] is None
    assert any("Adding" in m for m in s["log"])
    html = client.get(loc).get_data(as_text=True)
    assert "Added" in html and "Invite link sent" in html and "Download Excel sheet" in html
    assert "Next: welcome messages" in html
    assert fake.group_posts == {}
    sheet = store.EXPORT_DIR / "28 Oct Recre @ B+ Aperia.xlsx"
    assert sheet.exists()
    assert client.get("/exports/28 Oct Recre @ B+ Aperia.xlsx").status_code == 200


def test_second_run_blocked_while_first_running(client, fake, monkeypatch):
    fake.vote(OPT_A, range(1, 6))
    import asyncio

    async def slow_pause(lo, hi):
        await asyncio.sleep(0.2)
    monkeypatch.setattr(tg, "_pause", slow_pause)
    first = client.post("/run", data=run_form()).headers["Location"]
    second = client.post("/run", data=run_form(), headers={"Referer": "/option"})
    assert "/job/" not in second.headers["Location"]
    wait_for_job(client, first)
    assert len(fake.groups) == 1


def test_job_error_is_shown(client, fake):
    fake.vote_required = True
    s = wait_for_job(client, client.post("/run", data=run_form()).headers["Location"])
    assert "voted in this poll yourself" in s["error"]


def test_unexpected_crash_in_job_is_reported(client, fake, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(tg, "run_option", boom)
    s = wait_for_job(client, client.post("/run", data=run_form()).headers["Location"])
    assert "kaboom" in s["error"]


@pytest.mark.parametrize("cap", ["0", "-5", "abc", ""])
def test_bad_cap_in_run_form(client, fake, cap):
    fake.vote(OPT_A, [1])
    r = client.post("/run", data=run_form(cap=cap))
    assert r.status_code == 302
    if "/job/" in r.headers["Location"]:
        assert wait_for_job(client, r.headers["Location"])["error"] is None


def test_empty_title_is_refused(client, fake):
    fake.vote(OPT_A, [1])
    r = client.post("/run", data=run_form(title="   "), headers={"Referer": "/option"})
    assert "/job/" not in r.headers["Location"]
    assert fake.groups == {}


def test_unknown_job_404(client):
    assert client.get("/job/nope").status_code == 404
    assert client.get("/job/nope/status").status_code == 404


def test_download_cannot_escape_exports(client):
    assert client.get("/exports/../config.json").status_code == 404
    assert client.get("/exports/..%2Fconfig.json").status_code == 404


# ---------------------------------------------------------------- templates page

def test_templates_save_reset(client):
    assert client.get("/templates").status_code == 200
    client.post("/templates", data=dict(welcome.DEFAULTS, meet="New {start}", back=""))
    assert welcome.templates()["meet"] == "New {start}"
    client.post("/templates", data=dict(welcome.DEFAULTS, reset="1", back=""))
    assert welcome.templates()["meet"] == welcome.DEFAULTS["meet"]


def test_templates_partial_form_does_not_crash(client):
    r = client.post("/templates", data={"meet": "only this"})
    assert r.status_code == 302
    assert welcome.templates()["meet"] == "only this"
    assert welcome.templates()["welcome"] == welcome.DEFAULTS["welcome"]


def test_templates_back_link_stays_on_site(client):
    r = client.post("/templates", data=dict(welcome.DEFAULTS, back="https://evil.example.com"))
    assert "evil.example.com" not in r.headers["Location"]




def test_option_page_keeps_current_group_name(client, fake):
    fake.vote(OPT_A, [1])
    tg.run(tg.run_option(CHAT, POLL_MSG, OPT_A.hex(), "Option 1", 20, "{link}", progress=lambda *a: None))
    next(iter(fake.groups.values())).title = "Renamed in Telegram"
    html = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}").get_data(as_text=True)
    assert 'value="Renamed in Telegram"' in html and "will be renamed" not in html


def test_option_page_warns_about_rename(client, fake):
    fake.vote(OPT_A, [1])
    tg.run(tg.run_option(CHAT, POLL_MSG, OPT_A.hex(), "Option 1", 20, "{link}", progress=lambda *a: None))
    html = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}&title=New+name").get_data(as_text=True)
    assert "will be renamed to" in html and "New name" in html


def test_run_form_uses_name_typed_into_box(client, fake):
    html = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}").get_data(as_text=True)
    assert 'id="title_box"' in html and 'namedItem("title").value = title' in html


def test_invite_message_is_remembered_for_next_time(client, fake):
    fake.vote(OPT_A, [1])
    html = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}").get_data(as_text=True)
    assert "{date} Recreational Session" in html  # the new default
    loc = client.post("/run", data=run_form(dm="Custom {date} {link}")).headers["Location"]
    wait_for_job(client, loc)
    html = client.get(f"/option?chat={CHAT}&msg={POLL_MSG}&opt={OPT_A.hex()}").get_data(as_text=True)
    assert "Custom {date} {link}" in html
