"""Local web page for turning poll votes into session groups.

Run with start.bat (Windows) or start.sh (Mac), then open http://127.0.0.1:5050
"""
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
import webbrowser
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)
from werkzeug.exceptions import HTTPException

import export
import store
import tg
import welcome

PORT = 5050
DEFAULT_CAP = 20
DEFAULT_DM = ("Hi {name}! You're confirmed for {option} 🧗\n"
              "I couldn't add you to the group directly, so here's the invite link: {link}")

app = Flask(__name__)
app.secret_key = os.urandom(16)
_login_phone = {}
_jobs = {}  # job id -> progress and result of a run


@app.errorhandler(tg.TgError)
def show_tg_error(e):
    if request.method == "POST" and request.referrer:
        flash(str(e), "error")
        return redirect(request.referrer)
    return render_template("error.html", message=str(e)), 400


@app.errorhandler(Exception)
def show_unexpected_error(e):
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("Unexpected error")
    return render_template("error.html", message=f"Something went wrong: {e.__class__.__name__}: {e}"), 500


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _local_path(url):
    """Only follow 'back' links within this app."""
    return url if url and url.startswith("/") and not url.startswith("//") else None


def needs_login(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        cfg = store.load_config()
        if not cfg.get("api_id"):
            return redirect(url_for("setup"))
        if not tg.run(tg.is_logged_in()):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        api_id = request.form["api_id"].strip()
        api_hash = request.form["api_hash"].strip()
        if not api_id.isdigit() or len(api_hash) < 16:
            flash("API id should be a number and API hash a long string of letters/numbers.", "error")
            return redirect(url_for("setup"))
        store.update_config(api_id=api_id, api_hash=api_hash)
        tg.run(tg.reset_client())
        return redirect(url_for("login"))
    return render_template("setup.html", cfg=store.load_config())


@app.route("/login", methods=["GET", "POST"])
def login():
    step = request.args.get("step", "phone")
    if request.method == "POST":
        if step == "phone":
            phone = request.form["phone"].replace(" ", "")
            tg.run(tg.send_code(phone))
            _login_phone["phone"] = phone
            return redirect(url_for("login", step="code"))
        if not _login_phone.get("phone"):
            flash("Start again with your phone number.", "error")
            return redirect(url_for("login"))
        if step == "code":
            result = tg.run(tg.sign_in(_login_phone["phone"], code=request.form["code"].strip()))
        else:
            result = tg.run(tg.sign_in(None, password=request.form["password"]))
        if result == "password":
            return redirect(url_for("login", step="password"))
        return redirect(url_for("index"))
    return render_template("login.html", step=step)


@app.post("/logout")
def logout():
    tg.run(tg.log_out())
    flash("Logged out of Telegram on this computer.", "info")
    return redirect(url_for("login"))


@app.route("/")
@needs_login
def index():
    cfg = store.load_config()
    groups = tg.run(tg.list_groups())
    typed = request.args.get("q", "").strip()
    if typed:
        try:
            chat_id = tg.run(tg.resolve_chat(typed))
        except tg.TgError as e:
            flash(str(e), "error")
            return render_template("index.html", groups=groups, chat_id=None, chat_name=typed,
                                   polls=[], me=tg.run(tg.me()))
        store.update_config(chat_id=chat_id)
    else:
        chat_id = request.args.get("chat", type=int) or cfg.get("chat_id")
    chat_name = next((g["name"] for g in groups if g["id"] == chat_id), "")
    polls = tg.run(tg.list_polls(chat_id)) if chat_id else []
    return render_template("index.html", groups=groups, chat_id=chat_id, chat_name=chat_name,
                           polls=polls, me=tg.run(tg.me()))


@app.route("/templates", methods=["GET", "POST"])
@needs_login
def edit_templates():
    if request.method == "POST":
        if "reset" in request.form:
            store.update_config(welcome_templates={})
            flash("Welcome templates reset to the defaults.", "info")
        else:
            welcome.save_templates(**request.form)
            flash("Welcome templates saved.", "info")
        return redirect(_local_path(request.form.get("back")) or url_for("edit_templates"))
    return render_template("templates.html", t=welcome.templates(), placeholders=welcome.PLACEHOLDERS,
                           back=_local_path(request.args.get("back")) or "")


@app.route("/option")
@needs_login
def option():
    cfg = store.load_config()
    chat_id = request.args.get("chat", type=int)
    msg_id = request.args.get("msg", type=int)
    opt = request.args.get("opt", "")
    if not chat_id or not msg_id or not opt or not all(c in "0123456789abcdef" for c in opt.lower()) \
            or len(opt) % 2:
        abort(400)
    cap = max(1, request.args.get("cap", type=int) or cfg.get("cap", DEFAULT_CAP))
    poll = tg.run(tg.get_poll(chat_id, msg_id))
    option_text = poll["options"].get(opt, "")
    title = request.args.get("title") or tg.suggest_title(option_text)
    info = tg.run(tg.preview(chat_id, msg_id, opt, title, cap))
    return render_template("option.html", chat_id=chat_id, msg_id=msg_id, opt=opt, cap=cap,
                           title=title, option_text=option_text, info=info,
                           dm=cfg.get("dm_template", DEFAULT_DM))


@app.post("/run")
@needs_login
def run():
    if any(not j["done"] for j in _jobs.values()):
        flash("A run is already in progress. Wait for it to finish first.", "error")
        return redirect(request.referrer or url_for("index"))
    f = request.form
    chat_id, msg_id, opt = _int(f.get("chat"), 0), _int(f.get("msg"), 0), f.get("opt", "")
    if not chat_id or not msg_id or not opt:
        abort(400)
    cap = max(1, _int(f.get("cap"), DEFAULT_CAP))
    title = f.get("title", "").strip()[:128]
    if not title:
        flash("The group needs a name.", "error")
        return redirect(request.referrer or url_for("index"))
    dm = f.get("dm") or DEFAULT_DM
    store.update_config(cap=cap, dm_template=dm)

    job_id = uuid.uuid4().hex
    job = _jobs[job_id] = {"done": False, "message": "Starting", "step": None, "total": None,
                           "log": [], "result": None, "sheet": None, "error": None,
                           "cap": cap, "chat_id": chat_id}

    def progress(message, done=None, total=None):
        job.update(message=message, step=done, total=total)
        job["log"].append(message)

    def work():
        try:
            result = tg.run(tg.run_option(chat_id, msg_id, opt, title, cap, dm, progress=progress))
            job["sheet"] = export.write_run(result["title"], result["voters"], cap)
            job["result"] = result
        except tg.TgError as e:
            job["error"] = str(e)
        except Exception as e:  # show it on the page instead of failing silently
            job["error"] = f"Something went wrong: {e.__class__.__name__}: {e}"
        job["done"] = True

    threading.Thread(target=work, daemon=True).start()
    return redirect(url_for("job_page", job_id=job_id))


@app.route("/job/<job_id>")
def job_page(job_id):
    job = _jobs.get(job_id) or abort(404)
    if job["done"] and job["result"]:
        return render_template("result.html", r=job["result"], cap=job["cap"],
                               sheet=job["sheet"], chat_id=job["chat_id"])
    return render_template("progress.html", job_id=job_id, job=job)


@app.route("/job/<job_id>/status")
def job_status(job_id):
    job = _jobs.get(job_id) or abort(404)
    return jsonify({k: job[k] for k in ("done", "message", "step", "total", "log", "error")})


def _split_key(key):
    chat, msg, opt = key.split(":")
    return int(chat), int(msg), opt


@app.route("/groups")
@needs_login
def groups():
    rows = []
    for key, rec in store.all_records().items():
        chat_id, msg_id, opt = _split_key(key)
        rows.append({"key": key, "chat_id": chat_id, "msg_id": msg_id, "opt": opt, **rec})
    rows.sort(key=lambda r: r.get("poll_date", ""), reverse=True)
    return render_template("groups.html", rows=rows, me=tg.run(tg.me()))


@app.route("/messages", methods=["GET", "POST"])
@needs_login
def messages():
    key = request.values.get("key", "")
    if key.count(":") != 2:
        abort(400)
    rec, group = tg.run(tg.record_group(key))

    if request.method == "POST":
        f = request.form
        posts = {"welcome": f.get("welcome_text", ""), "meet": f.get("meet_text", ""),
                 "poll_question": f.get("poll_question", ""),
                 "poll_options": f.get("poll_options", "").splitlines()}
        when = None
        if f.get("when_mode") == "schedule":
            try:
                when = datetime.fromisoformat(f.get("when", "")).astimezone().astimezone(timezone.utc)
            except ValueError:
                flash("Pick the date and time to schedule the messages for.", "error")
                return redirect(url_for("messages", key=key))
        welcome.remember_place({k: f.get(k, "").strip() for k in welcome.PLACEHOLDERS})
        sent = tg.run(tg.send_messages(key, posts, when=when, pin=bool(f.get("pin"))))
        if not sent:
            flash("Nothing was sent: all the messages were empty.", "error")
        elif when:
            local = when.astimezone()
            nice = (local.strftime("%a %d %b, %I.%M") + local.strftime("%p").lower()).replace(" 0", " ")
            flash(f"Scheduled the {', '.join(sent)} for {nice}. "
                  "You can see or cancel them in Telegram (the clock icon in the group's message box).", "info")
        else:
            flash(f"Sent the {', '.join(sent)}.", "info")
        return redirect(url_for("messages", key=key))

    poll_date = datetime.fromisoformat(rec["poll_date"]) if rec.get("poll_date") else datetime.now(timezone.utc)
    values, examples = welcome.with_examples(welcome.guess(rec.get("option", ""), poll_date))
    default_when = (datetime.now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    history = [dict(m, at=datetime.fromisoformat(m["at"]).astimezone()) for m in rec.get("messages", [])]
    return render_template("messages.html", key=key, rec=rec, group=group, values=values, examples=examples,
                           placeholders=welcome.PLACEHOLDERS, templates=welcome.templates(),
                           history=history, pending_pins=len(rec.get("pending_pins") or []),
                           default_when=default_when.strftime("%Y-%m-%dT%H:%M"), me=tg.run(tg.me()))


def _pin_scheduled_messages_forever():
    """While the app is open, pin scheduled welcome messages once Telegram sends them."""
    while True:
        try:
            if store.load_config().get("api_id") and tg.run(tg.is_logged_in()):
                tg.run(tg.pin_due())
        except Exception:
            app.logger.exception("Pinning scheduled messages failed; will retry")
        time.sleep(60)


@app.route("/exports/<path:name>")
def download(name):
    return send_from_directory(store.EXPORT_DIR, name, as_attachment=True)


if __name__ == "__main__":
    threading.Thread(target=_pin_scheduled_messages_forever, daemon=True).start()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
