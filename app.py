"""Local web page for turning poll votes into session groups.

Run with start.bat (Windows) or start.sh (Mac), then open http://127.0.0.1:5050
"""
import os
import threading
import webbrowser
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for

import export
import store
import tg

PORT = 5050
DEFAULT_CAP = 20
DEFAULT_DM = ("Hi {name}! You're confirmed for {option} 🧗\n"
              "I couldn't add you to the group directly, so here's the invite link: {link}")

app = Flask(__name__)
app.secret_key = os.urandom(16)
_login_phone = {}


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
    chat_id = request.args.get("chat", type=int) or cfg.get("chat_id")
    if chat_id and request.args.get("chat"):
        store.update_config(chat_id=chat_id)
    polls = tg.run(tg.list_polls(chat_id)) if chat_id else []
    return render_template("index.html", groups=groups, chat_id=chat_id, polls=polls,
                           me=tg.run(tg.me()))


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
                           dm=cfg.get("dm_template", DEFAULT_DM))


@app.post("/run")
@needs_login
def run():
    f = request.form
    chat_id, msg_id, opt = int(f["chat"]), int(f["msg"]), f["opt"]
    cap = max(1, int(f["cap"]))
    title = f["title"].strip()[:128]
    store.update_config(cap=cap, dm_template=f["dm"])
    result = tg.run(tg.run_option(chat_id, msg_id, opt, title, cap, f["dm"]))
    sheet = export.write_run(result["title"], result["voters"], cap)
    return render_template("result.html", r=result, cap=cap, sheet=sheet, chat_id=chat_id)


@app.route("/exports/<path:name>")
def download(name):
    return send_from_directory(store.EXPORT_DIR, name, as_attachment=True)


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
