import hmac
import os
from html import escape

from flask import Flask, redirect, render_template_string, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import settings as config
from bot.forwarder import format_outgoing_message

_DAYS = [
    (0, "Mon"),
    (1, "Tue"),
    (2, "Wed"),
    (3, "Thu"),
    (4, "Fri"),
    (5, "Sat"),
    (6, "Sun"),
]


def _check_admin_login(email: str, password: str) -> bool:
    return hmac.compare_digest((email or "").strip(), config.ADMIN_EMAIL.strip()) and hmac.compare_digest(
        (password or "").strip(), config.ADMIN_PASSWORD.strip()
    )


def _format_days(days_csv: str) -> str:
    wanted = {part.strip() for part in (days_csv or "").split(",") if part.strip()}
    names = [name for idx, name in _DAYS if str(idx) in wanted]
    return ", ".join(names) if names else "-"


def create_panel_app(store, destination_chat_id: str, send_text_callable):
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # Railway proxy headers
    is_railway = any(key.startswith("RAILWAY_") for key in os.environ)
    app.secret_key = config.PANEL_SECRET_KEY
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_railway,
    )

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            email = request.form.get("email", "")
            password = request.form.get("password", "")
            if _check_admin_login(email, password):
                session["admin_ok"] = True
                return redirect(url_for("dashboard"))
            error = "Invalid credentials."
        return render_template_string(
            """
            <!doctype html>
            <html>
            <head>
              <meta charset="utf-8"/>
              <meta name="viewport" content="width=device-width, initial-scale=1"/>
              <title>Shahid Haidar Doghali Panel</title>
              <style>
                :root {
                  --bg0: #081311;
                  --bg1: #0f241f;
                  --bg2: #12352d;
                  --gold1: #d4af37;
                  --gold2: #f0d47a;
                  --emerald1: #0f6b54;
                  --emerald2: #1f8a70;
                  --text: #f6f6f9;
                  --muted: #b8d0c9;
                  --panel: rgba(8, 22, 19, 0.76);
                  --border: rgba(255, 255, 255, 0.12);
                }
                * { box-sizing: border-box; }
                body {
                  margin: 0;
                  min-height: 100vh;
                  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
                  color: var(--text);
                  background:
                    radial-gradient(circle at 10% 10%, rgba(212, 175, 55, 0.22), transparent 35%),
                    radial-gradient(circle at 90% 20%, rgba(31, 138, 112, 0.22), transparent 40%),
                    radial-gradient(circle at 50% 100%, rgba(212, 175, 55, 0.12), transparent 50%),
                    linear-gradient(160deg, var(--bg0), var(--bg1) 55%, var(--bg2));
                  display: grid;
                  place-items: center;
                  padding: 24px;
                  overflow: hidden;
                }
                body::before {
                  content: "";
                  position: fixed;
                  inset: -20%;
                  background:
                    repeating-linear-gradient(
                      45deg,
                      transparent 0px,
                      transparent 14px,
                      rgba(212, 175, 55, 0.04) 14px,
                      rgba(212, 175, 55, 0.04) 15px
                    );
                  animation: drift 26s linear infinite;
                  pointer-events: none;
                }
                @keyframes drift {
                  from { transform: translate3d(0, 0, 0); }
                  to { transform: translate3d(-80px, -50px, 0); }
                }
                .card {
                  width: min(460px, 100%);
                  border: 1px solid var(--border);
                  background: var(--panel);
                  backdrop-filter: blur(8px);
                  border-radius: 18px;
                  padding: 24px;
                  box-shadow: 0 20px 45px rgba(0, 0, 0, 0.45);
                  position: relative;
                  z-index: 1;
                }
                .title {
                  margin: 0 0 8px 0;
                  font-size: 1.55rem;
                  font-weight: 800;
                  letter-spacing: 0.4px;
                  background: linear-gradient(90deg, var(--gold1), var(--gold2), #fff3c1);
                  -webkit-background-clip: text;
                  -webkit-text-fill-color: transparent;
                }
                .sub { margin: 0 0 18px 0; color: var(--muted); }
                .brand-row {
                  display: flex;
                  align-items: center;
                  gap: 10px;
                  margin-bottom: 8px;
                }
                .icon-wrap {
                  width: 42px;
                  height: 42px;
                  border-radius: 50%;
                  display: grid;
                  place-items: center;
                  border: 1px solid rgba(212, 175, 55, 0.35);
                  background: radial-gradient(circle at 30% 30%, rgba(212,175,55,.2), rgba(0,0,0,.1));
                  animation: pulse 2.6s ease-in-out infinite;
                }
                @keyframes pulse {
                  0%, 100% { transform: scale(1); box-shadow: 0 0 0 rgba(212,175,55,0.0); }
                  50% { transform: scale(1.04); box-shadow: 0 0 18px rgba(212,175,55,0.35); }
                }
                .err {
                  margin: 0 0 14px 0;
                  padding: 10px 12px;
                  border-radius: 10px;
                  border: 1px solid rgba(255, 70, 70, 0.45);
                  background: rgba(120, 20, 30, 0.25);
                  color: #ffd5d9;
                }
                label { display: block; margin-bottom: 6px; color: #f2ebff; font-weight: 600; }
                input {
                  width: 100%;
                  padding: 11px 12px;
                  border-radius: 10px;
                  border: 1px solid rgba(255, 255, 255, 0.15);
                  background: rgba(0, 0, 0, 0.25);
                  color: var(--text);
                  margin-bottom: 14px;
                }
                button {
                  width: 100%;
                  border: 0;
                  border-radius: 12px;
                  padding: 12px 14px;
                  font-weight: 800;
                  cursor: pointer;
                  color: #0f201b;
                  background: linear-gradient(95deg, var(--gold2), var(--gold1), #f7e6aa);
                  box-shadow: 0 8px 24px rgba(212, 175, 55, 0.35);
                }
              </style>
            </head>
            <body>
              <div class="card">
                <div class="brand-row">
                  <div class="icon-wrap">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M14.7 4.8a7.2 7.2 0 1 0 4.5 12.8 6 6 0 1 1-4.5-12.8Z" fill="#d4af37"/>
                      <circle cx="17.8" cy="8.2" r="1.2" fill="#f0d47a"/>
                    </svg>
                  </div>
                  <h1 class="title">Shahid Haidar Doghali Panel</h1>
                </div>
                <p class="sub">Secure Islamic scheduler control for your Railway deployment.</p>
                {% if error %}<p class="err">{{ error }}</p>{% endif %}
                <form method="post">
                  <label>Email</label>
                  <input name="email" type="email" required />
                  <label>Password</label>
                  <input name="password" type="password" required />
                  <button type="submit">Enter Panel</button>
                </form>
              </div>
            </body>
            </html>
            """,
            error=error,
        )

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/", methods=["GET"])
    def dashboard():
        if not session.get("admin_ok"):
            return redirect(url_for("login"))
        schedules = store.list_messages()
        flash = request.args.get("flash", "")
        return render_template_string(
            """
            <!doctype html>
            <html>
            <head>
              <meta charset="utf-8"/>
              <meta name="viewport" content="width=device-width, initial-scale=1"/>
              <title>Shahid Haidar Doghali Panel</title>
              <style>
                :root {
                  --bg0: #081311;
                  --bg1: #0f241f;
                  --bg2: #12352d;
                  --panel: rgba(10, 24, 21, 0.78);
                  --panel-strong: rgba(12, 28, 24, 0.92);
                  --gold1: #d4af37;
                  --gold2: #f0d47a;
                  --ok: #50d890;
                  --muted: #b7b0bf;
                  --line: rgba(255, 255, 255, 0.14);
                  --text: #f7f4ff;
                }
                * { box-sizing: border-box; }
                body {
                  margin: 0;
                  color: var(--text);
                  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
                  background:
                    radial-gradient(circle at 0% 0%, rgba(212,175,55,.20), transparent 30%),
                    radial-gradient(circle at 100% 0%, rgba(31,138,112,.2), transparent 35%),
                    radial-gradient(circle at 50% 100%, rgba(212,175,55,.10), transparent 50%),
                    linear-gradient(160deg, var(--bg0), var(--bg1) 55%, var(--bg2));
                  min-height: 100vh;
                }
                body::before {
                  content: "";
                  position: fixed;
                  inset: 0;
                  background:
                    linear-gradient(120deg, transparent 0 46%, rgba(212,175,55,.04) 46% 47%, transparent 47% 100%),
                    linear-gradient(60deg, transparent 0 46%, rgba(212,175,55,.03) 46% 47%, transparent 47% 100%);
                  pointer-events: none;
                }
                .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
                .hero {
                  border: 1px solid var(--line);
                  border-radius: 18px;
                  padding: 18px 20px;
                  background: var(--panel);
                  backdrop-filter: blur(7px);
                  box-shadow: 0 18px 42px rgba(0, 0, 0, .4);
                  display: flex;
                  justify-content: space-between;
                  align-items: center;
                  gap: 12px;
                  margin-bottom: 20px;
                }
                .title {
                  margin: 0;
                  font-size: 1.8rem;
                  font-weight: 850;
                  letter-spacing: .4px;
                  background: linear-gradient(90deg, var(--gold2), var(--gold1), #fff3c1);
                  -webkit-background-clip: text;
                  -webkit-text-fill-color: transparent;
                }
                .sub { margin: 4px 0 0 0; color: var(--muted); }
                .brand {
                  display: flex;
                  align-items: center;
                  gap: 12px;
                }
                .brand svg {
                  width: 34px;
                  height: 34px;
                  filter: drop-shadow(0 0 10px rgba(212,175,55,.3));
                  animation: float 3s ease-in-out infinite;
                }
                @keyframes float {
                  0%, 100% { transform: translateY(0); }
                  50% { transform: translateY(-3px); }
                }
                .logout {
                  color: #ffe2b8;
                  text-decoration: none;
                  border: 1px solid var(--line);
                  background: rgba(0,0,0,.2);
                  border-radius: 10px;
                  padding: 10px 13px;
                  font-weight: 700;
                }
                .grid {
                  display: grid;
                  grid-template-columns: minmax(320px, 420px) 1fr;
                  gap: 20px;
                }
                .card {
                  border: 1px solid var(--line);
                  border-radius: 16px;
                  background: var(--panel);
                  backdrop-filter: blur(7px);
                  padding: 18px;
                }
                h3 { margin: 0 0 14px 0; font-size: 1.1rem; }
                .flash {
                  margin-bottom: 16px;
                  border: 1px solid rgba(80,216,144,.45);
                  background: rgba(8,81,47,.35);
                  border-radius: 10px;
                  padding: 10px 12px;
                  color: #d7ffe8;
                  font-weight: 700;
                }
                label { display: block; margin-bottom: 6px; font-weight: 650; color: #f2ecff; }
                input[type="text"], textarea {
                  width: 100%;
                  border: 1px solid var(--line);
                  border-radius: 10px;
                  background: rgba(0,0,0,.2);
                  color: var(--text);
                  padding: 10px 12px;
                  margin-bottom: 12px;
                }
                .days {
                  display: grid;
                  grid-template-columns: repeat(4, minmax(0,1fr));
                  gap: 8px;
                  margin-bottom: 12px;
                }
                .day {
                  border: 1px solid var(--line);
                  border-radius: 9px;
                  padding: 8px;
                  background: rgba(0,0,0,.18);
                  font-size: .92rem;
                }
                .btn {
                  border: 0;
                  border-radius: 11px;
                  padding: 10px 12px;
                  font-weight: 800;
                  cursor: pointer;
                  color: #10221d;
                  background: linear-gradient(90deg, var(--gold2), var(--gold1), #f7e6aa);
                  box-shadow: 0 8px 22px rgba(212, 175, 55, .3);
                }
                .btn.small { padding: 7px 9px; font-size: .86rem; box-shadow: none; }
                .btn.secondary {
                  color: #ffd8a8;
                  background: rgba(0,0,0,.22);
                  border: 1px solid var(--line);
                }
                .table-wrap { overflow-x: auto; }
                table {
                  width: 100%;
                  border-collapse: collapse;
                  min-width: 680px;
                }
                th, td {
                  border-bottom: 1px solid var(--line);
                  padding: 10px 8px;
                  text-align: left;
                  vertical-align: top;
                  font-size: .95rem;
                }
                th { color: #ffe5c3; }
                .status {
                  display: inline-block;
                  border-radius: 999px;
                  padding: 4px 9px;
                  font-size: .78rem;
                  font-weight: 800;
                  letter-spacing: .3px;
                }
                .status.on { background: rgba(80,216,144,.18); color: #9df7c3; border: 1px solid rgba(80,216,144,.4); }
                .status.off { background: rgba(255,110,110,.15); color: #ffc2c2; border: 1px solid rgba(255,110,110,.35); }
                .actions { display: flex; gap: 6px; flex-wrap: wrap; }
                @media (max-width: 980px) {
                  .grid { grid-template-columns: 1fr; }
                  .days { grid-template-columns: repeat(3, minmax(0,1fr)); }
                }
              </style>
            </head>
            <body>
              <div class="wrap">
                <div class="hero">
                  <div class="brand">
                    <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
                      <path d="M39 10c-9.4 0-17 7.6-17 17s7.6 17 17 17c6 0 11.3-3.1 14.3-7.7-2 .7-4.1 1-6.3 1-10.6 0-19.3-8.7-19.3-19.3 0-2.2.4-4.3 1-6.3A16.9 16.9 0 0 0 39 10Z" fill="#d4af37"/>
                      <circle cx="46.5" cy="20" r="2.2" fill="#f0d47a"/>
                    </svg>
                    <div>
                      <h1 class="title">Shahid Haidar Doghali Panel</h1>
                      <p class="sub">Railway-ready control panel for timing, formatting, and sending posts.</p>
                    </div>
                  </div>
                  <a class="logout" href="/logout">Logout</a>
                </div>

                {% if flash %}<div class="flash">{{ flash }}</div>{% endif %}

                <div class="grid">
                  <section class="card">
                    <h3>Create Scheduled Message</h3>
                    <form method="post" action="/schedule/create">
                      <label>Title</label>
                      <input name="title" required maxlength="120" type="text" placeholder="Maghrib Ta'qib"/>

                      <label>Time (HH:MM, 24-hour)</label>
                      <input name="time_of_day" required type="text" placeholder="19:30"/>

                      <label>Days</label>
                      <div class="days">
                        {% for idx, name in days %}
                          <label class="day"><input type="checkbox" name="days" value="{{ idx }}"/> {{ name }}</label>
                        {% endfor %}
                      </div>

                      <label>Message body</label>
                      <textarea name="message_body" rows="13" required placeholder="Paste your full formatted Arabic message here..."></textarea>

                      <button class="btn" type="submit">Save Schedule</button>
                    </form>
                  </section>

                  <section class="card">
                    <h3>Existing Schedules</h3>
                    <div class="table-wrap">
                      <table>
                        <tr><th>ID</th><th>Title</th><th>Time</th><th>Days</th><th>Status</th><th>Last Sent</th><th>Actions</th></tr>
                        {% for s in schedules %}
                          <tr>
                            <td>{{ s.id }}</td>
                            <td>{{ s.title }}</td>
                            <td>{{ s.time_of_day }}</td>
                            <td>{{ format_days(s.days_csv) }}</td>
                            <td>
                              {% if s.enabled %}
                                <span class="status on">ENABLED</span>
                              {% else %}
                                <span class="status off">DISABLED</span>
                              {% endif %}
                            </td>
                            <td>{{ s.last_sent_on or "-" }}</td>
                            <td>
                              <div class="actions">
                                <form method="post" action="/schedule/toggle/{{ s.id }}">
                                  <input type="hidden" name="enabled" value="{{ 0 if s.enabled else 1 }}"/>
                                  <button class="btn small secondary" type="submit">{{ "Disable" if s.enabled else "Enable" }}</button>
                                </form>
                                <form method="post" action="/schedule/send-now/{{ s.id }}">
                                  <button class="btn small" type="submit">Send Now</button>
                                </form>
                                <form method="post" action="/schedule/delete/{{ s.id }}">
                                  <button class="btn small secondary" type="submit">Delete</button>
                                </form>
                              </div>
                            </td>
                          </tr>
                        {% endfor %}
                      </table>
                    </div>
                  </section>
                </div>
              </div>
            </body>
            </html>
            """,
            schedules=schedules,
            flash=flash,
            days=_DAYS,
            format_days=_format_days,
        )

    @app.post("/schedule/create")
    def schedule_create():
        if not session.get("admin_ok"):
            return redirect(url_for("login"))
        title = request.form.get("title", "")
        time_of_day = request.form.get("time_of_day", "")
        message_body = request.form.get("message_body", "")
        days = request.form.getlist("days")
        try:
            store.create_message(title, message_body, time_of_day, days)
            return redirect(url_for("dashboard", flash="Schedule saved."))
        except Exception as exc:
            return redirect(url_for("dashboard", flash=f"Error: {escape(str(exc))}"))

    @app.post("/schedule/toggle/<int:schedule_id>")
    def schedule_toggle(schedule_id: int):
        if not session.get("admin_ok"):
            return redirect(url_for("login"))
        enabled = request.form.get("enabled", "1") == "1"
        store.toggle_enabled(schedule_id, enabled)
        return redirect(url_for("dashboard", flash="Schedule updated."))

    @app.post("/schedule/delete/<int:schedule_id>")
    def schedule_delete(schedule_id: int):
        if not session.get("admin_ok"):
            return redirect(url_for("login"))
        store.delete_message(schedule_id)
        return redirect(url_for("dashboard", flash="Schedule deleted."))

    @app.post("/schedule/send-now/<int:schedule_id>")
    def schedule_send_now(schedule_id: int):
        if not session.get("admin_ok"):
            return redirect(url_for("login"))
        schedule = store.get_by_id(schedule_id)
        if schedule is None:
            return redirect(url_for("dashboard", flash="Schedule not found."))
        sent = send_text_callable(
            destination_chat_id,
            format_outgoing_message(schedule.message_body),
            source=f"panel-send-now:{schedule.id}",
        )
        if sent is True:
            return redirect(url_for("dashboard", flash="Message sent now."))
        if sent is None:
            return redirect(
                url_for(
                    "dashboard",
                    flash="Skipped: same text was already sent recently (dedupe).",
                )
            )
        return redirect(url_for("dashboard", flash="Send failed, check bot logs."))

    return app
