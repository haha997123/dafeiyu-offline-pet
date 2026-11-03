"""Behavior tests for local memory, growth, and recoverable backups."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from companion.memory import CompanionStore, LEVELS


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 2, 9, tzinfo=timezone(timedelta(hours=8)))

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class CompanionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.clock = Clock()
        self.store = CompanionStore(self.directory / "data", clock=self.clock)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def reopen(self):
        self.store.close()
        self.store = CompanionStore(self.directory / "data", clock=self.clock)

    def test_reopen_keeps_profile_facts_food_care_and_voice_settings(self):
        self.store.update_profile({"owner_name": "小林", "nickname": "阿林", "likes": "热茶、独立游戏", "birthday": "02-29"})
        self.store.set_setting("voice_enabled", True)
        self.store.set_setting("voice_volume", 33)
        self.store.record_interaction("feed", food="草莓蛋糕", detail="午后的一小块")
        note = self.store.remember("主人不吃香菜。\n不要把它当成鱼鱼自己的偏好。")
        self.store.add_reminder("给花浇水", self.clock.now + timedelta(hours=1))
        before = self.store.snapshot()
        self.reopen()
        self.assertEqual(before, self.store.snapshot())
        self.assertIn("草莓蛋糕", self.store.recall())
        self.assertIn(note["text"], self.store.recall())
        self.assertIn("阿林", self.store.recall())

    def test_cooldown_does_not_erase_food_or_interaction_memory(self):
        self.assertEqual(self.store.record_interaction("feed", food="白米饭")["points"], 8)
        second = self.store.record_interaction("feed", food="虾仁")
        self.assertEqual(second["points"], 0)
        self.assertEqual(self.store.snapshot()["total_care"]["feed"], 2)
        self.assertIn("虾仁", self.store.recall())
        self.clock.advance(seconds=119)
        self.assertEqual(self.store.record_interaction("feed", food="团子")["points"], 0)
        self.clock.advance(seconds=1)
        self.assertEqual(self.store.record_interaction("feed", food="小鱼干")["points"], 8)
        self.assertEqual(self.store.snapshot()["total_care"]["feed"], 4)

    def test_daily_cap_resets_on_calendar_day_but_all_care_is_saved(self):
        for _ in range(12):
            self.store.record_interaction("play")
            self.clock.advance(minutes=3)
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["daily_points"], 60)
        self.assertEqual(snapshot["total_care"]["play"], 12)
        self.assertEqual(snapshot["level"], 1)
        self.clock.now = self.clock.now.replace(day=3, hour=9, minute=0)
        self.assertEqual(self.store.snapshot()["daily_points"], 0)
        self.assertEqual(self.store.snapshot()["today_care"]["play"], 0)
        self.assertEqual(self.store.record_interaction("play")["points"], 10)
        self.assertEqual(self.store.snapshot()["days_together"], 2)

    def test_passive_state_hooks_are_coalesced_but_visits_work_next_day(self):
        for _ in range(100):
            self.store.record_interaction("sleep", detail="午休")
        self.assertEqual(self.store.snapshot()["event_count"], 1)
        self.store.record_interaction("visit")
        self.clock.advance(minutes=10)
        self.assertEqual(self.store.record_interaction("visit")["points"], 0)
        self.clock.advance(days=1)
        self.assertEqual(self.store.record_interaction("visit")["points"], 2)

    def test_snapshot_view_does_not_truncate_event_archive_or_long_notes(self):
        long_fact = "有来源的个人笔记。" * 5000
        self.store.remember(long_fact)
        for number in range(145):
            self.store.record_interaction("feed", food=f"食物{number}")
        snapshot = self.store.snapshot()
        self.assertEqual(len(snapshot["events"]), 100)
        self.assertEqual(snapshot["event_count"], 146)
        self.assertEqual(snapshot["notes"][0]["text"], long_fact)
        target = self.directory / "all-events.json"
        self.store.export_backup(target)
        backup = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(len(backup["events"]), 146)
        self.assertEqual(backup["events"][1]["food"], "食物0")
        self.assertEqual(backup["notes"][0]["text"], long_fact)

    def test_forgetting_fact_removes_it_from_recall_and_new_backups(self):
        fact = "唯一的待遗忘事实：紫色旧围巾"
        note = self.store.remember(fact)
        self.store.forget_note(note["id"])
        self.assertNotIn(fact, self.store.recall())
        self.assertEqual(self.store.snapshot()["notes"], [])
        target = self.directory / "after-forget.json"
        self.store.export_backup(target)
        self.assertNotIn(fact, target.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            self.store.forget_note(note["id"])

    def test_reminders_are_not_repeated_after_polling_or_restart(self):
        item = self.store.add_reminder("喝口水", self.clock.now + timedelta(minutes=1))
        self.assertEqual(self.store.due_reminders(), [])
        self.clock.advance(minutes=1)
        self.assertEqual(self.store.due_reminders(), [item])
        self.assertEqual(self.store.due_reminders(), [])
        self.reopen()
        self.assertEqual(self.store.due_reminders(), [])
        self.store.complete_reminder(item["id"])
        self.assertTrue(self.store.snapshot()["reminders"][0]["done"])

    def test_valid_import_restores_everything_and_backs_up_previous_data(self):
        self.store.record_interaction("feed", food="白饭")
        self.store.remember("原先的事实")
        original = self.store.snapshot()
        backup = self.directory / "original.json"
        self.store.export_backup(backup)
        self.store.update_profile({"nickname": "后来改过的称呼"})
        self.store.remember("后来添加的事实")
        before_import = self.store.snapshot()
        self.store.import_backup(backup)
        self.assertEqual(self.store.snapshot(), original)
        restores = list((self.directory / "data" / "backups").glob("before-import-*.json"))
        self.assertEqual(len(restores), 1)
        self.store.import_backup(restores[0])
        self.assertEqual(self.store.snapshot(), before_import)

    def test_corrupt_or_invalid_imports_leave_original_database_unchanged(self):
        self.store.remember("保留这条真实记忆")
        before = self.store.snapshot()
        valid_path = self.directory / "valid.json"
        self.store.export_backup(valid_path)
        valid = json.loads(valid_path.read_text(encoding="utf-8"))
        invalids = []
        for key, value in (("version", 999), ("notes", [{"id": 1, "at": "bad", "text": "损坏"}]), ("events", [{"id": 1}])):
            invalids.append(json.dumps({**valid, key: value}))
        version_field = f'"version": {valid["version"]}'
        invalids += ['{"format":', valid_path.read_text(encoding="utf-8").replace(version_field, version_field + ', ' + version_field)]
        for number, content in enumerate(invalids):
            path = self.directory / f"broken-{number}.json"
            path.write_text(content, encoding="utf-8")
            with self.subTest(number=number), self.assertRaises(ValueError):
                self.store.import_backup(path)
            self.assertEqual(self.store.snapshot(), before)
        self.reopen()
        self.assertEqual(self.store.snapshot(), before)

    def test_import_sql_failure_rolls_back_already_deleted_rows(self):
        self.store.remember("原库必须留着")
        before = self.store.snapshot()
        backup = self.directory / "source.json"
        self.store.export_backup(backup)
        # An I/O/SQL failure after DELETE must be atomic as well as malformed
        # input failures before mutation. A temporary trigger simulates it.
        self.store._db.execute("CREATE TRIGGER fail_note_import BEFORE INSERT ON notes BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.import_backup(backup)
        self.assertEqual(self.store.snapshot(), before)
        self.store._db.execute("DROP TRIGGER fail_note_import")

    def test_growth_requires_long_term_points_and_days(self):
        # Every day, six appropriately spaced play sessions earn the daily cap.
        for day in range(3):
            self.clock.now = datetime(2026, 11, 2 + day, 9, tzinfo=self.clock.now.tzinfo)
            for _ in range(6):
                self.store.record_interaction("play")
                self.clock.advance(minutes=3)
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["total_points"], 180)
        self.assertEqual(snapshot["level"], 2)
        self.assertEqual(snapshot["next_level_points"], 360)
        self.assertEqual(snapshot["next_level_days"], 7)
        # Even enough points do not skip the required companionship days.
        self.assertEqual(CompanionStore._level(10000, 3), 2)
        self.assertEqual(CompanionStore._level(10000, 179), 7)
        self.assertEqual(CompanionStore._level(LEVELS[-1][0], 180), 8)

    def test_validation_does_not_partly_update_profile_or_accept_bad_settings(self):
        self.store.update_profile({"nickname": "原称呼"})
        with self.assertRaises(ValueError):
            self.store.update_profile({"nickname": "不应保存", "birthday": "02-30"})
        self.assertEqual(self.store.snapshot()["profile"]["nickname"], "原称呼")
        for key, value in (("voice_volume", 101), ("quiet_start", 24), ("voice_enabled", 1), ("voice_rate", True), ("unknown", 2)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.store.set_setting(key, value)

    def test_future_database_version_is_rejected_without_overwrite(self):
        self.store.remember("未来版本测试")
        self.store.close()
        database = self.directory / "data" / "companion.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA user_version=999")
        connection.close()
        with self.assertRaises(ValueError):
            CompanionStore(self.directory / "data", clock=self.clock)
        connection = sqlite3.connect(database)
        self.assertEqual(connection.execute("SELECT text FROM notes").fetchone()[0], "未来版本测试")
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 999)
        connection.close()

    def test_daily_alarm_skips_missed_days_once_and_keeps_next_wall_time(self):
        original = self.store.add_reminder("午后喝水", self.clock.now + timedelta(minutes=10), "daily")
        self.clock.advance(days=8, minutes=15)
        self.reopen()
        self.assertEqual(self.store.due_reminders(), [original])
        next_alarm = self.store.snapshot()["reminders"][0]
        next_time = datetime.fromisoformat(next_alarm["due_at"])
        self.assertEqual((next_time.hour, next_time.minute), (9, 10))
        self.assertGreater(next_time, self.clock.now)
        self.assertLessEqual(next_time - self.clock.now, timedelta(days=1))
        self.assertEqual(self.store.due_reminders(), [])
        self.reopen()
        self.assertEqual(self.store.due_reminders(), [])
        self.clock.now = next_time
        self.assertEqual(len(self.store.due_reminders()), 1)
        self.assertEqual(self.store.due_reminders(), [])

    def test_workday_alarm_skips_weekend_and_preserves_time(self):
        self.clock.now = self.clock.now.replace(day=6, hour=8)  # Friday
        self.store.add_reminder("上班喝水", self.clock.now.replace(hour=9), "weekdays")
        self.clock.advance(hours=1)
        self.assertEqual(len(self.store.due_reminders()), 1)
        next_time = datetime.fromisoformat(self.store.snapshot()["reminders"][0]["due_at"])
        self.assertEqual((next_time.weekday(), next_time.hour), (0, 9))
        self.clock.advance(days=1)
        self.assertEqual(self.store.due_reminders(), [])
        self.clock.now = next_time
        self.assertEqual(len(self.store.due_reminders()), 1)

    def test_edit_delete_repeat_backup_and_legacy_backup_import(self):
        alarm = self.store.add_reminder("旧提醒", self.clock.now, "daily")
        self.store.complete_reminder(alarm["id"])
        edited = self.store.update_reminder(alarm["id"], "新提醒", self.clock.now + timedelta(hours=1), "weekdays")
        self.assertFalse(edited["done"])
        target = self.directory / "alarms.json"
        self.store.set_setting("alarm_sound_enabled", False)
        self.store.export_backup(target)
        expected = self.store.snapshot()
        self.store.delete_reminder(alarm["id"])
        self.assertEqual(self.store.snapshot()["reminders"], [])
        self.store.import_backup(target)
        self.assertEqual(self.store.snapshot(), expected)
        legacy = json.loads(target.read_text(encoding="utf-8"))
        legacy["version"] = 1
        legacy["settings"].pop("alarm_sound_enabled")
        legacy["settings"].pop("alarms_enabled")
        for row in legacy["reminders"]:
            row.pop("repeat")
        target.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        self.store.import_backup(target)
        self.assertEqual(self.store.snapshot()["reminders"][0]["repeat"], "once")
        self.assertTrue(self.store.snapshot()["settings"]["alarm_sound_enabled"])
        self.assertTrue(self.store.snapshot()["settings"]["alarms_enabled"])

    def test_existing_v1_database_migrates_without_losing_old_memory(self):
        self.store.remember("旧版本里的记忆")
        alarm = self.store.add_reminder("旧闹钟", self.clock.now + timedelta(hours=1))
        self.store.close()
        db = sqlite3.connect(self.directory / "data" / "companion.sqlite3")
        db.execute("CREATE TABLE reminders_v1 (id INTEGER PRIMARY KEY AUTOINCREMENT,text TEXT NOT NULL,due_at TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0,1)),notified_at TEXT)")
        db.execute("INSERT INTO reminders_v1 SELECT id,text,due_at,done,notified_at FROM reminders")
        db.execute("DROP TABLE reminders")
        db.execute("ALTER TABLE reminders_v1 RENAME TO reminders")
        db.execute("DELETE FROM settings WHERE key='alarm_sound_enabled'")
        db.execute("DELETE FROM settings WHERE key='alarms_enabled'")
        db.execute("PRAGMA user_version=1")
        db.commit()
        db.close()
        self.store = CompanionStore(self.directory / "data", clock=self.clock)
        self.assertIn("旧版本里的记忆", self.store.recall())
        self.assertEqual(self.store.snapshot()["reminders"], [alarm])
        self.assertTrue(self.store.snapshot()["settings"]["alarm_sound_enabled"])
        self.assertTrue(self.store.snapshot()["settings"]["alarms_enabled"])
        self.assertEqual(self.store._db.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_once_alarm_missed_while_closed_delivers_once_after_reopen(self):
        alarm = self.store.add_reminder("出门前带钥匙", self.clock.now + timedelta(minutes=1))
        self.clock.advance(days=2)
        self.reopen()
        self.assertEqual(self.store.due_reminders(), [alarm])
        self.reopen()
        self.assertEqual(self.store.due_reminders(), [])

    def test_snooze_is_atomic_and_does_not_change_recurring_alarm(self):
        recurring = self.store.add_reminder("喝水", self.clock.now + timedelta(minutes=5), "daily")
        before = self.store.snapshot()
        delayed = self.store.snooze_reminders([recurring, {"text": "另一个小事"}])
        self.assertEqual(len(delayed), 2)
        self.assertTrue(all(r["repeat"] == "once" for r in delayed))
        self.assertTrue(all(datetime.fromisoformat(r["due_at"]) == self.clock.now + timedelta(minutes=5) for r in delayed))
        self.assertIn(recurring, self.store.snapshot()["reminders"])
        before_failure = self.store.snapshot()
        self.store._db.execute("CREATE TRIGGER fail_second_alarm BEFORE INSERT ON reminders WHEN NEW.text='模拟失败' BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.snooze_reminders([{"text": "这条也不能留下"}, {"text": "模拟失败"}])
        self.assertEqual(self.store.snapshot(), before_failure)
        self.store._db.execute("DROP TRIGGER fail_second_alarm")

    def test_global_alarm_switch_pauses_delivery_without_consuming_or_rescheduling(self):
        once = self.store.add_reminder("一次提醒", self.clock.now)
        daily = self.store.add_reminder("每天提醒", self.clock.now, "daily")
        self.store.set_setting("alarms_enabled", False)
        before = [tuple(row) for row in self.store._db.execute("SELECT * FROM reminders ORDER BY id")]
        self.clock.advance(days=3)
        self.assertEqual(self.store.due_reminders(), [])
        self.reopen()
        self.assertFalse(self.store.snapshot()["settings"]["alarms_enabled"])
        self.assertEqual(self.store.due_reminders(), [])
        self.assertEqual([tuple(row) for row in self.store._db.execute("SELECT * FROM reminders ORDER BY id")], before)
        self.store.update_reminder(once["id"], "关闭期间可以编辑", self.clock.now)
        self.store.set_setting("alarms_enabled", True)
        due = self.store.due_reminders()
        self.assertEqual({r["id"] for r in due}, {once["id"], daily["id"]})
        self.assertEqual(self.store.due_reminders(), [])

    def test_schema2_and_backup2_add_enabled_default_and_keep_sound_preference(self):
        self.store.add_reminder("老版本的每天提醒", self.clock.now, "daily")
        self.store.set_setting("alarm_sound_enabled", False)
        backup = self.directory / "schema2.json"
        self.store.export_backup(backup)
        payload = json.loads(backup.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["settings"].pop("alarms_enabled")
        backup.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.store.close()
        db = sqlite3.connect(self.directory / "data" / "companion.sqlite3")
        db.execute("DELETE FROM settings WHERE key='alarms_enabled'")
        db.execute("PRAGMA user_version=2")
        db.commit()
        db.close()
        self.store = CompanionStore(self.directory / "data", clock=self.clock)
        self.assertTrue(self.store.snapshot()["settings"]["alarms_enabled"])
        self.assertFalse(self.store.snapshot()["settings"]["alarm_sound_enabled"])
        self.store.set_setting("alarms_enabled", False)
        self.store.import_backup(backup)
        self.assertTrue(self.store.snapshot()["settings"]["alarms_enabled"])
        self.assertFalse(self.store.snapshot()["settings"]["alarm_sound_enabled"])


if __name__ == "__main__":
    unittest.main()
