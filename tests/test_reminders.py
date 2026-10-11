import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import AquaTidy as app
from storage import SettingsStore, next_saturday_slot

ROLES = {"🧹": "Clean", "💧": "Water", "🥤": "Bottle"}


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "db.sqlite3")
        self.store = SettingsStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def configure(self, guild=1, now=utc("2026-10-09T12:00"), tz="America/New_York"):
        self.store.configure(guild, guild * 10, guild * 100, ROLES, tz, now)

    def test_settings_and_deadlines_survive_restart_and_are_per_guild(self):
        self.configure()
        self.store.configure(2, 22, 222, {"🧹": "Different"}, "UTC", utc("2026-10-09T12:00"))
        self.store.close()
        self.store = SettingsStore(self.path)
        self.assertEqual(self.store.get(1)["role_map"], ROLES)
        self.assertEqual(self.store.get(1)["role_message_id"], 10)
        self.assertEqual(self.store.get(1)["reminder_channel_id"], 100)
        self.assertEqual(self.store.get(1)["timezone"], "America/New_York")
        self.assertEqual(self.store.get(2)["role_map"], {"🧹": "Different"})
        self.assertEqual(len(self.store.due("clean", utc("2026-10-10T04:02"))), 2)

    def test_late_saturday_poll_is_sent_once(self):
        self.configure()
        now = utc("2026-10-10T04:02")  # Saturday 00:02 New York
        settings, due = self.store.due("clean", now)[0]
        self.store.mark_sent(settings, "clean", due, now)
        self.assertEqual(self.store.due("clean", now), [])
        self.assertEqual(len(self.store.due("clean", utc("2026-10-10T08:00"))), 1)

    def test_restart_after_saturday_coalesces_and_persists_delivery(self):
        self.configure()
        now = utc("2026-10-12T12:00")
        settings, due = self.store.due("clean", now)[0]
        self.store.mark_sent(settings, "clean", due, now)
        self.store.close()
        self.store = SettingsStore(self.path)
        self.assertEqual(self.store.due("clean", now), [])
        self.assertEqual(len(self.store.due("clean", utc("2026-10-17T04:00"))), 1)

    def test_periodic_cadence_survives_delays(self):
        self.configure(now=utc("2026-10-09T12:00"))
        now = utc("2026-10-09T19:30")
        settings, due = self.store.due("hydrated", now)[0]
        self.store.mark_sent(settings, "hydrated", due, now)
        self.assertEqual(self.store.due("hydrated", utc("2026-10-09T19:59")), [])
        self.assertEqual(len(self.store.due("hydrated", utc("2026-10-09T20:00"))), 1)

    def test_all_saturday_slots_and_no_sunday_slots(self):
        for hour in range(0, 24, 4):
            now = utc(f"2026-10-10T{hour:02d}:00")
            self.assertEqual(next_saturday_slot(now, "UTC", inclusive=True), now)
        self.assertEqual(next_saturday_slot(utc("2026-10-11T00:00"), "UTC"), utc("2026-10-17T00:00"))

    def test_saturday_slots_and_timezone_dst(self):
        cases = [
            ("2026-10-10T04:00", "2026-10-10T08:00"),
            ("2026-10-11T00:01", "2026-10-17T04:00"),
            ("2026-03-07T01:00", "2026-03-07T05:00"),
            ("2026-03-08T02:00", "2026-03-14T04:00"),
            ("2026-10-31T23:00", "2026-11-01T00:00"),
            ("2026-11-01T01:00", "2026-11-07T05:00"),
        ]
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(next_saturday_slot(utc(now), "America/New_York"), utc(expected))
        exact = utc("2026-10-10T04:00")
        self.assertEqual(next_saturday_slot(exact, "America/New_York", inclusive=True), exact)


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_reconnections_do_not_start_loops(self):
        with patch.object(app.update_hydrated_roles, "start") as hydrated, \
             patch.object(app.update_bottle_check_roles, "start") as bottle, \
             patch.object(app.update_clean_room_roles, "start") as clean:
            await app.on_ready()
            await app.on_ready()
            for loop in (hydrated, bottle, clean):
                loop.assert_not_called()

    async def test_setup_hook_starts_loops_once_and_close_cancels(self):
        client = app.AquaTidyBot(command_prefix="!", intents=app.intents)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(app.os.environ, {"DATABASE_PATH": str(Path(tmp) / "db.sqlite3")}):
            await client.setup_hook()
            self.assertTrue(all(loop.is_running() for loop in (
                app.update_hydrated_roles, app.update_bottle_check_roles, app.update_clean_room_roles)))
            original_tasks = [loop.get_task() for loop in (
                app.update_hydrated_roles, app.update_bottle_check_roles, app.update_clean_room_roles)]
            await client.setup_hook()
            self.assertEqual(original_tasks, [loop.get_task() for loop in (
                app.update_hydrated_roles, app.update_bottle_check_roles, app.update_clean_room_roles)])
            await client.close()
            self.assertTrue(all(task.done() for task in original_tasks))

    async def test_failed_send_stays_due_and_other_guild_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(str(Path(tmp) / "db.sqlite3"))
            now = utc("2026-10-10T00:02")
            for guild in (1, 2):
                store.configure(guild, guild, guild, ROLES, "UTC", utc("2026-10-09T12:00"))
            fake_bot = SimpleNamespace(settings=store, wait_until_ready=AsyncMock())
            failure = app.discord.HTTPException(SimpleNamespace(status=500, reason="error"), "error")
            with patch.object(app, "bot", fake_bot), \
                 patch.object(app, "send_role_reminder", AsyncMock(side_effect=[failure, True])):
                await app.dispatch_due("clean", now)
            self.assertEqual([settings["guild_id"] for settings, _ in store.due("clean", now)], [1])
            store.close()

    async def test_raw_reactions_use_saved_message_without_message_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "db.sqlite3")
            store = SettingsStore(path)
            store.configure(1, 10, 100, ROLES, "UTC", utc("2026-10-09T12:00"))
            store.close()
            store = SettingsStore(path)
            member = SimpleNamespace(bot=False, add_roles=AsyncMock(), remove_roles=AsyncMock(), send=AsyncMock())
            role = SimpleNamespace(name="Clean")
            guild = SimpleNamespace(id=1, roles=[role], get_member=lambda _: None, fetch_member=AsyncMock(return_value=member))
            fake_bot = SimpleNamespace(settings=store, get_guild=lambda _: guild)
            payload = SimpleNamespace(guild_id=1, message_id=10, user_id=7, emoji="🧹")
            with patch.object(app, "bot", fake_bot):
                await app.on_raw_reaction_add(payload)
                await app.on_raw_reaction_remove(payload)
                payload.message_id = 11
                await app.on_raw_reaction_add(payload)
            member.add_roles.assert_awaited_once_with(role)
            member.remove_roles.assert_awaited_once_with(role)
            store.close()


if __name__ == "__main__":
    unittest.main()
