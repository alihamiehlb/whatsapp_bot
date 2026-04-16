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
              <title>Majlis Control Panel</title>
              <style>
                :root {
                  --bg0: #0d0a10;
                  --bg1: #1a0f1f;
                  --bg2: #2a1219;
                  --fire1: #ff6a00;
                  --fire2: #ff2d55;
                  --fire3: #ffd166;
                  --text: #f6f6f9;
                  --muted: #b7b0bf;
                  --panel: rgba(20, 14, 24, 0.78);
                  --border: rgba(255, 255, 255, 0.12);
                }
                * { box-sizing: border-box; }
                body {
                  margin: 0;
                  min-height: 100vh;
                  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
                  color: var(--text);
                  background:
                    radial-gradient(circle at 10% 10%, rgba(255, 106, 0, 0.25), transparent 35%),
                    radial-gradient(circle at 90% 20%, rgba(255, 45, 85, 0.2), transparent 40%),
                    radial-gradient(circle at 50% 100%, rgba(255, 209, 102, 0.12), transparent 50%),
                    linear-gradient(160deg, var(--bg0), var(--bg1) 55%, var(--bg2));
                  display: grid;
                  place-items: center;
                  padding: 24px;
                }
                .card {
                  width: min(460px, 100%);
                  border: 1px solid var(--border);
                  background: var(--panel);
                  backdrop-filter: blur(8px);
                  border-radius: 18px;
                  padding: 24px;
                  box-shadow: 0 20px 45px rgba(0, 0, 0, 0.45);
                }
                .title {
                  margin: 0 0 8px 0;
                  font-size: 1.55rem;
                  font-weight: 800;
                  letter-spacing: 0.4px;
                  background: linear-gradient(90deg, var(--fire1), var(--fire2), var(--fire3));
                  -webkit-background-clip: text;
                  -webkit-text-fill-color: transparent;
                }
                .sub { margin: 0 0 18px 0; color: var(--muted); }
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
                  color: #1b0e13;
                  background: linear-gradient(95deg, var(--fire3), var(--fire1), var(--fire2));
                  box-shadow: 0 8px 24px rgba(255, 106, 0, 0.35);
                }
              </style>
            </head>
            <body>
              <div class="card">
                <h1 class="title">Shia Majlis Panel</h1>
                <p class="sub">Secure scheduler control for your Railway deployment.</p>
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
              <title>Majlis Scheduler</title>
              <style>
                :root {
                  --bg0: #0d0a10;
                  --bg1: #1a0f1f;
                  --bg2: #2a1219;
                  --panel: rgba(23, 17, 29, 0.75);
                  --panel-strong: rgba(20, 14, 26, 0.92);
                  --fire1: #ff6a00;
                  --fire2: #ff2d55;
                  --fire3: #ffd166;
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
                    radial-gradient(circle at 0% 0%, rgba(255,106,0,.22), transparent 30%),
                    radial-gradient(circle at 100% 0%, rgba(255,45,85,.2), transparent 35%),
                    radial-gradient(circle at 50% 100%, rgba(255,209,102,.12), transparent 50%),
                    linear-gradient(160deg, var(--bg0), var(--bg1) 55%, var(--bg2));
                  min-height: 100vh;
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
                  background: linear-gradient(90deg, var(--fire3), var(--fire1), var(--fire2));
                  -webkit-background-clip: text;
                  -webkit-text-fill-color: transparent;
                }
                .sub { margin: 4px 0 0 0; color: var(--muted); }
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
                  color: #180e12;
                  background: linear-gradient(90deg, var(--fire3), var(--fire1), var(--fire2));
                  box-shadow: 0 8px 22px rgba(255, 106, 0, .3);
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
                  <div>
                    <h1 class="title">Shia Majlis Scheduler</h1>
                    <p class="sub">Railway-ready control panel for timing, formatting, and sending posts.</p>
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
        if sent:
            return redirect(url_for("dashboard", flash="Message sent now."))
        return redirect(url_for("dashboard", flash="Send failed, check bot logs."))

    return app
