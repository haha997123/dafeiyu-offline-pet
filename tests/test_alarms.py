"""Offscreen alarm delivery checks; all audio playback is intercepted."""
from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.paths import AppPaths
from companion.alarms import AlarmDialog
from companion.window import CompanionPetWindow
from settings.config import ConfigManager


SOURCE_ROOT = Path(__file__).resolve().parents[1]


class QtAlarmCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.previous_quit_on_close = cls.application.quitOnLastWindowClosed()
        cls.application.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.application.setQuitOnLastWindowClosed(cls.previous_quit_on_close)

    @classmethod
    def flush_deletes(cls):
        cls.application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def reminder(number, text="喝口水", due_at="2026-11-03T12:00:00+08:00", repeat="once"):
    return {"id": number, "text": text, "due_at": due_at, "done": False, "repeat": repeat}


class AlarmDialogTests(QtAlarmCase):
    def setUp(self):
        self.dialog = AlarmDialog()

    def tearDown(self):
        self.dialog.dismiss()
        self.dialog.deleteLater()
        self.flush_deletes()

    def test_empty_queue_does_not_open_a_dialog(self):
        self.dialog.enqueue([])
        self.assertEqual(self.dialog.pending, [])
        self.assertFalse(self.dialog.isVisible())

    def test_queue_merges_occurrences_and_deduplicates_id_and_due_time(self):
        first = reminder(1, "喝水")
        second = reminder(2, "活动肩膀")
        next_occurrence = reminder(1, "喝水", "2026-11-04T12:00:00+08:00", "daily")
        self.dialog.enqueue([first, second, first])
        self.dialog.enqueue([dict(second), next_occurrence, dict(next_occurrence)])
        self.assertEqual(self.dialog.pending, [first, second, next_occurrence])
        self.assertIn("3", self.dialog.title.text())
        self.assertEqual(self.dialog.details.toPlainText(), "喝水\n\n活动肩膀\n\n喝水")
        self.assertTrue(self.dialog.isVisible())

    def test_reminder_text_is_literal_plain_text_and_not_html(self):
        text = '<b>吃药</b> & <a href="https://example.invalid">点这里</a>\n<img src="file:///missing.png">'
        self.dialog.enqueue([reminder(1, text)])
        self.assertTrue(self.dialog.details.isReadOnly())
        self.assertEqual(self.dialog.details.toPlainText(), text)
        self.assertIn("&lt;b&gt;吃药&lt;/b&gt;", self.dialog.details.toHtml())
        self.assertNotIn('<img src="file:///missing.png">', self.dialog.details.toHtml())

    def test_pending_and_input_records_are_defensive_copies(self):
        original = reminder(1, "原来的提醒")
        self.dialog.enqueue([original])
        original["text"] = "调用者修改了输入"
        returned = self.dialog.pending
        returned[0]["text"] = "调用者修改了输出"
        returned.clear()
        self.assertEqual(self.dialog.pending, [reminder(1, "原来的提醒")])

    def test_close_escape_and_acknowledge_all_dismiss_without_snoozing(self):
        emitted = []
        acknowledged = []
        self.dialog.snooze_requested.connect(emitted.append)
        self.dialog.acknowledged.connect(acknowledged.append)
        for action in ("close", "escape", "acknowledge"):
            with self.subTest(action=action):
                items = [reminder(1), reminder(2, "去休息")]
                self.dialog.enqueue(items)
                self.assertTrue(self.dialog.isVisible())
                if action == "close":
                    self.dialog.close()
                elif action == "escape":
                    QTest.keyClick(self.dialog, Qt.Key.Key_Escape)
                else:
                    QTest.mouseClick(self.dialog.dismiss_button, Qt.MouseButton.LeftButton)
                self.assertEqual(self.dialog.pending, [])
                self.assertFalse(self.dialog.isVisible())
                self.assertEqual(acknowledged[-1], items)
        self.assertEqual(emitted, [])
        self.assertEqual(len(acknowledged), 3)
        self.dialog.dismiss()
        self.dialog.close()
        self.assertEqual(len(acknowledged), 3)

    def test_snooze_emits_all_pending_once_and_waits_for_controller_acknowledgement(self):
        first, second = reminder(1), reminder(2, "休息一下", repeat="daily")
        emitted = []
        acknowledged = []
        self.dialog.snooze_requested.connect(emitted.append)
        self.dialog.acknowledged.connect(acknowledged.append)
        self.dialog.enqueue([first, second, first])
        QTest.mouseClick(self.dialog.snooze_button, Qt.MouseButton.LeftButton)
        self.assertEqual(emitted, [[first, second]])
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(self.dialog.pending, [first, second])
        self.assertEqual(acknowledged, [])
        emitted[0][0]["text"] = "不能通过信号改掉待处理内容"
        self.assertEqual(self.dialog.pending, [first, second])


class AlarmIntegrationTests(QtAlarmCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.data_dir = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.context.enter_context(patch.dict(os.environ, {
            "QT_QPA_PLATFORM": "offscreen",
            "DAFEIYU_DATA_DIR": str(self.data_dir),
            "DAFEIYU_NO_HUB": "1",
            "DAFEIYU_SILENT": "1",
        }))
        # Patch the playback entry point before constructing multimedia objects,
        # including cases that deliberately turn off the test mute below.
        self.chime_play = self.context.enter_context(patch("companion.window.QSoundEffect.play"))
        paths = AppPaths(app_dir=self.data_dir, bundle_dir=SOURCE_ROOT)
        paths.ensure_user_dirs()
        config = ConfigManager(paths.config_path)
        config.set("topmost", False)
        config.set_nested("awareness", "enabled", False)
        config.set_nested("comfort", "desktop_surfaces", False)
        config.set_nested("updates", "enabled", False)
        with patch.object(CompanionPetWindow, "_show_startup_recovery_line"):
            self.window = CompanionPetWindow(paths, config)
        self.now = datetime.now().astimezone().replace(microsecond=0)
        self.window.companion_store._clock = lambda: self.now
        self.tray_message = self.context.enter_context(patch.object(self.window.tray, "showMessage"))
        self.voice_play = self.context.enter_context(patch.object(self.window.speech._player, "play"))
        self.stop_timers()
        self.flush_deletes()
        self.assertFalse(self.window.speech.enabled)

    def stop_timers(self):
        for widget in (self.window, self.window.hub, self.window.food_panel,
                       self.window.control_panel, self.window.care_panel, self.window.alarm_dialog):
            for timer in widget.findChildren(QTimer):
                timer.stop()

    def tearDown(self):
        self.stop_timers()
        try:
            self.window.shutdown_companion()
        finally:
            try:
                self.application.aboutToQuit.disconnect(self.window.shutdown_companion)
            except (RuntimeError, TypeError):
                pass
            self.window.tray.hide()
            for widget in (self.window.hub, self.window.food_panel, self.window.control_panel,
                           self.window.care_panel, self.window.alarm_dialog, self.window):
                widget.hide()
                widget.deleteLater()
            self.flush_deletes()

    def add_due_reminders(self):
        due = self.now + timedelta(minutes=1)
        items = [
            self.window.companion_store.add_reminder("给花浇水", due),
            self.window.companion_store.add_reminder("离开屏幕活动一下", due, repeat="daily"),
        ]
        self.now = due
        return items

    def test_due_reminders_open_visible_dialog_once_without_repeating_after_dismiss(self):
        items = self.add_due_reminders()
        dialog = self.window.alarm_dialog
        with patch.object(dialog, "enqueue", wraps=dialog.enqueue) as enqueue:
            self.window._companion_tick()
            self.window._companion_tick()
            enqueue.assert_called_once_with(items)
            self.assertEqual(dialog.pending, items)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(self.tray_message.call_count, 2)
            self.chime_play.assert_not_called()
            self.voice_play.assert_not_called()
            dialog.dismiss()
            self.window._companion_tick()
            self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(dialog.pending, [])
        self.assertFalse(dialog.isVisible())

    def test_new_due_items_join_the_existing_alarm_queue(self):
        first = self.window.companion_store.add_reminder("先喝水", self.now)
        self.window._companion_tick()
        second = self.window.companion_store.add_reminder("再活动肩膀", self.now)
        self.window._companion_tick()
        self.window._companion_tick()
        self.assertEqual(self.window.alarm_dialog.pending, [first, second])
        self.assertTrue(self.window.alarm_dialog.isVisible())
        self.assertEqual(self.tray_message.call_count, 2)

    def test_snooze_button_passes_the_complete_queue_to_atomic_store_method(self):
        items = self.add_due_reminders()
        self.window._companion_tick()
        store = self.window.companion_store
        repeat_before = next(item for item in store.snapshot()["reminders"] if item["id"] == items[1]["id"])
        with patch.object(store, "snooze_reminders", wraps=store.snooze_reminders) as snooze, \
             patch.object(self.window.hub, "refresh", wraps=self.window.hub.refresh) as refresh:
            QTest.mouseClick(self.window.alarm_dialog.snooze_button, Qt.MouseButton.LeftButton)
            snooze.assert_called_once_with(items, minutes=5)
            refresh.assert_called()
        self.assertEqual(self.window.alarm_dialog.pending, [])
        self.assertFalse(self.window.alarm_dialog.isVisible())
        saved = {item["id"]: item for item in store.snapshot()["reminders"]}
        self.assertTrue(saved[items[0]["id"]]["done"])
        self.assertEqual(saved[items[1]["id"]], repeat_before)
        added = [item for key, item in saved.items() if key not in {old["id"] for old in items}]
        self.assertEqual(len(added), 2)
        self.assertEqual({item["text"] for item in added}, {item["text"] for item in items})
        self.assertTrue(all(item["repeat"] == "once" and not item["done"] for item in added))

    def test_alarm_master_switch_pauses_polling_and_reenable_delivers_saved_alarms(self):
        items = self.add_due_reminders()
        store = self.window.companion_store
        saved = store.snapshot()["reminders"]
        store.set_setting("alarms_enabled", False)
        self.window.apply_companion_settings()
        with patch.object(store, "due_reminders", wraps=store.due_reminders) as poll, \
             patch.object(self.window.alarm_dialog, "enqueue", wraps=self.window.alarm_dialog.enqueue) as enqueue:
            for _ in range(3):
                self.window._companion_tick()
            poll.assert_not_called()
            enqueue.assert_not_called()
            self.assertFalse(self.window.alarm_dialog.isVisible())
            self.assertEqual(store.snapshot()["reminders"], saved)
            self.chime_play.assert_not_called()
            self.tray_message.assert_not_called()
            store.set_setting("alarms_enabled", True)
            self.window.apply_companion_settings()
            self.window._companion_tick()
            self.window._companion_tick()
            enqueue.assert_called_once_with(items)
        self.assertTrue(self.window.alarm_dialog.isVisible())
        self.assertEqual(self.window.alarm_dialog.pending, items)
        self.assertEqual(self.tray_message.call_count, 2)

    def test_disabling_alarm_master_switch_hides_active_dialog_and_stops_chime(self):
        self.add_due_reminders()
        self.window._companion_tick()
        self.assertTrue(self.window.alarm_dialog.isVisible())
        saved = self.window.companion_store.snapshot()["reminders"]
        self.window.companion_store.set_setting("alarms_enabled", False)
        with patch.object(self.window.alarm_chime, "stop") as stop:
            self.window.apply_companion_settings()
            stop.assert_called_once_with()
        self.assertFalse(self.window.alarm_dialog.isVisible())
        # A global pause is not an acknowledgement of a reminder by the user.
        self.assertEqual(self.window.companion_store.snapshot()["reminders"], saved)

    def test_acknowledging_once_marks_it_done_and_daily_occurrences_keep_repeating(self):
        items = self.add_due_reminders()
        once_id, daily_id = (item["id"] for item in items)
        self.window._companion_tick()
        store = self.window.companion_store
        scheduled_daily = next(item for item in store.snapshot()["reminders"] if item["id"] == daily_id)
        with patch.object(store, "complete_reminder", wraps=store.complete_reminder) as complete:
            QTest.mouseClick(self.window.alarm_dialog.dismiss_button, Qt.MouseButton.LeftButton)
            self.window.alarm_dialog.dismiss()
            complete.assert_called_once_with(once_id)
        saved = {item["id"]: item for item in store.snapshot()["reminders"]}
        self.assertTrue(saved[once_id]["done"])
        self.assertEqual(saved[daily_id], scheduled_daily)
        self.assertFalse(saved[daily_id]["done"])
        self.now = datetime.fromisoformat(scheduled_daily["due_at"])
        self.window._companion_tick()
        self.assertEqual([item["id"] for item in self.window.alarm_dialog.pending], [daily_id])
        with patch.object(store, "complete_reminder", wraps=store.complete_reminder) as complete:
            self.window.alarm_dialog.close()
            complete.assert_not_called()
        saved = {item["id"]: item for item in store.snapshot()["reminders"]}
        self.assertTrue(saved[once_id]["done"])
        self.assertFalse(saved[daily_id]["done"])
        self.assertEqual(saved[daily_id]["repeat"], "daily")
        self.assertGreater(datetime.fromisoformat(saved[daily_id]["due_at"]), self.now)

    def test_failed_snooze_keeps_visible_pending_items_for_a_retry(self):
        items = self.add_due_reminders()
        self.window._companion_tick()
        with patch.object(self.window.companion_store, "snooze_reminders", side_effect=OSError("disk full")) as snooze, \
             self.assertLogs("companion.window", level="ERROR"):
            QTest.mouseClick(self.window.alarm_dialog.snooze_button, Qt.MouseButton.LeftButton)
            snooze.assert_called_once_with(items, minutes=5)
        self.assertEqual(self.window.alarm_dialog.pending, items)
        self.assertTrue(self.window.alarm_dialog.isVisible())
        self.assertIn("重试", self.window.alarm_dialog.status.text())
        with patch.object(self.window.companion_store, "snooze_reminders", return_value=[]) as retry:
            QTest.mouseClick(self.window.alarm_dialog.snooze_button, Qt.MouseButton.LeftButton)
            retry.assert_called_once_with(items, minutes=5)
        self.assertEqual(self.window.alarm_dialog.pending, [])
        self.assertFalse(self.window.alarm_dialog.isVisible())

    def test_empty_snooze_does_not_write_to_store(self):
        with patch.object(self.window.companion_store, "snooze_reminders") as snooze:
            self.window._snooze_alarms([])
            snooze.assert_not_called()

    def test_chime_requires_enabled_sound_outside_quiet_hours_without_test_mute(self):
        for enabled in (False, True):
            for quiet in (False, True):
                for silent in (False, True):
                    with self.subTest(enabled=enabled, quiet=quiet, silent=silent):
                        self.window.companion_store.set_setting("alarm_sound_enabled", enabled)
                        self.window.companion_store.add_reminder("声音开关测试", self.now)
                        self.chime_play.reset_mock()
                        with patch.object(self.window, "_quiet_now", return_value=quiet), \
                             patch.dict(os.environ, {"DAFEIYU_SILENT": "1" if silent else "0"}):
                            self.window._companion_tick()
                            self.window._companion_tick()
                        if enabled and not quiet and not silent:
                            self.chime_play.assert_called_once_with()
                        else:
                            self.chime_play.assert_not_called()
                        self.voice_play.assert_not_called()
                        self.assertTrue(self.window.alarm_dialog.isVisible())
                        self.window.alarm_dialog.dismiss()


if __name__ == "__main__":
    unittest.main()
