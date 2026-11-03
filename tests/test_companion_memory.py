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
        invalids += ['{"format":', valid_path.read_text(encoding="utf-8").replace('"version": 1', '"version": 1, "version": 2')]
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


if __name__ == "__main__":
    unittest.main()
