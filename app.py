"""Local web page for turning poll votes into session groups.

Run with start.bat (Windows) or start.sh (Mac), then open http://127.0.0.1:5050
"""
import os
import threading
import uuid
import webbrowser
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)

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
        if step == "code":
            result = tg.run(tg.sign_in(_login_phone.get("phone"), code=request.form["code"].strip()))
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
        return redirect(request.form.get("back") or url_for("edit_templates"))
    return render_template("templates.html", t=welcome.templates(),
                           placeholders=welcome.PLACEHOLDERS, back=request.args.get("back", ""))


@app.route("/option")
@needs_login
def option():
    cfg = store.load_config()
    chat_id = request.args.get("chat", type=int)
    msg_id = request.args.get("msg", type=int)
    opt = request.args["opt"]
    cap = request.args.get("cap", type=int) or cfg.get("cap", DEFAULT_CAP)
    poll = tg.run(tg.get_poll(chat_id, msg_id))
    option_text = poll["options"].get(opt, "")
    title = request.args.get("title") or tg.suggest_title(option_text)
    info = tg.run(tg.preview(chat_id, msg_id, opt, title, cap))
    return render_template("option.html", chat_id=chat_id, msg_id=msg_id, opt=opt, cap=cap,
                           title=title, option_text=option_text, info=info,
                           dm=cfg.get("dm_template", DEFAULT_DM),
                           values=welcome.guess(option_text, poll["date"]),
                           placeholders=welcome.PLACEHOLDERS, templates=welcome.templates())


@app.post("/run")
@needs_login
def run():
    if any(not j["done"] for j in _jobs.values()):
        flash("A run is already in progress. Wait for it to finish first.", "error")
        return redirect(request.referrer or url_for("index"))
    f = request.form
    chat_id, msg_id, opt = int(f["chat"]), int(f["msg"]), f["opt"]
    cap = max(1, int(f["cap"]))
    title = f["title"].strip()[:128]
    dm = f["dm"]
    store.update_config(cap=cap, dm_template=dm)

    posts = None
    if f.get("post_welcome"):
        welcome.remember_place({k: f.get(k, "").strip() for k in welcome.PLACEHOLDERS})
        posts = {"welcome": f["welcome_text"], "meet": f["meet_text"],
                 "poll_question": f["poll_question"],
                 "poll_options": f["poll_options"].splitlines()}

    job_id = uuid.uuid4().hex
    job = _jobs[job_id] = {"done": False, "message": "Starting", "step": None, "total": None,
                           "log": [], "result": None, "sheet": None, "error": None,
                           "cap": cap, "chat_id": chat_id}

    def progress(message, done=None, total=None):
        job.update(message=message, step=done, total=total)
        job["log"].append(message)

    def work():
        try:
            result = tg.run(tg.run_option(chat_id, msg_id, opt, title, cap, dm,
                                          welcome=posts, progress=progress))
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


@app.route("/exports/<path:name>")
def download(name):
    return send_from_directory(store.EXPORT_DIR, name, as_attachment=True)


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
