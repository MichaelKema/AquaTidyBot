"""Durable guild settings and reminder deadlines (UTC epoch seconds)."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

REMINDERS = {
    "hydrated": ("💧", "stay hydrated!", 2),
    "bottle": ("🥤", "check your bottles!", 3),
    "clean": ("🧹", "clean your room!", None),
}


def next_saturday_slot(now, timezone_name, inclusive=False):
    """Next Saturday at 00, 04, 08, 12, 16 or 20 in the guild timezone."""
    local = now.astimezone(ZoneInfo(timezone_name))
    for day_offset in range(8):
        day = local.date() + timedelta(days=day_offset)
        if day.weekday() != 5:
            continue
        for hour in range(0, 24, 4):
            slot = datetime(day.year, day.month, day.day, hour,
                            tzinfo=ZoneInfo(timezone_name)).astimezone(timezone.utc)
            if slot > now or (inclusive and slot == now):
                return slot
    raise ValueError("No Saturday slot found")


class SettingsStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                role_message_id INTEGER NOT NULL,
                reminder_channel_id INTEGER NOT NULL,
                role_map TEXT NOT NULL,
                timezone TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminder_state (
                guild_id INTEGER NOT NULL REFERENCES guild_settings(guild_id),
                kind TEXT NOT NULL,
                next_due REAL NOT NULL,
                PRIMARY KEY (guild_id, kind)
            );
        """)

    def configure(self, guild_id, message_id, channel_id, role_map, timezone_name, now):
        ZoneInfo(timezone_name)  # Validate before writing any settings.
        with self.connection:
            self.connection.execute("""
                INSERT INTO guild_settings VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    role_message_id=excluded.role_message_id,
                    reminder_channel_id=excluded.reminder_channel_id,
                    role_map=excluded.role_map, timezone=excluded.timezone
            """, (guild_id, message_id, channel_id, json.dumps(role_map), timezone_name))
            for kind in REMINDERS:
                due = next_saturday_slot(now, timezone_name, inclusive=True) if kind == "clean" else now
                self.connection.execute("INSERT OR REPLACE INTO reminder_state VALUES (?, ?, ?)",
                                        (guild_id, kind, due.timestamp()))

    def get(self, guild_id):
        row = self.connection.execute("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)).fetchone()
        if row is None:
            return None
        settings = dict(row)
        settings["role_map"] = json.loads(settings["role_map"])
        return settings

    def due(self, kind, now):
        rows = self.connection.execute("""
            SELECT guild_id, next_due FROM reminder_state
            WHERE kind=? AND next_due <= ?
        """, (kind, now.timestamp())).fetchall()
        return [(self.get(row["guild_id"]), row["next_due"]) for row in rows]

    def mark_sent(self, settings, kind, previous_due, now):
        if kind == "clean":
            upcoming = next_saturday_slot(now, settings["timezone"]).timestamp()
        else:
            interval = REMINDERS[kind][2] * 3600
            # Keep the original cadence and coalesce missed reminders into one.
            upcoming = previous_due + (int((now.timestamp() - previous_due) // interval) + 1) * interval
        with self.connection:
            self.connection.execute("""
                UPDATE reminder_state SET next_due=?
                WHERE guild_id=? AND kind=? AND next_due=?
            """, (upcoming, settings["guild_id"], kind, previous_due))

    def close(self):
        self.connection.close()
