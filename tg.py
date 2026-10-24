"""Everything that talks to Telegram.

Logs in as the captain's own account (not a bot), because bots can't create
groups. Telethon is async, Flask isn't, so Telethon runs on its own event loop
in a background thread and Flask calls into it with run().
"""
import asyncio
import random
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient, errors, functions, types, utils

import store

_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()


def run(coro):
    """Run a coroutine on the Telegram loop and wait for its result."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


class TgError(Exception):
    """An error with a message that is safe to show on the web page."""


@dataclass
class Voter:
    position: int
    user: types.User
    voted_at: datetime

    @property
    def id(self):
        return self.user.id

    @property
    def name(self):
        return " ".join(p for p in (self.user.first_name, self.user.last_name) if p) or "(no name)"

    @property
    def handle(self):
        return f"@{self.user.username}" if self.user.username else ""


def _text(value):
    # Newer Telegram layers wrap poll text in TextWithEntities.
    return getattr(value, "text", value) or ""


def suggest_title(option_text):
    """'28 Oct 730pm-930pm @B+ Aperia w/Darryl' -> '28 Oct Recre @ B+ Aperia'."""
    date = re.match(r"\s*(\d{1,2}\s*[A-Za-z]{3,9})", option_text)
    place = re.search(r"@\s*(.+?)(?:\s+w/.*)?$", option_text)
    if date and place:
        return f"{date.group(1)} Recre @ {place.group(1).strip()}"[:128]
    return option_text.strip()[:128]


# ---------------------------------------------------------------- login

_client = None


async def _get_client():
    global _client
    if _client is None:
        cfg = store.load_config()
        if not cfg.get("api_id") or not cfg.get("api_hash"):
            raise TgError("Telegram API id/hash not set yet.")
        _client = TelegramClient(str(store.SESSION_PATH), int(cfg["api_id"]), cfg["api_hash"])
    if not _client.is_connected():
        await _client.connect()
    return _client


async def reset_client():
    global _client
    if _client is not None:
        await _client.disconnect()
    _client = None


async def is_logged_in():
    client = await _get_client()
    return await client.is_user_authorized()


async def me():
    client = await _get_client()
    return await client.get_me()


async def send_code(phone):
    client = await _get_client()
    try:
        await client.send_code_request(phone)
    except errors.PhoneNumberInvalidError:
        raise TgError("That phone number isn't valid. Include the country code, e.g. +6591234567.")
    except errors.ApiIdInvalidError:
        raise TgError("Telegram rejected the API id/hash. Re-check them on my.telegram.org.")


async def sign_in(phone, code=None, password=None):
    """Returns 'ok' or 'password' (2-step verification needed)."""
    client = await _get_client()
    try:
        if password is not None:
            await client.sign_in(password=password)
        else:
            await client.sign_in(phone, code)
    except errors.SessionPasswordNeededError:
        return "password"
    except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError):
        raise TgError("That code is wrong or expired. Request a new one.")
    except errors.PasswordHashInvalidError:
        raise TgError("Wrong 2-step verification password.")
    return "ok"


async def log_out():
    client = await _get_client()
    await client.log_out()
    await reset_client()


# ---------------------------------------------------------------- polls

async def list_groups():
    """Groups and channels you're in (polls can be posted in either)."""
    client = await _get_client()
    return [
        {"id": d.id, "name": d.name}
        async for d in client.iter_dialogs()
        if d.is_group or d.is_channel
    ]


async def resolve_chat(text):
    """Chat id from a typed name, @username or t.me link."""
    text = text.strip()
    groups = await list_groups()
    exact = [g for g in groups if g["name"].lower() == text.lower()]
    if exact:
        return exact[0]["id"]
    partial = [g for g in groups if text.lower() in g["name"].lower()]
    if len(partial) == 1:
        return partial[0]["id"]
    if len(partial) > 1:
        names = ", ".join(g["name"] for g in partial[:8])
        raise TgError(f"Several chats match '{text}': {names}. Type more of the name.")
    if text.startswith("@") or "t.me/" in text:
        client = await _get_client()
        try:
            return utils.get_peer_id(await client.get_entity(text))
        except (ValueError, errors.RPCError):
            pass
    raise TgError(f"No chat found matching '{text}'. You need to be a member of it.")


async def list_polls(chat_id, limit=10):
    """Most recent polls in a chat from anyone, newest first."""
    client = await _get_client()
    polls = []
    async for m in client.iter_messages(chat_id, limit=limit, filter=types.InputMessagesFilterPoll()):
        if not isinstance(m.media, types.MessageMediaPoll):
            continue
        poll, results = m.media.poll, m.media.results
        counts = {r.option: r.voters for r in (results.results or [])} if results else {}
        polls.append({
            "msg_id": m.id,
            "question": _text(poll.question),
            "date": m.date.astimezone(),
            "closed": poll.closed,
            "anonymous": not poll.public_voters,
            "options": [
                {"hex": a.option.hex(), "text": _text(a.text), "votes": counts.get(a.option)}
                for a in poll.answers
            ],
        })
        if len(polls) >= limit:
            break
    return polls


async def get_poll(chat_id, msg_id):
    client = await _get_client()
    m = await client.get_messages(chat_id, ids=msg_id)
    if not m or not isinstance(m.media, types.MessageMediaPoll):
        raise TgError("That poll message couldn't be found.")
    poll = m.media.poll
    return {
        "msg_id": m.id,
        "question": _text(poll.question),
        "date": m.date,
        "anonymous": not poll.public_voters,
        "options": {a.option.hex(): _text(a.text) for a in poll.answers},
    }


async def get_voters(chat_id, msg_id, option_hex):
    """Everyone who picked this option, earliest vote first (you excluded)."""
    client = await _get_client()
    peer = await client.get_input_entity(chat_id)
    my_id = (await client.get_me()).id
    users, votes, offset = {}, [], None
    while True:
        try:
            res = await client(functions.messages.GetPollVotesRequest(
                peer=peer, id=msg_id, option=bytes.fromhex(option_hex), offset=offset, limit=50))
        except errors.RPCError as e:
            if "POLL_VOTE_REQUIRED" in str(e):
                raise TgError("Telegram only shows who voted once you've voted in this poll yourself "
                              "(or it's closed). Vote or close the poll, then try again. "
                              "Your own vote is never counted toward the 20.")
            if "BROADCAST_FORBIDDEN" in str(e) or "POLL_ANONYMOUS" in str(e):
                raise TgError("This poll is anonymous, so Telegram doesn't reveal who voted.")
            raise
        users.update({u.id: u for u in res.users})
        votes.extend(res.votes)
        offset = res.next_offset
        if not offset:
            break

    # Telegram returns newest first. Reverse, then a stable sort by time keeps
    # votes cast in the same second in their true order.
    # A vote with no time (rare) goes to the back and shows as cast just now.
    never = datetime.now(timezone.utc)
    seen, ordered = set(), []
    for v in sorted(reversed(votes), key=lambda v: (v.date is None, v.date or never)):
        uid = getattr(v.peer, "user_id", None)
        if uid is None or uid == my_id or uid in seen or uid not in users:
            continue
        seen.add(uid)
        ordered.append(Voter(len(ordered) + 1, users[uid], (v.date or never).astimezone()))
    return ordered


# ---------------------------------------------------------------- groups

async def find_group(key, title, poll_date):
    """Existing group for this option: (entity, how) where how is 'record' or 'name'."""
    client = await _get_client()
    rec = store.get_record(key)
    if rec:
        try:
            ent = await client.get_entity(types.PeerChannel(rec["group_id"]))
            if not getattr(ent, "left", False):
                return ent, "record"
        except (ValueError, errors.RPCError):
            pass  # deleted, or we left it
    # Fall back to an exact-name match, ignoring last year's group of the same name.
    earliest = poll_date - timedelta(days=1)
    async for d in client.iter_dialogs(limit=300):
        if d.is_group and d.name.strip().lower() == title.strip().lower():
            if getattr(d.entity, "date", None) and d.entity.date < earliest:
                continue
            return d.entity, "name"
    return None, None


async def member_ids(group):
    client = await _get_client()
    return {p.id for p in await client.get_participants(group)}


async def preview(chat_id, msg_id, option_hex, title, cap):
    poll = await get_poll(chat_id, msg_id)
    if poll["anonymous"]:
        raise TgError("This poll is anonymous, so Telegram doesn't reveal who voted. "
                      "Next time turn off 'Anonymous Voting' when creating the poll.")
    voters = await get_voters(chat_id, msg_id, option_hex)
    key = store.record_key(chat_id, msg_id, option_hex)
    group, how = await find_group(key, title, poll["date"])
    members = await member_ids(group) if group else set()
    rec = store.get_record(key) or {}
    messaged = set(rec.get("messaged", []))
    for v in voters:
        if v.position > cap:
            v.status = f"Not in first {cap}"
        elif v.id in members:
            v.status = "Already in group"
        elif v.id in messaged:
            v.status = "Link sent earlier (not joined yet)"
        else:
            v.status = "Will be added"
    return {"poll": poll, "voters": voters, "group": group, "found_by": how,
            "member_count": len(members),
            "welcome_posted": bool(group) and how == "record" and rec.get("welcome_posted", False)}


async def _pause(lo, hi):
    await asyncio.sleep(random.uniform(lo, hi))


async def _add(client, group, user):
    """Try to add one user. Returns None on success, or a reason it failed."""
    for attempt in range(2):
        try:
            if isinstance(group, types.Chat):  # old-style basic group
                await client(functions.messages.AddChatUserRequest(group.id, user, fwd_limit=0))
            else:
                await client(functions.channels.InviteToChannelRequest(group, [user]))
            return None
        except errors.FloodWaitError as e:
            if attempt == 0 and e.seconds <= 60:
                await asyncio.sleep(e.seconds + 1)
                continue
            raise
        except errors.UserAlreadyParticipantError:
            return None
        except (errors.UserPrivacyRestrictedError, errors.UserNotMutualContactError):
            return "Privacy settings block being added"
        except errors.UserChannelsTooMuchError:
            return "They're in too many groups"
        except errors.UserKickedError:
            return "They were removed from this group before"
        except errors.PeerFloodError:
            raise  # account-wide limit: stop the whole run
        except errors.RPCError as e:
            return f"Telegram error: {e.__class__.__name__}"


async def _dm(client, user, text):
    """Message one user. Returns None on success, or a reason it failed."""
    for attempt in range(2):
        try:
            await client.send_message(user, text, link_preview=False)
            return None
        except errors.FloodWaitError as e:
            if attempt == 0 and e.seconds <= 60:
                await asyncio.sleep(e.seconds + 1)
                continue
            raise
        except errors.UserIsBlockedError:
            return "They've blocked you"
        except errors.PeerFloodError:
            raise  # account-wide limit: stop the whole run
        except errors.RPCError as e:
            return f"Telegram error: {e.__class__.__name__}"


def _fill(template, **values):
    for k, v in values.items():
        template = template.replace("{" + k + "}", str(v))
    return template


async def _post_welcome(client, group, welcome):
    """Post and pin the welcome message, then the meeting message and poll."""
    if welcome["welcome"].strip():
        msg = await client.send_message(group, welcome["welcome"], link_preview=False)
        await client.pin_message(group, msg, notify=True)
    if welcome["meet"].strip():
        await client.send_message(group, welcome["meet"], link_preview=False)
    options = [o.strip() for o in welcome["poll_options"] if o.strip()][:10]
    if welcome["poll_question"].strip() and len(options) >= 2:
        poll = types.Poll(
            id=random.getrandbits(62), hash=0, public_voters=True,
            question=types.TextWithEntities(welcome["poll_question"].strip()[:255], []),
            answers=[types.PollAnswer(types.TextWithEntities(o[:100], []), bytes([i]))
                     for i, o in enumerate(options)])
        await client.send_message(group, file=types.InputMediaPoll(poll))


def _no_progress(message, done=None, total=None):
    print(message)


async def run_option(chat_id, msg_id, option_hex, title, cap, dm_template,
                     welcome=None, progress=_no_progress):
    """Create/reuse the group, add the first `cap` voters, DM the link to the rest.

    welcome: dict of welcome/meet/poll_question/poll_options to post, or None.
    progress(message, done, total) is called as work happens.
    """
    client = await _get_client()
    progress("Checking the poll")
    info = await preview(chat_id, msg_id, option_hex, title, cap)
    poll, voters, group = info["poll"], info["voters"], info["group"]
    option_text = poll["options"].get(option_hex, "")
    key = store.record_key(chat_id, msg_id, option_hex)
    rec = store.get_record(key) or {"messaged": []}

    created = False
    if group is None:
        progress(f"Creating group '{title}'")
        res = await client(functions.channels.CreateChannelRequest(
            title=title, about=f"Recre: {option_text}", megagroup=True))
        group, created = res.chats[0], True
        try:  # so people who join later still see the pinned welcome message
            await client(functions.channels.TogglePreHistoryHiddenRequest(group, False))
        except errors.RPCError:
            pass

    rec.update(group_id=group.id, title=getattr(group, "title", title),
               poll=poll["question"], option=option_text)
    store.save_record(key, rec)

    selected = [v for v in voters if v.position <= cap]
    members = await member_ids(group)
    to_add = [v for v in selected if v.id not in members]
    reasons = {}
    stopped = None
    for i, v in enumerate(to_add, 1):
        progress(f"Adding {i} of {len(to_add)}: {v.name}", i - 1, len(to_add))
        try:
            reasons[v.id] = await _add(client, group, v.user)
        except errors.FloodWaitError as e:
            stopped = f"Telegram says slow down: wait {e.seconds // 60 + 1} min, then run again."
            break
        except errors.PeerFloodError:
            stopped = "Telegram has temporarily limited your account from adding people. Try again later."
            break
        await _pause(2, 4)

    # Don't trust the API replies alone: check who is actually in the group now.
    progress("Checking who is in the group")
    now_members = await member_ids(group)
    missing = [v for v in selected if v.id not in now_members]

    if welcome and not stopped:
        progress("Posting the welcome messages")
        try:
            await _post_welcome(client, group, welcome)
            rec["welcome_posted"] = True
        except errors.RPCError as e:
            stopped = f"Couldn't post the welcome messages ({e.__class__.__name__})."
        store.save_record(key, rec)

    if missing and not stopped and not rec.get("link"):
        try:
            invite = await client(functions.messages.ExportChatInviteRequest(peer=group))
            rec["link"] = invite.link
        except errors.RPCError:
            stopped = "Couldn't make an invite link for this group (are you an admin of it?)."
    if missing and not stopped:
        to_dm = [v for v in missing if v.id not in rec["messaged"]]
        for i, v in enumerate(to_dm, 1):
            progress(f"Sending invite link {i} of {len(to_dm)}: {v.name}", i - 1, len(to_dm))
            text = _fill(dm_template, name=v.user.first_name or v.name, option=option_text,
                         title=rec["title"], link=rec["link"])
            try:
                fail = await _dm(client, v.user, text)
            except (errors.FloodWaitError, errors.PeerFloodError):
                stopped = "Telegram limited messaging for now. The rest still need the link; run again later."
                break
            if fail:
                reasons[v.id] = f"{reasons.get(v.id) or 'Not added'}; couldn't message: {fail}"
            else:
                rec["messaged"].append(v.id)
            await _pause(3, 6)
    store.save_record(key, rec)

    messaged = set(rec["messaged"])
    for v in voters:
        if v.position > cap:
            v.status = f"Not in first {cap}"
        elif v.id in members:
            v.status = "Already in group"
        elif v.id in now_members:
            v.status = "Added"
        elif v.id in messaged:
            v.status = "Invite link sent"
        else:
            v.status = "NOT REACHED - send link manually"
        v.note = reasons.get(v.id) or ""

    return {"poll": poll, "option": option_text, "voters": voters, "title": rec["title"],
            "created": created, "link": rec.get("link"), "stopped": stopped,
            "member_count": len(now_members),
            "welcome_posted": bool(welcome) and rec.get("welcome_posted", False)}
