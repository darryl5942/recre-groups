"""Welcome messages: their own step after the group exists, sent now or scheduled."""
import time
from datetime import datetime, timedelta, timezone

import pytest
from telethon import types

import app as webapp
import store
import tg
import welcome
from conftest import CHAT, OPT_A, OPT_B, POLL_MSG, run_option

POSTS = {"welcome": "HII gang! Welcome", "meet": "Meet us at GU @ 4.00pm!", "poll_question": "Meet where!!!",
         "poll_options": ["Bencoolen Exit C @ 3.30pm", "GU @ 4.00pm"]}
KEY = store.record_key(CHAT, POLL_MSG, OPT_A.hex())


@pytest.fixture
def group(fake):
    fake.vote(OPT_A, [1, 2])
    run_option(fake)
    return next(iter(fake.groups))


def send(posts=POSTS, when=None, pin=True):
    return tg.run(tg.send_messages(KEY, posts, when=when, pin=pin))


def soon(minutes=30):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


# ---------------------------------------------------------------- sending now

def test_send_now_posts_all_three_and_pins(fake, group):
    assert send() == ["welcome message", "meeting message", "poll"]
    posts = fake.group_posts[group]
    assert posts[0] == POSTS["welcome"] and posts[1] == POSTS["meet"]
    assert isinstance(posts[2], types.Poll) and posts[2].public_voters
    assert [a.text.text for a in posts[2].answers] == POSTS["poll_options"]
    assert group in fake.pinned
    rec = store.get_record(KEY)
    assert rec["messages"][-1]["sent"] == ["welcome message", "meeting message", "poll"]
    assert not rec["messages"][-1]["scheduled"]


def test_send_without_pin(fake, group):
    send(pin=False)
    assert group not in fake.pinned


def test_empty_parts_are_skipped(fake, group):
    assert send({"welcome": " ", "meet": "", "poll_question": "", "poll_options": []}) == []
    assert group not in fake.group_posts and group not in fake.pinned
    assert "messages" not in store.get_record(KEY)


def test_poll_options_cleaned_and_capped_at_10(fake, group):
    send(dict(POSTS, poll_options=["", "  "] + [f"Option {i}" for i in range(15)]))
    assert len(fake.group_posts[group][2].answers) == 10


def test_poll_skipped_with_fewer_than_two_options(fake, group):
    assert send(dict(POSTS, poll_options=["Only one"])) == ["welcome message", "meeting message"]


def test_very_long_poll_texts_are_trimmed(fake, group):
    send(dict(POSTS, poll_question="Q" * 400, poll_options=["A" * 300, "B"]))
    poll = fake.group_posts[group][2]
    assert len(poll.question.text) == 255 and len(poll.answers[0].text.text) == 100


def test_sending_before_any_group_exists(fake):
    with pytest.raises(tg.TgError, match="No group"):
        send()


def test_sending_to_deleted_group(fake, group):
    del fake.groups[group]
    with pytest.raises(tg.TgError, match="deleted"):
        send()


def test_telegram_refusal_mid_way_reports_what_was_sent(fake, group, monkeypatch):
    real = fake.send_message

    async def fail_on_poll(entity, message=None, file=None, **k):
        if file is not None:
            raise tg.errors.ChatWriteForbiddenError(None)
        return await real(entity, message, file=file, **k)
    monkeypatch.setattr(fake, "send_message", fail_on_poll)
    with pytest.raises(tg.TgError, match="welcome message, meeting message"):
        send()
    assert store.get_record(KEY)["messages"][-1]["sent"] == ["welcome message", "meeting message"]


def test_sending_twice_is_allowed_and_logged(fake, group):
    send()
    send()
    assert len(fake.group_posts[group]) == 6
    assert len(store.get_record(KEY)["messages"]) == 2


# ---------------------------------------------------------------- scheduling

def test_schedule_hands_messages_to_telegram(fake, group):
    when = soon()
    assert send(when=when) == ["welcome message", "meeting message", "poll"]
    assert group not in fake.group_posts  # nothing in the chat yet
    assert [(g, w) for g, w, _ in fake.scheduled] == [(group, when)] * 3
    rec = store.get_record(KEY)
    assert rec["messages"][-1]["scheduled"]
    assert rec["pending_pins"] == [{"at": when.isoformat(), "text": POSTS["welcome"]}]
    assert group not in fake.pinned


@pytest.mark.parametrize("when,match", [
    (lambda: datetime.now(timezone.utc) - timedelta(minutes=5), "at least a minute"),
    (lambda: datetime.now(timezone.utc) + timedelta(seconds=5), "at least a minute"),
    (lambda: datetime.now(timezone.utc) + timedelta(days=400), "up to a year"),
])
def test_bad_schedule_times(fake, group, when, match):
    with pytest.raises(tg.TgError, match=match):
        send(when=when())
    assert fake.scheduled == []


def test_scheduled_welcome_pinned_after_telegram_sends_it(fake, group, monkeypatch):
    when = soon()
    send(when=when)
    assert tg.run(tg.pin_due()) == 0  # not due yet
    fake.deliver_scheduled()
    future = when + timedelta(minutes=1)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return future
    monkeypatch.setattr(tg, "datetime", Later)
    assert tg.run(tg.pin_due()) == 1
    assert group in fake.pinned
    assert store.get_record(KEY)["pending_pins"] == []
    assert tg.run(tg.pin_due()) == 0  # never pinned twice


def test_scheduled_but_not_yet_delivered_keeps_waiting(fake, group, monkeypatch):
    when = soon()
    send(when=when)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return when + timedelta(minutes=5)
    monkeypatch.setattr(tg, "datetime", Later)
    assert tg.run(tg.pin_due()) == 0
    assert len(store.get_record(KEY)["pending_pins"]) == 1


def test_cancelled_scheduled_message_is_given_up_after_2_days(fake, group, monkeypatch):
    when = soon()
    send(when=when)
    fake.scheduled = []  # captain cancelled it in Telegram

    class MuchLater(datetime):
        @classmethod
        def now(cls, tz=None):
            return when + timedelta(days=3)
    monkeypatch.setattr(tg, "datetime", MuchLater)
    assert tg.run(tg.pin_due()) == 0
    assert store.get_record(KEY)["pending_pins"] == []


def test_pin_due_survives_deleted_group(fake, group, monkeypatch):
    when = soon()
    send(when=when)
    del fake.groups[group]

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return when + timedelta(days=3)
    monkeypatch.setattr(tg, "datetime", Later)
    assert tg.run(tg.pin_due()) == 0


# ---------------------------------------------------------------- the pages

@pytest.fixture
def client(fake):
    store.update_config(api_id="123", api_hash="a" * 32)
    webapp.app.config["TESTING"] = False
    return webapp.app.test_client()


def form(**over):
    f = {"key": KEY, "welcome_text": "Welcome!", "meet_text": "Meet!", "poll_question": "Meet where!!!",
         "poll_options": "A\nB", "pin": "1", "when_mode": "now", **{k: "" for k in welcome.PLACEHOLDERS}}
    f.update(over)
    return f


def test_messages_page_prefills_from_option(client, fake, group):
    html = client.get(f"/messages?key={KEY}").get_data(as_text=True)
    assert 'value="7.30pm-9.30pm"' in html and 'value="7.00pm"' in html and 'value="B+ Aperia"' in html
    assert 'data-tag="date"' not in html and '<span class="tag" data-tag="mrt"' in html
    assert "Send now" in html and 'type="datetime-local"' in html


def test_messages_page_unreadable_option_uses_examples(client, fake):
    fake.vote(OPT_B, [1])
    fake.extra_polls = [fake.poll_message(msg_id=77, options={OPT_B: "Friday session (TBC)"})]
    tg.run(tg.run_option(CHAT, 77, OPT_B.hex(), "Friday", 20, "{link}", progress=lambda *a: None))
    html = client.get(f"/messages?key={CHAT}:77:{OPT_B.hex()}").get_data(as_text=True)
    assert html.count('<span class="tag" data-tag=') == len(welcome.PLACEHOLDERS) - 1 - len(welcome.OPTIONAL)
    assert 'value="NE8 Farrer Park"' in html


def test_send_now_from_page(client, fake, group):
    r = client.post("/messages", data=form(location="B+ Aperia", mrt="DT21 Bencoolen", loc_short="B+"))
    assert r.status_code == 302
    assert fake.group_posts[group][:2] == ["Welcome!", "Meet!"]
    html = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "Sent the welcome message, meeting message, poll" in html
    assert "Already sent to this group" in html
    assert 'value="DT21 Bencoolen"' in html  # place remembered


def test_schedule_from_page(client, fake, group):
    local = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)
    r = client.post("/messages", data=form(when_mode="schedule", when=local.strftime("%Y-%m-%dT%H:%M")))
    html = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "Scheduled the welcome message" in html
    assert len(fake.scheduled) == 3
    assert fake.scheduled[0][1] == local.astimezone().astimezone(timezone.utc)


@pytest.mark.parametrize("when", ["", "not-a-date"])
def test_schedule_without_valid_time(client, fake, group, when):
    r = client.post("/messages", data=form(when_mode="schedule", when=when))
    assert "Pick the date and time" in client.get(r.headers["Location"]).get_data(as_text=True)
    assert fake.scheduled == []


def test_schedule_in_past_from_page(client, fake, group):
    past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    r = client.post("/messages", data=form(when_mode="schedule", when=past),
                    headers={"Referer": f"/messages?key={KEY}"})
    assert "at least a minute" in client.get(r.headers["Location"]).get_data(as_text=True)


def test_all_empty_from_page(client, fake, group):
    r = client.post("/messages", data=form(welcome_text="", meet_text="", poll_question=""))
    assert "Nothing was sent" in client.get(r.headers["Location"]).get_data(as_text=True)


@pytest.mark.parametrize("key", ["", "nonsense", "1:2"])
def test_messages_page_bad_key(client, key):
    assert client.get(f"/messages?key={key}").status_code == 400


def test_messages_page_unknown_group(client):
    r = client.get(f"/messages?key={CHAT}:5:ff")
    assert r.status_code == 400 and "No group has been made" in r.get_data(as_text=True)


def test_groups_page(client, fake, group):
    html = client.get("/groups").get_data(as_text=True)
    assert "28 Oct Recre @ B+ Aperia" in html and "Welcome messages not sent yet" in html
    client.post("/messages", data=form())
    assert "✓ Welcome messages sent" in client.get("/groups").get_data(as_text=True)


def test_groups_page_empty(client):
    assert "No groups yet" in client.get("/groups").get_data(as_text=True)


def test_results_page_links_to_messages(client, fake):
    fake.vote(OPT_A, [1])
    r = client.post("/run", data={"chat": str(CHAT), "msg": str(POLL_MSG), "opt": OPT_A.hex(),
                                  "title": "28 Oct Recre @ B+ Aperia", "cap": "20", "dm": "{link}"})
    loc = r.headers["Location"]
    for _ in range(200):
        if client.get(loc + "/status").get_json()["done"]:
            break
        time.sleep(0.05)
    html = client.get(loc).get_data(as_text=True)
    assert f"/messages?key={KEY.replace(':', '%3A')}" in html or f"/messages?key={KEY}" in html


# ---------------------------------------------------------------- map links

MAP = "https://maps.app.goo.gl/AbC123"


def test_location_sent_as_clickable_link(fake, group):
    send(dict(POSTS, welcome=f"Hi 🧗\n[28 Oct] @ [Ground Up]({MAP})", meet=f"Meet at [GU]({MAP})"))
    posts = fake.group_posts[group]
    assert posts[0] == "Hi 🧗\n[28 Oct] @ Ground Up" and posts[1] == "Meet at GU"
    (text, (entity,)), (_, (meet_entity,)) = fake.links
    assert isinstance(entity, types.MessageEntityTextUrl) and entity.url == MAP
    assert text.encode("utf-16-le")[entity.offset * 2:(entity.offset + entity.length) * 2].decode("utf-16-le") == "Ground Up"
    assert meet_entity.offset == len("Meet at ")


def test_links_removed_from_poll(fake, group):
    send(dict(POSTS, poll_question=f"Meet where @ [GU]({MAP})?", poll_options=[f"[GU]({MAP}) @ 4pm", "School"]))
    poll = fake.group_posts[group][2]
    assert poll.question.text == "Meet where @ GU?"
    assert poll.answers[0].text.text == "GU @ 4pm"


def test_scheduled_linked_welcome_still_gets_pinned(fake, group, monkeypatch):
    when = soon()
    send(dict(POSTS, welcome=f"[28 Oct] @ [Ground Up]({MAP})"), when=when)
    assert store.get_record(KEY)["pending_pins"][0]["text"] == "[28 Oct] @ Ground Up"
    for gid, w, content in fake.scheduled:  # Telegram delivers the plain text
        pass
    fake.deliver_scheduled()

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return when + timedelta(minutes=1)
    monkeypatch.setattr(tg, "datetime", Later)
    assert tg.run(tg.pin_due()) == 1


def test_messages_page_has_optional_map_link(client, fake, group):
    html = client.get(f"/messages?key={KEY}").get_data(as_text=True)
    assert 'name="map_link"' in html and "data-optional" in html and 'type="url"' not in html
    assert '<span class="tag" data-tag="map_link"' not in html


def test_map_link_remembered_from_page(client, fake, group):
    client.post("/messages", data=form(location="B+ Aperia", map_link=MAP))
    assert f'value="{MAP}"' in client.get(f"/messages?key={KEY}").get_data(as_text=True)
