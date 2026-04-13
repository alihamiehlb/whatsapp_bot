import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import settings as config
from bot.forwarder import format_outgoing_message


@dataclass
class ScheduledMessage:
    id: int
    title: str
    message_body: str
    time_of_day: str
    days_csv: str
    enabled: bool
    last_sent_on: str


def _validate_time_of_day(value: str) -> bool:
    try:
        hour_text, minute_text = value.split(":")
        hour = int(hour_text)
        minute = int(minute_text)
    except Exception:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _sanitize_days(days: list[str]) -> str:
    cleaned = sorted({str(int(day)) for day in days if str(day).strip().isdigit() and 0 <= int(day) <= 6})
    return ",".join(cleaned)


class ScheduleStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    message_body TEXT NOT NULL,
                    time_of_day TEXT NOT NULL,
                    days_csv TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_sent_on TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def list_messages(self) -> list[ScheduledMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, message_body, time_of_day, days_csv, enabled, last_sent_on
                FROM scheduled_messages
                ORDER BY time_of_day ASC, id DESC
                """
            ).fetchall()
        return [
            ScheduledMessage(
                id=row["id"],
                title=row["title"],
                message_body=row["message_body"],
                time_of_day=row["time_of_day"],
                days_csv=row["days_csv"],
                enabled=bool(row["enabled"]),
                last_sent_on=row["last_sent_on"] or "",
            )
            for row in rows
        ]

    def create_message(self, title: str, message_body: str, time_of_day: str, days: list[str]) -> None:
        title = (title or "").strip()
        message_body = (message_body or "").strip()
        time_of_day = (time_of_day or "").strip()
        days_csv = _sanitize_days(days)
        if not title or not message_body:
            raise ValueError("Title and message body are required.")
        if not _validate_time_of_day(time_of_day):
            raise ValueError("Time must be in HH:MM format.")
        if not days_csv:
            raise ValueError("At least one day must be selected.")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_messages (title, message_body, time_of_day, days_csv, enabled)
                VALUES (?, ?, ?, ?, 1)
                """,
                (title, message_body, time_of_day, days_csv),
            )
            conn.commit()

    def delete_message(self, schedule_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM scheduled_messages WHERE id = ?", (schedule_id,))
            conn.commit()

    def toggle_enabled(self, schedule_id: int, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE scheduled_messages SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, schedule_id),
            )
            conn.commit()

    def mark_sent_today(self, schedule_id: int, date_iso: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE scheduled_messages SET last_sent_on = ? WHERE id = ?",
                (date_iso, schedule_id),
            )
            conn.commit()

    def get_by_id(self, schedule_id: int) -> ScheduledMessage | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, message_body, time_of_day, days_csv, enabled, last_sent_on
                FROM scheduled_messages
                WHERE id = ?
                """,
                (schedule_id,),
            ).fetchone()
        if row is None:
            return None
        return ScheduledMessage(
            id=row["id"],
            title=row["title"],
            message_body=row["message_body"],
            time_of_day=row["time_of_day"],
            days_csv=row["days_csv"],
            enabled=bool(row["enabled"]),
            last_sent_on=row["last_sent_on"] or "",
        )


class MessageSchedulerService:
    def __init__(self, store: ScheduleStore, destination_chat_id: str, send_text_callable):
        self.store = store
        self.destination_chat_id = destination_chat_id
        self.send_text_callable = send_text_callable
        self._running = False

    def _due(self, schedule: ScheduledMessage, now_local: datetime) -> bool:
        if not schedule.enabled:
            return False
        if str(now_local.weekday()) not in schedule.days_csv.split(","):
            return False
        hhmm = now_local.strftime("%H:%M")
        if hhmm != schedule.time_of_day:
            return False
        if schedule.last_sent_on == now_local.date().isoformat():
            return False
        return True

    def run_forever(self) -> None:
        self._running = True
        tz = ZoneInfo(config.SCHEDULE_TIMEZONE)
        while self._running:
            try:
                now_local = datetime.now(tz)
                today_iso = now_local.date().isoformat()
                schedules = self.store.list_messages()
                for schedule in schedules:
                    if not self._due(schedule, now_local):
                        continue
                    message = format_outgoing_message(schedule.message_body)
                    sent = self.send_text_callable(
                        self.destination_chat_id,
                        message,
                        source=f"schedule:{schedule.id}",
                    )
                    if sent:
                        self.store.mark_sent_today(schedule.id, today_iso)
                        print(f"  [Scheduler] sent '{schedule.title}' at {schedule.time_of_day}")
                time.sleep(15)
            except Exception as exc:
                print(f"  [Scheduler] unexpected error: {exc}")
                time.sleep(5)

