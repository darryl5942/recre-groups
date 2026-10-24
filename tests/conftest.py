"""A fake Telegram so the whole app can be tested without a real account.

FakeTelegram stands in for Telethon's client: it keeps chats, polls, votes,
groups and sent messages in memory, and can be told to misbehave the way real
Telegram does (privacy blocks, rate limits, blocked messages...).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from telethon import errors, functions, types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import export  # noqa: E402
import store  # noqa: E402
import tg  # noqa: E402

ME = 10 ** 9
CHAT = -100123
POLL_MSG = 5
POLL_DATE = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
OPT_A = b"\x00"
OPT_B = b"\x01"
OPTIONS = {OPT_A: "28 Oct 730pm-930pm @B+ Aperia w/Darryl", OPT_B: "30 Oct 4pm-6pm @BP TS w/Irina"}


def user(uid, username=True):
    return types.User(id=uid, first_name=f"Climber{uid}", last_name=None,
                      username=f"climber{uid}" if username else None, access_hash=uid * 7)


class FakeTelegram:
    def __init__(self):
        self.users = {ME: user(ME)}
        self.votes = {}            # option bytes -> [(user id, date or None)] in vote order
        self.anonymous = False
        self.vote_required = False
        self.groups = {}           # group id -> entity
        self.members = {}          # group id -> set of user ids
        self.dialogs = [SimpleNamespace(id=CHAT, name="SMU Climbing Club", is_group=True,
                                        is_channel=True, entity=None)]
        self.extra_polls = []      # more poll messages in the chat
        # misbehaviour switches
        self.privacy_block = set()  # can't be added (error)
        self.silent_fail = set()    # "added" but never actually join
        self.dm_blocked = set()     # can't be messaged
        self.flood_after = None     # raise FloodWait after this many adds
        self.flood_seconds = 600
        self.peer_flood_on_dm = False
        self.invite_link_error = False
        # what happened
        self.adds = 0
        self.dms = {}               # user id -> [text]
        self.group_posts = {}       # group id -> [text or poll]
        self.pinned = {}            # group id -> message id
        self.history_visible = set()
        self._next_id = 5000

    # -- helpers for tests
    def vote(self, option, uids, start=None, step=timedelta(minutes=1)):
        """Votes cast one after another, carrying on after the previous call's votes."""
        t = start or getattr(self, "_last_vote", POLL_DATE) + step
        for uid in uids:
            self.users.setdefault(uid, user(uid))
            self.votes.setdefault(option, []).append((uid, t))
            self._last_vote = t
            t += step

    def make_group(self, title, date=None, members=(), basic=False):
        self._next_id += 1
        gid = self._next_id
        if basic:
            ent = types.Chat(id=gid, title=title, photo=types.ChatPhotoEmpty(), participants_count=1,
                             date=date or POLL_DATE, version=1)
        else:
            ent = SimpleNamespace(id=gid, title=title, date=date or POLL_DATE + timedelta(hours=1), left=False)
        self.groups[gid] = ent
        self.members[gid] = {ME, *members}
        self.dialogs.append(SimpleNamespace(id=-gid, name=title, is_group=True, is_channel=not basic, entity=ent))
        return ent

    def poll_message(self, msg_id=POLL_MSG, question="WEEK 11 RECRE 🧗", options=None):
        options = options or OPTIONS
        poll = types.Poll(id=1, hash=0, public_voters=not self.anonymous,
                          question=types.TextWithEntities(question, []),
                          answers=[types.PollAnswer(types.TextWithEntities(t, []), o) for o, t in options.items()])
        results = types.PollResults(results=[types.PollAnswerVoters(option=o, voters=len(self.votes.get(o, [])))
                                             for o in options])
        return SimpleNamespace(id=msg_id, date=POLL_DATE, media=types.MessageMediaPoll(poll=poll, results=results))

    # -- the client API used by tg.py
    def is_connected(self):
        return True

    async def connect(self):
        pass

    async def is_user_authorized(self):
        return True

    async def get_me(self):
        return self.users[ME]

    async def get_input_entity(self, peer):
        return peer

    async def get_entity(self, peer):
        if isinstance(peer, types.PeerChannel):
            if peer.channel_id in self.groups:
                return self.groups[peer.channel_id]
            raise ValueError("Could not find the input entity")
        if isinstance(peer, str) and peer.lstrip("@").lower() == "smuclimb":
            return types.Channel(id=123, title="SMU Climbing Club", photo=types.ChatPhotoEmpty(),
                                 date=POLL_DATE, megagroup=True, access_hash=1)
        raise ValueError("No user has that username")

    async def get_messages(self, chat, ids):
        for m in [self.poll_message(), *self.extra_polls]:
            if m.id == ids:
                return m
        return None

    async def iter_messages(self, chat, limit=None, filter=None):
        for m in [*self.extra_polls, self.poll_message()][:limit]:
            yield m

    async def iter_dialogs(self, limit=None):
        for d in self.dialogs[:limit]:
            yield d

    async def get_participants(self, group):
        return [SimpleNamespace(id=uid) for uid in self.members[group.id]]

    async def send_message(self, entity, message=None, file=None, link_preview=True):
        if isinstance(entity, types.User):
            if self.peer_flood_on_dm:
                raise errors.PeerFloodError(None)
            if entity.id in self.dm_blocked:
                raise errors.UserIsBlockedError(None)
            self.dms.setdefault(entity.id, []).append(message)
        else:
            self.group_posts.setdefault(entity.id, []).append(file.poll if file else message)
        self._next_id += 1
        return SimpleNamespace(id=self._next_id)

    async def pin_message(self, group, msg, notify=False):
        self.pinned[group.id] = msg.id

    async def __call__(self, req):
        if isinstance(req, functions.messages.GetPollVotesRequest):
            return self._poll_votes(req)
        if isinstance(req, functions.channels.CreateChannelRequest):
            return SimpleNamespace(chats=[self.make_group(req.title, date=datetime.now(timezone.utc))])
        if isinstance(req, functions.channels.TogglePreHistoryHiddenRequest):
            self.history_visible.add(req.channel.id)
            return None
        if isinstance(req, functions.channels.InviteToChannelRequest):
            return self._add(req.channel, req.users[0])
        if isinstance(req, functions.messages.AddChatUserRequest):
            return self._add(self.groups[req.chat_id], req.user_id)
        if isinstance(req, functions.messages.ExportChatInviteRequest):
            if self.invite_link_error:
                raise errors.ChatAdminRequiredError(None)
            return SimpleNamespace(link=f"https://t.me/+group{req.peer.id}")
        raise NotImplementedError(type(req).__name__)

    def _poll_votes(self, req):
        if self.vote_required:
            raise errors.RPCError(None, "POLL_VOTE_REQUIRED", 400)
        newest_first = list(reversed(self.votes.get(req.option, [])))
        start = int(req.offset or 0)
        page = newest_first[start:start + req.limit]
        more = start + req.limit < len(newest_first)
        return types.messages.VotesList(
            count=len(newest_first),
            votes=[types.MessagePeerVote(types.PeerUser(uid), req.option, date) for uid, date in page],
            chats=[], users=[self.users[uid] for uid, _ in page],
            next_offset=str(start + req.limit) if more else None)

    def _add(self, group, u):
        if self.flood_after is not None and self.adds >= self.flood_after:
            raise errors.FloodWaitError(None, capture=self.flood_seconds)
        self.adds += 1
        if u.id in self.privacy_block:
            raise errors.UserPrivacyRestrictedError(None)
        if u.id in self.silent_fail:
            return SimpleNamespace(missing_invitees=[u.id])
        self.members[group.id].add(u.id)
        return SimpleNamespace(missing_invitees=[])


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """Fresh fake Telegram + empty data folder for every test."""
    f = FakeTelegram()

    async def get_client():
        return f

    async def no_pause(lo, hi):
        pass

    monkeypatch.setattr(tg, "_get_client", get_client)
    monkeypatch.setattr(tg, "_pause", no_pause)
    monkeypatch.setattr(store, "_CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(store, "_RECORDS", tmp_path / "records.json")
    monkeypatch.setattr(store, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(export, "EXPORT_DIR", tmp_path / "exports")
    (tmp_path / "exports").mkdir()
    return f


def run_option(fake, option=OPT_A, cap=20, title="28 Oct Recre @ B+ Aperia", welcome=None,
               dm="Hi {name}! {option} {title} {link}"):
    return tg.run(tg.run_option(CHAT, POLL_MSG, option.hex(), title, cap, dm, welcome=welcome,
                                progress=lambda *a: None))


def statuses(result):
    return {v.id: v.status for v in result["voters"]}
