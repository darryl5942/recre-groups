"""Who counts as the first 20, and what a run does to the group."""
import random
from datetime import timedelta

import pytest

import store
import tg
from conftest import CHAT, ME, OPT_A, OPT_B, POLL_DATE, POLL_MSG, run_option, statuses, user



def voters(fake, option=OPT_A):
    return tg.run(tg.get_voters(CHAT, POLL_MSG, option.hex()))


# ---------------------------------------------------------------- ordering

def test_voters_ordered_by_vote_time_not_api_order(fake):
    ids = list(range(1, 31))
    random.Random(1).shuffle(ids)
    for n, uid in enumerate(ids):
        fake.vote(OPT_A, [uid], start=POLL_DATE + timedelta(minutes=uid))  # earlier id = earlier vote
    random.Random(2).shuffle(fake.votes[OPT_A])  # API order is scrambled
    got = voters(fake)
    assert [v.id for v in got] == list(range(1, 31))
    assert [v.position for v in got] == list(range(1, 31))


def test_my_own_vote_never_takes_a_slot(fake):
    fake.vote(OPT_A, [ME, 1, 2, 3])
    got = voters(fake)
    assert [v.id for v in got] == [1, 2, 3]
    assert got[0].position == 1


def test_pagination_fetches_every_voter(fake):
    fake.vote(OPT_A, range(1, 238), step=timedelta(seconds=7))
    got = voters(fake)
    assert len(got) == 237
    assert [v.id for v in got] == list(range(1, 238))


def test_same_second_votes_keep_true_order(fake):
    fake.vote(OPT_A, [10, 11, 12], step=timedelta(0))  # all in the same second
    assert [v.id for v in voters(fake)] == [10, 11, 12]


def test_vote_without_time_goes_last(fake):
    fake.vote(OPT_A, [1, 2])
    fake.users[3] = user(3)
    fake.votes[OPT_A].insert(0, (3, None))
    assert [v.id for v in voters(fake)] == [1, 2, 3]


def test_options_are_counted_separately(fake):
    fake.vote(OPT_A, [1, 2])
    fake.vote(OPT_B, [3])
    assert [v.id for v in voters(fake, OPT_A)] == [1, 2]
    assert [v.id for v in voters(fake, OPT_B)] == [3]


def test_vote_required_gives_friendly_message(fake):
    fake.vote_required = True
    with pytest.raises(tg.TgError, match="voted in this poll yourself"):
        voters(fake)


def test_anonymous_poll_is_refused(fake):
    fake.anonymous = True
    with pytest.raises(tg.TgError, match="anonymous"):
        tg.run(tg.preview(CHAT, POLL_MSG, OPT_A.hex(), "x", 20))


def test_users_without_handle(fake):
    fake.users[1] = user(1, username=False)
    fake.vote(OPT_A, [1])
    v = voters(fake)[0]
    assert v.handle == "" and v.name == "Climber1"


# ---------------------------------------------------------------- first run

def test_first_run_creates_group_and_adds_first_20(fake):
    fake.vote(OPT_A, range(1, 26))
    r = run_option(fake)
    rec = store.get_record(store.record_key(CHAT, POLL_MSG, OPT_A.hex()))
    gid = rec["group_id"]
    assert r["created"] and r["key"] == store.record_key(CHAT, POLL_MSG, OPT_A.hex())
    assert rec["poll_date"] and rec["option"].startswith("28 Oct")
    assert fake.members[gid] == {ME, *range(1, 21)}
    s = statuses(r)
    assert all(s[i] == "Added" for i in range(1, 21))
    assert all(s[i] == "Not in first 20" for i in range(21, 26))
    assert gid in fake.history_visible
    assert gid not in fake.group_posts  # welcome messages are a separate step now
    assert fake.dms == {}


def test_custom_cap(fake):
    fake.vote(OPT_A, range(1, 10))
    r = run_option(fake, cap=5)
    assert sum(s == "Added" for s in statuses(r).values()) == 5


def test_run_with_no_voters_does_not_crash(fake):
    r = run_option(fake)
    assert r["voters"] == [] and r["created"]


# ---------------------------------------------------------------- re-runs

def test_rerun_10_then_25_adds_the_next_10_only(fake):
    fake.vote(OPT_A, range(1, 11))
    first = run_option(fake)
    assert sum(s == "Added" for s in statuses(first).values()) == 10

    fake.vote(OPT_A, range(11, 26))
    second = run_option(fake)
    s = statuses(second)
    assert not second["created"]
    assert [i for i in s if s[i] == "Already in group"] == list(range(1, 11))
    assert [i for i in s if s[i] == "Added"] == list(range(11, 21))
    assert [i for i in s if s[i] == "Not in first 20"] == list(range(21, 26))
    assert len(fake.groups) == 1


def test_cancellation_moves_21st_person_up(fake):
    fake.vote(OPT_A, range(1, 23))
    run_option(fake)
    fake.votes[OPT_A] = [v for v in fake.votes[OPT_A] if v[0] != 5]  # #5 un-votes
    r = run_option(fake)
    s = statuses(r)
    assert s[21] == "Added"            # moved up into the top 20
    assert s[22] == "Not in first 20"
    assert 5 not in s                   # not a voter any more; app never removes anyone
    gid = next(iter(fake.groups))
    assert 5 in fake.members[gid]


def test_revote_moves_to_back(fake):
    fake.vote(OPT_A, range(1, 22))
    fake.votes[OPT_A] = [v for v in fake.votes[OPT_A] if v[0] != 1]
    fake.vote(OPT_A, [1], start=POLL_DATE + timedelta(hours=5))
    s = statuses(run_option(fake))
    assert s[1] == "Not in first 20" and s[21] == "Added"


# ---------------------------------------------------------------- people who can't be added

def test_privacy_blocked_people_get_the_link_once(fake):
    fake.vote(OPT_A, range(1, 6))
    fake.privacy_block = {2, 4}
    r = run_option(fake)
    s = statuses(r)
    assert s[2] == s[4] == "Invite link sent"
    assert set(fake.dms) == {2, 4}
    assert "https://t.me/+group" in fake.dms[2][0]
    assert "Climber2" in fake.dms[2][0] and "28 Oct" in fake.dms[2][0]

    r2 = run_option(fake)  # run again: no second message
    assert len(fake.dms[2]) == 1
    assert statuses(r2)[2] == "Invite link sent"


def test_silent_add_failure_is_caught_by_member_check(fake):
    fake.vote(OPT_A, [1, 2])
    fake.silent_fail = {2}
    s = statuses(run_option(fake))
    assert s[1] == "Added" and s[2] == "Invite link sent"


def test_cannot_add_or_message_is_flagged(fake):
    fake.vote(OPT_A, [1, 2])
    fake.privacy_block = {2}
    fake.dm_blocked = {2}
    r = run_option(fake)
    v2 = next(v for v in r["voters"] if v.id == 2)
    assert v2.status.startswith("NOT REACHED")
    assert "Privacy" in v2.note and "blocked" in v2.note


def test_invite_link_reused_between_runs(fake):
    fake.vote(OPT_A, [1])
    fake.privacy_block = {1, 2}
    link1 = run_option(fake)["link"]
    fake.vote(OPT_A, [2])
    link2 = run_option(fake)["link"]
    assert link1 == link2


def test_no_invite_link_permission(fake):
    fake.vote(OPT_A, [1])
    fake.privacy_block = {1}
    fake.invite_link_error = True
    r = run_option(fake)
    assert "invite link" in r["stopped"]
    assert statuses(r)[1].startswith("NOT REACHED")


def test_dm_template_with_stray_braces(fake):
    fake.vote(OPT_A, [1])
    fake.privacy_block = {1}
    run_option(fake, dm="Hey {name} {unknown} {{ }} {link}")
    assert "{unknown}" in fake.dms[1][0]


# ---------------------------------------------------------------- Telegram rate limits

def test_flood_wait_stops_safely_and_rerun_continues(fake):
    fake.vote(OPT_A, range(1, 21))
    fake.privacy_block = {3}
    fake.flood_after = 5
    r = run_option(fake)
    assert "slow down" in r["stopped"]
    s = statuses(r)
    assert sum(x == "Added" for x in s.values()) == 4  # #3 failed on privacy
    assert fake.dms == {}                    # stopped before messaging

    fake.flood_after = None
    r2 = run_option(fake)
    s2 = statuses(r2)
    assert r2["stopped"] is None
    assert sum(x in ("Added", "Already in group") for x in s2.values()) == 19
    assert s2[3] == "Invite link sent"


def test_short_flood_wait_is_retried(fake, monkeypatch):
    fake.vote(OPT_A, [1, 2])
    calls = {"n": 0}
    real_add = fake._add

    def add_once_flooded(group, u):
        calls["n"] += 1
        if calls["n"] == 2:  # second add: "wait 0 seconds", then the retry works
            raise tg.errors.FloodWaitError(None, capture=0)
        return real_add(group, u)
    monkeypatch.setattr(fake, "_add", add_once_flooded)
    r = run_option(fake)
    assert r["stopped"] is None
    assert all(s == "Added" for s in statuses(r).values())


def test_peer_flood_on_messages_stops(fake):
    fake.vote(OPT_A, [1, 2])
    fake.privacy_block = {1, 2}
    fake.peer_flood_on_dm = True
    r = run_option(fake)
    assert "limited messaging" in r["stopped"]
    assert all(s.startswith("NOT REACHED") for s in statuses(r).values())


# ---------------------------------------------------------------- finding existing groups

def test_existing_group_found_by_name(fake):
    g = fake.make_group("28 Oct Recre @ B+ Aperia", members={1})
    fake.vote(OPT_A, [1, 2])
    info = tg.run(tg.preview(CHAT, POLL_MSG, OPT_A.hex(), "28 oct recre @ b+ aperia", 20))
    assert info["found_by"] == "name" and info["group"] is g
    r = run_option(fake)
    assert not r["created"]
    assert statuses(r) == {1: "Already in group", 2: "Added"}


def test_last_years_group_with_same_name_is_ignored(fake):
    fake.make_group("28 Oct Recre @ B+ Aperia", date=POLL_DATE - timedelta(days=365))
    fake.vote(OPT_A, [1])
    r = run_option(fake)
    assert r["created"]
    assert len(fake.groups) == 2


def test_deleted_group_gets_recreated(fake):
    fake.vote(OPT_A, [1])
    run_option(fake)
    gid = next(iter(fake.groups))
    del fake.groups[gid]
    fake.dialogs = [d for d in fake.dialogs if d.entity is None]
    r = run_option(fake)
    assert r["created"] and statuses(r)[1] == "Added"


def test_renamed_group_still_found_from_record(fake):
    fake.vote(OPT_A, [1])
    run_option(fake)
    gid = next(iter(fake.groups))
    fake.groups[gid].title = "Renamed by someone"
    r = run_option(fake, title="Renamed by someone")
    assert not r["created"]
    assert getattr(fake, "renames", 0) == 0


def test_typing_a_new_name_renames_the_existing_group(fake):
    fake.vote(OPT_A, [1])
    run_option(fake, title="Option 1")
    gid = next(iter(fake.groups))
    fake.vote(OPT_A, [2])
    r = run_option(fake, title="28 Oct Recre @ GU")
    assert not r["created"] and len(fake.groups) == 1
    assert fake.groups[gid].title == "28 Oct Recre @ GU"
    assert r["title"] == "28 Oct Recre @ GU"
    assert store.get_record(store.record_key(CHAT, POLL_MSG, OPT_A.hex()))["title"] == "28 Oct Recre @ GU"
    assert statuses(r) == {1: "Already in group", 2: "Added"}


def test_same_name_does_not_rename(fake):
    fake.vote(OPT_A, [1])
    run_option(fake, title="Option 1")
    run_option(fake, title="Option 1")
    assert getattr(fake, "renames", 0) == 0


def test_first_run_uses_the_typed_name(fake):
    fake.vote(OPT_A, [1])
    r = run_option(fake, title="My own name")
    assert r["created"] and next(iter(fake.groups.values())).title == "My own name"


def test_old_basic_group_uses_basic_add(fake):
    fake.make_group("28 Oct Recre @ B+ Aperia", basic=True)
    fake.vote(OPT_A, [1])
    assert statuses(run_option(fake)) == {1: "Added"}


def test_two_options_get_two_groups(fake):
    fake.vote(OPT_A, [1, 2])
    fake.vote(OPT_B, [3])
    run_option(fake, OPT_A, title="28 Oct Recre @ B+ Aperia")
    run_option(fake, OPT_B, title="30 Oct Recre @ BP TS")
    assert len(fake.groups) == 2


# ---------------------------------------------------------------- chats and polls

def test_resolve_chat(fake):
    fake.dialogs.append(type(fake.dialogs[0])(id=-5, name="SMU Climbing Exco", is_group=True,
                                              is_channel=True, entity=None))
    assert tg.run(tg.resolve_chat("smu climbing club")) == CHAT
    assert tg.run(tg.resolve_chat("  Exco ")) == -5
    with pytest.raises(tg.TgError, match="Several chats"):
        tg.run(tg.resolve_chat("SMU"))
    with pytest.raises(tg.TgError, match="No chat found"):
        tg.run(tg.resolve_chat("nope"))
    assert tg.run(tg.resolve_chat("@smuclimb")) == -1000000000123
    with pytest.raises(tg.TgError):
        tg.run(tg.resolve_chat("@doesnotexist"))


def test_list_polls_reads_options_and_counts(fake):
    fake.vote(OPT_A, [1, 2, 3])
    polls = tg.run(tg.list_polls(CHAT))
    assert polls[0]["question"] == "WEEK 11 RECRE 🧗"
    assert [o["votes"] for o in polls[0]["options"]] == [3, 0]
    assert not polls[0]["anonymous"]


def test_list_polls_limit(fake):
    fake.extra_polls = [fake.poll_message(msg_id=i) for i in range(100, 130)]
    assert len(tg.run(tg.list_polls(CHAT, limit=10))) == 10


def test_missing_poll_message(fake):
    with pytest.raises(tg.TgError, match="couldn't be found"):
        tg.run(tg.get_poll(CHAT, 424242))


@pytest.mark.parametrize("text,title", [
    ("28 Oct 730pm-930pm @B+ Aperia w/Darryl", "28 Oct Recre @ B+ Aperia"),
    ("30 Oct 4pm-6pm @BP TS w/Irina", "30 Oct Recre @ BP TS"),
    ("1 Nov 2pm @ Ground Up", "1 Nov Recre @ Ground Up"),
    ("Can't make it 😢", "Can't make it 😢"),
    ("", ""),
    ("x" * 300, "x" * 128),
])
def test_suggest_title(text, title):
    assert tg.suggest_title(text) == title


# ---------------------------------------------------------------- stress

def test_stress_1000_voters_with_mixed_failures(fake):
    fake.vote(OPT_A, range(1, 1001), step=timedelta(seconds=1))
    rng = random.Random(42)
    fake.privacy_block = set(rng.sample(range(1, 1001), 150))
    fake.dm_blocked = set(rng.sample(sorted(fake.privacy_block), 40))
    r = run_option(fake, cap=300)
    s = statuses(r)
    assert len(s) == 1000
    top = range(1, 301)
    assert sum(s[i] == "Not in first 300" for i in range(301, 1001)) == 700
    for i in top:
        if i not in fake.privacy_block:
            assert s[i] == "Added"
        elif i in fake.dm_blocked:
            assert s[i].startswith("NOT REACHED")
        else:
            assert s[i] == "Invite link sent"
    gid = next(iter(fake.groups))
    assert len(fake.members[gid]) == 1 + sum(1 for i in top if i not in fake.privacy_block)


def test_stress_many_reruns_are_stable(fake):
    for wave in range(10):
        fake.vote(OPT_A, range(wave * 5 + 1, wave * 5 + 6))
        r = run_option(fake)
    s = statuses(r)
    assert sum(x in ("Added", "Already in group") for x in s.values()) == 20
    assert len(fake.groups) == 1
    assert fake.members[next(iter(fake.groups))] == {ME, *range(1, 21)}


# ---------------------------------------------------------------- invite message details

def test_invite_message_fills_session_details(fake):
    fake.vote(OPT_A, [1])
    fake.privacy_block = {1}
    run_option(fake, dm="Hi {name}! You're confirmed for {date} Recreational Session!🧗 "
                        "{day} {time} at {location}: {link}")
    text = fake.dms[1][0]
    assert text.startswith("Hi Climber1! You're confirmed for 28 Oct Recreational Session!🧗 ")
    assert "Wednesday 7.30pm-9.30pm at B+ Aperia: https://t.me/+group" in text
    assert "{" not in text


def test_invite_message_date_falls_back_to_option(fake):
    fake.extra_polls = [fake.poll_message(msg_id=77, options={OPT_A: "Friday session (TBC)"})]
    fake.vote(OPT_A, [1])
    fake.privacy_block = {1}
    tg.run(tg.run_option(CHAT, 77, OPT_A.hex(), "Friday", 20, "Confirmed for {date}!", progress=lambda *a: None))
    assert fake.dms[1][0] == "Confirmed for Friday session (TBC)!"
