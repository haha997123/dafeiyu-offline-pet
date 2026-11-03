"""Offscreen integration checks using the real pet, journal, and local store.

The source art and character-audio manifest are loaded normally. Audio stays
disabled, external windows remain hidden, and each test uses its own data dir.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtCore import Qt, QPoint, QPointF, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.paths import AppPaths
from companion.window import CompanionPetWindow
from settings.config import ConfigManager
from pet.interaction import InteractionOutcome
from types import SimpleNamespace


SOURCE_ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = datetime.now().astimezone()

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class CompanionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls._previous_quit_on_close = cls.application.quitOnLastWindowClosed()
        cls.application.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        # Do not call QApplication.quit(): other UI suites share this instance.
        cls.application.setQuitOnLastWindowClosed(cls._previous_quit_on_close)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            "QT_QPA_PLATFORM": "offscreen",
            "DAFEIYU_DATA_DIR": str(self.data_dir),
            "DAFEIYU_NO_HUB": "1",
            "DAFEIYU_SILENT": "1",
        })
        self.environment.start()
        self.windows = []
        self.clock = Clock()
        self.window = self.make_window()

    def tearDown(self):
        try:
            for window in list(self.windows):
                self.dispose_window(window)
            self.application.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            self.environment.stop()
            self.temporary.cleanup()

    def make_window(self):
        paths = AppPaths(app_dir=self.data_dir, bundle_dir=SOURCE_ROOT)
        paths.ensure_user_dirs()
        config = ConfigManager(paths.config_path)
        config.set("topmost", False)
        config.set_nested("awareness", "enabled", False)
        config.set_nested("comfort", "desktop_surfaces", False)
        config.set_nested("updates", "enabled", False)
        window = CompanionPetWindow(paths, config)
        self.windows.append(window)
        # Control elapsed care time without waiting, while keeping the real
        # SQLite connection, controller, widgets, and source assets in place.
        window.companion_store._clock = self.clock
        self.stop_timers(window)
        self.assertFalse(window.speech.enabled)  # Test-only mute never overwrites the user's preference.
        self.application.processEvents()
        return window

    @staticmethod
    def stop_timers(window):
        # The journal is a separate top-level widget rather than a child of the
        # pet. Stop both trees before explicitly driving the tested slots.
        for widget in (window, window.hub, window.food_panel, window.control_panel):
            if widget is not None:
                for timer in widget.findChildren(QTimer):
                    timer.stop()

    def dispose_window(self, window):
        if window not in self.windows:
            return
        self.windows.remove(window)
        self.stop_timers(window)
        try:
            window.shutdown_companion()
        finally:
            try:
                self.application.aboutToQuit.disconnect(window.shutdown_companion)
            except (RuntimeError, TypeError):
                pass
            window.tray.hide()
            for widget in (window.hub, window.food_panel, window.control_panel, window):
                if widget is not None:
                    widget.hide()
                    widget.deleteLater()
            self.application.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def events_of_kind(self, kind):
        return [event for event in self.window.companion_store.snapshot()["events"] if event["kind"] == kind]

    def test_hub_feed_signal_records_one_specific_chinese_food(self):
        before = self.window.companion_store.snapshot()
        old_feed_count = self.window.pet_state.total_feedings
        with patch.object(self.window.speech._player, "play") as audio_play:
            self.window.hub.interaction_requested.emit("feed", "草莓蛋糕")
            audio_play.assert_not_called()
        after = self.window.companion_store.snapshot()
        self.assertEqual(after["event_count"], before["event_count"] + 1)
        self.assertEqual(after["total_care"]["feed"], 1)
        self.assertEqual(self.window.pet_state.total_feedings, old_feed_count + 1)
        self.assertEqual(len(self.events_of_kind("feed")), 1)
        self.assertEqual(self.events_of_kind("feed")[0]["food"], "草莓蛋糕")
        self.assertIn("草莓蛋糕", self.window.companion_store.recall())

    def test_profile_and_handwritten_fact_survive_a_real_window_restart(self):
        hub = self.window.hub
        with patch.object(hub, "_error", side_effect=AssertionError("UI persistence failed")):
            hub.profile_fields["owner_name"].setText("小林")
            hub.profile_fields["nickname"].setText("阿林")
            hub.profile_fields["pet_name"].setText("蓝蓝")
            hub.profile_fields["likes"].setText("热茶、独立游戏")
            hub._save_profile()
            hub.note_input.setPlainText("主人喜欢热茶，不喝冰水。")
            hub._remember()
        expected_profile = self.window.companion_store.snapshot()["profile"]
        expected_notes = self.window.companion_store.snapshot()["notes"]
        self.dispose_window(self.window)
        self.window = self.make_window()
        snapshot = self.window.companion_store.snapshot()
        self.assertEqual(snapshot["profile"], expected_profile)
        self.assertEqual(snapshot["notes"], expected_notes)
        self.assertEqual(self.window.hub.profile_fields["nickname"].text(), "阿林")
        self.assertEqual(self.window.hub.note_list.count(), 1)
        self.assertIn("主人喜欢热茶，不喝冰水。", self.window.companion_store.recall())

    def test_cooldown_keeps_concrete_food_memories_when_points_are_zero(self):
        baseline = self.window.companion_store.snapshot()["total_points"]
        self.window.hub.interaction_requested.emit("feed", "白米饭")
        self.window.hub.interaction_requested.emit("feed", "虾仁")
        snapshot = self.window.companion_store.snapshot()
        self.assertEqual(snapshot["total_points"] - baseline, 8)
        self.assertEqual(snapshot["total_care"]["feed"], 2)
        self.assertIn("虾仁", self.window.companion_store.recall())
        self.clock.advance(seconds=120)
        self.window.hub.interaction_requested.emit("feed", "海苔团子")
        snapshot = self.window.companion_store.snapshot()
        self.assertEqual(snapshot["total_points"] - baseline, 16)
        self.assertEqual(snapshot["total_care"]["feed"], 3)
        self.assertEqual([event["food"] for event in self.events_of_kind("feed")], ["海苔团子", "虾仁", "白米饭"])

    def test_cancelled_focus_has_no_reward_and_completed_focus_records_once(self):
        before = self.window.companion_store.snapshot()
        previous_mode = self.window.movement.mode
        self.window.hub.focus_requested.emit(5)
        self.assertGreater(self.window._focus_end, 0)
        self.assertEqual(self.window.movement.mode, "still")
        self.window.hub.focus_requested.emit(0)
        self.assertEqual(self.window._focus_end, 0)
        self.assertEqual(self.window.movement.mode, previous_mode)
        self.assertEqual(self.events_of_kind("focus"), [])
        self.assertEqual(self.window.companion_store.snapshot()["total_points"], before["total_points"])

        self.window.hub.focus_requested.emit(1)
        self.clock.advance(minutes=1)
        self.window._focus_end = time.monotonic() - 0.01
        with patch.object(self.window.tray, "showMessage") as notification:
            self.window._companion_tick()
            self.window._companion_tick()
            self.assertEqual(notification.call_count, 1)
        focus_events = self.events_of_kind("focus")
        self.assertEqual(len(focus_events), 1)
        self.assertIn("1 分钟", focus_events[0]["detail"])
        self.assertEqual(self.window.companion_store.snapshot()["total_points"] - before["total_points"], 8)
        self.assertEqual(self.window.movement.mode, previous_mode)

    def test_rapid_head_pats_cannot_bypass_daily_growth_or_relationship_stage(self):
        before = self.window.companion_store.snapshot()
        for _ in range(50):
            self.window.hub.interaction_requested.emit("pat", "")
        snapshot = self.window.companion_store.snapshot()
        self.assertEqual(snapshot["total_care"]["pat"], 50)
        self.assertEqual(snapshot["total_points"] - before["total_points"], 4)
        self.assertEqual(snapshot["level"], 1)
        expected_affinity = min(1.0, 0.36 + 0.075 * snapshot["level"])
        self.assertAlmostEqual(self.window.pet_state.affinity, expected_affinity)
        self.assertAlmostEqual(self.window.state_store.load().affinity, expected_affinity)
        self.assertLess(self.window.pet_state.affinity, 0.56)

    def test_due_reminder_is_presented_once_through_controller(self):
        item = self.window.companion_store.add_reminder("给花浇水", self.clock.now + timedelta(minutes=1))
        self.clock.advance(minutes=1)
        with patch.object(self.window.tray, "showMessage") as notification:
            self.window._companion_tick()
            self.window._companion_tick()
            self.assertEqual(notification.call_count, 1)
            self.assertEqual(notification.call_args.args[1], "给花浇水")
        reminders = self.window.companion_store.snapshot()["reminders"]
        self.assertEqual(reminders, [item])
        self.dispose_window(self.window)
        self.window = self.make_window()
        with patch.object(self.window.tray, "showMessage") as notification:
            self.window._companion_tick()
            notification.assert_not_called()

    def test_shutdown_closes_speech_and_store_even_if_pet_snapshot_fails(self):
        speech = self.window.speech
        store = self.window.companion_store
        with patch.object(self.window, "save_snapshot", side_effect=OSError("simulated snapshot failure")), \
             patch.object(speech, "close", wraps=speech.close) as speech_close, \
             patch.object(store, "close", wraps=store.close) as store_close, \
             self.assertLogs("companion.window", level="ERROR") as captured:
            self.window.shutdown_companion()
            self.window.shutdown_companion()
            speech_close.assert_called_once()
            store_close.assert_called_once()
        self.assertTrue(any("final pet snapshot" in message for message in captured.output))
        self.assertTrue(speech._closed)
        self.assertFalse(self.window.companion_timer.isActive())
        self.assertFalse(self.window.persistence_timer.isActive())
        self.assertFalse(self.window.timer.isActive())
        with self.assertRaises(RuntimeError):
            store.snapshot()

    def test_startup_keeps_the_journal_closed_and_escape_allows_reopening(self):
        self.assertFalse(self.window.hub.isVisible())
        self.window.open_hub("settings")
        self.assertTrue(self.window.hub.isVisible())
        QTest.keyClick(self.window.hub, Qt.Key.Key_Escape)
        self.assertFalse(self.window.hub.isVisible())
        self.assertTrue(self.window.isVisible())
        self.window.open_hub("settings")
        self.assertTrue(self.window.hub.isVisible())

    def test_explicit_interaction_voice_is_not_suppressed_by_night_quiet_hours(self):
        with patch.object(self.window, "_quiet_now", return_value=True), \
             patch.object(self.window.speech, "play", return_value="我一直都在这里的哦。") as play:
            self.window.interact("pat", "")
            play.assert_called_once_with("pat", automatic=False)
            self.assertEqual(self.window.bubble.text, "我一直都在这里的哦。")

    def test_preview_enables_only_character_voice_without_opening_the_journal(self):
        self.window.companion_store.set_setting("voice_enabled", False)
        with patch.object(self.window.speech, "play", return_value="我一直都在这里的哦。") as play:
            self.window.preview_voice()
            play.assert_called_once_with("preview", automatic=False)
        self.assertTrue(self.window.companion_store.snapshot()["settings"]["voice_enabled"])
        self.assertFalse(self.window.hub.isVisible())

    def test_voice_entry_opens_the_settings_page_directly(self):
        self.window.care_panel.voice_settings_button.click()
        self.assertTrue(self.window.hub.isVisible())
        self.assertEqual(self.window.hub.stack.currentWidget(), self.window.hub._pages["settings"])

    def test_drag_release_floats_at_drop_point_and_survives_size_change(self):
        window = self.window
        area = self.application.primaryScreen().availableGeometry()
        point = QPoint(area.left() + 100, area.top() + 45)
        window.move(point)
        window.set_mode("follow")
        outcome = InteractionOutcome("drag", "head", 1400, 900, 1.0)
        event = SimpleNamespace(button=lambda: Qt.MouseButton.LeftButton,
                                globalPosition=lambda: QPointF(300, 200))
        with patch.object(window.interaction, "release", return_value=outcome):
            window.mouseReleaseEvent(event)
        self.assertEqual(window.pos(), point)
        self.assertEqual(window.movement.mode, "still")
        self.assertFalse(window.physics.active)
        self.assertEqual(window.config.get("y"), point.y())
        window.set_size(0.55)
        self.assertEqual(window.pos(), point)
        self.dispose_window(window)
        self.window = self.make_window()
        self.assertEqual(self.window.pos(), point)
        self.assertEqual(self.window.movement.mode, "still")

    def test_gravity_is_available_as_an_explicit_option(self):
        self.window.set_placement("gravity")
        self.assertTrue(self.window.physics.active)
        self.window.set_placement("floating")
        self.assertFalse(self.window.physics.active)
        self.assertTrue(self.window.movement.free_vertical)

    def test_return_to_primary_uses_primary_work_area_and_stops_following(self):
        area = QRect(1000, 200, 1200, 900)
        primary = SimpleNamespace(availableGeometry=lambda: area)
        self.window.move(-500, -500)
        self.window.set_mode("follow")
        with patch("pet.window.QApplication.primaryScreen", return_value=primary):
            self.window.move_to_primary_screen()
        self.assertTrue(area.contains(self.window.geometry()))
        self.assertEqual(self.window.geometry().center(), area.center())
        self.assertEqual(self.window.movement.mode, "still")

    def test_reduced_motion_freezes_actual_continuous_frames(self):
        self.window.set_mode("still")
        self.window.set_reduced_motion(True)
        before = self.window.player.elapsed_seconds
        for _ in range(5):
            self.window.tick()
        self.assertEqual(self.window.player.elapsed_seconds, before)
        self.window.set_reduced_motion(False)
        self.window.tick()
        self.assertGreater(self.window.player.elapsed_seconds, before)

    def test_focus_restores_latest_saved_movement_choice(self):
        self.window.start_focus(5)
        self.window.set_mode("follow")
        self.window.start_focus(0)
        self.assertEqual(self.window.movement.mode, "follow")


if __name__ == "__main__":
    unittest.main()
