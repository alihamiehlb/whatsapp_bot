import hmac
from html import escape

from flask import Flask, redirect, render_template_string, request, session, url_for

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
    app.secret_key = config.PANEL_SECRET_KEY
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

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
            <html><body style="font-family:Arial;max-width:480px;margin:40px auto;">
              <h2>Shia Group Panel Login</h2>
              {% if error %}<p style="color:#b00020;">{{ error }}</p>{% endif %}
              <form method="post">
                <label>Email</label><br/>
                <input name="email" type="email" required style="width:100%;padding:8px;margin:6px 0 12px 0;"/><br/>
                <label>Password</label><br/>
                <input name="password" type="password" required style="width:100%;padding:8px;margin:6px 0 12px 0;"/><br/>
                <button type="submit" style="padding:10px 14px;">Login</button>
              </form>
            </body></html>
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
            <html><body style="font-family:Arial;max-width:980px;margin:20px auto;line-height:1.4;">
              <h2>Shia Group Scheduler Panel</h2>
              <p><a href="/logout">Logout</a></p>
              {% if flash %}<p style="color:#086f23;font-weight:bold;">{{ flash }}</p>{% endif %}
              <h3>Create scheduled message</h3>
              <form method="post" action="/schedule/create">
                <label>Title</label><br/>
                <input name="title" required maxlength="120" style="width:100%;padding:8px;margin:4px 0 10px 0;"/><br/>
                <label>Time (HH:MM, 24-hour)</label><br/>
                <input name="time_of_day" required placeholder="19:30" style="width:220px;padding:8px;margin:4px 0 10px 0;"/><br/>
                <label>Days</label><br/>
                {% for idx, name in days %}
                  <label style="margin-right:10px;"><input type="checkbox" name="days" value="{{ idx }}"/> {{ name }}</label>
                {% endfor %}
                <br/><br/>
                <label>Message body</label><br/>
                <textarea name="message_body" rows="12" required style="width:100%;padding:8px;"></textarea><br/><br/>
                <button type="submit" style="padding:10px 14px;">Save schedule</button>
              </form>

              <h3 style="margin-top:28px;">Existing schedules</h3>
              <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;">
                <tr><th>ID</th><th>Title</th><th>Time</th><th>Days</th><th>Status</th><th>Last Sent</th><th>Actions</th></tr>
                {% for s in schedules %}
                  <tr>
                    <td>{{ s.id }}</td>
                    <td>{{ s.title }}</td>
                    <td>{{ s.time_of_day }}</td>
                    <td>{{ format_days(s.days_csv) }}</td>
                    <td>{{ "Enabled" if s.enabled else "Disabled" }}</td>
                    <td>{{ s.last_sent_on or "-" }}</td>
                    <td>
                      <form method="post" action="/schedule/toggle/{{ s.id }}" style="display:inline;">
                        <input type="hidden" name="enabled" value="{{ 0 if s.enabled else 1 }}"/>
                        <button type="submit">{{ "Disable" if s.enabled else "Enable" }}</button>
                      </form>
                      <form method="post" action="/schedule/send-now/{{ s.id }}" style="display:inline;margin-left:5px;">
                        <button type="submit">Send now</button>
                      </form>
                      <form method="post" action="/schedule/delete/{{ s.id }}" style="display:inline;margin-left:5px;">
                        <button type="submit">Delete</button>
                      </form>
                    </td>
                  </tr>
                {% endfor %}
              </table>
            </body></html>
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
