"""Small JSON stores kept in data/ (never committed to git).

config.json  - Telegram API id/hash, last-used chat, settings and exco handles
records.json - which group was made for which poll option, its invite link,
               and who has already been sent that link
"""
import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
EXPORT_DIR = BASE_DIR / "exports"
SESSION_PATH = DATA_DIR / "telegram"  # Telethon adds ".session"

DATA_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)

_CONFIG = DATA_DIR / "config.json"
_RECORDS = DATA_DIR / "records.json"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_config():
    return _read(_CONFIG, {})


def update_config(**changes):
    cfg = load_config()
    cfg.update(changes)
    _write(_CONFIG, cfg)
    return cfg


_HANDLE = re.compile(r"[a-z][a-z0-9_]{3,31}$")  # Telegram usernames: 4-32 chars


def parse_handles(text):
    """'@Alice, t.me/bob\\ncarol' -> (['alice', 'bob', 'carol'], [entries that aren't handles])."""
    good, bad = [], []
    for raw in re.split(r"[\s,;]+", text or ""):
        h = re.sub(r"^(https?://)?(www\.)?(t\.me/|telegram\.me/)", "", raw.strip(), flags=re.I).lstrip("@").lower()
        if not h:
            continue
        if _HANDLE.match(h):
            if h not in good:
                good.append(h)
        else:
            bad.append(raw.strip())
    return good, bad


def exco_handles():
    return set(load_config().get("exco", []))


def record_key(chat_id, msg_id, option_hex):
    return f"{chat_id}:{msg_id}:{option_hex}"


def get_record(key):
    return _read(_RECORDS, {}).get(key)


def all_records():
    return _read(_RECORDS, {})


def save_record(key, record):
    records = _read(_RECORDS, {})
    records[key] = record
    _write(_RECORDS, records)
