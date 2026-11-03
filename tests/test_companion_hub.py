"""Offscreen interaction tests for the companion journal contract."""
import copy
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent

MODULE_PATH = Path(__file__).resolve().parents[1] / "companion" / "hub.py"
spec = importlib.util.spec_from_file_location("companion_hub_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CompanionHub = module.CompanionHub


class FakeStore:
    def __init__(self):
        self.data = {
            "profile": {"owner_name": "小青", "nickname": "阿青", "pet_name": "大肥鱼", "likes": ["雨天", "蛋糕"]},
            "settings": {"voice_enabled": False, "voice_auto": False, "voice_id": "", "voice_rate": 0, "voice_volume": 75},
            "created_at": "2026-11-01T08:00:00+08:00", "days_together": 2,
            "total_points": 30, "level": 1, "stage": "初次见面", "next_level_points": 100, "daily_points": 20,
            "today_care": {"feed": 2, "pat": 1, "play": 0}, "total_care": {"feed": 3, "pat": 4, "play": 2},
            "events": [{"id": "event1", "at": "2026-11-02T09:00:00+08:00", "kind": "feed", "title": "吃饱啦", "detail": "认真吃完了", "food": "shrimp"}],
            "event_count": 1, "notes": [{"id": "note1", "at": "2026-11-02T09:00:00+08:00", "text": "喜欢下雨天"}], "reminders": [],
        }

    def snapshot(self):
        return copy.deepcopy(self.data)

    def update_profile(self, profile):
        self.data["profile"].update(profile)

    def set_setting(self, key, value):
        self.data["settings"][key] = value

    def remember(self, text):
        self.data["notes"].append({"id": "new-note", "at": "2026-11-02T12:00:00+08:00", "text": text})

    def forget_note(self, note_id):
        self.data["notes"] = [note for note in self.data["notes"] if note["id"] != note_id]

    def add_reminder(self, text, due_at):
        self.data["reminders"].append({"id": "reminder1", "text": text, "due_at": due_at, "done": False})

    def complete_reminder(self, reminder_id):
        for reminder in self.data["reminders"]:
            if reminder["id"] == reminder_id:
                reminder["done"] = True


class FakeSpeech:
    def __init__(self):
        self.available = False
        self.error = ""
        self.voices = []
        self.configurations = []
        self.spoken = []
        self.stopped = False

    def configure(self, enabled, **kwargs):
        self.configurations.append((enabled, kwargs))

    def speak(self, text, automatic=False):
        self.spoken.append(text)

    def stop(self):
        self.stopped = True


class CompanionHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = FakeStore()
        self.speech = FakeSpeech()
        self.hub = CompanionHub(self.store, self.speech)

    def tearDown(self):
        self.hub._voice_timer.stop()
        self.hub._clock_timer.stop()
        self.hub._voice_save_timer.stop()
        self.hub.deleteLater()
        self.app.processEvents()

    def test_care_emits_selected_food_without_recording_twice(self):
        events = []
        self.hub.interaction_requested.connect(lambda kind, food: events.append((kind, food)))
        self.hub.food_combo.setCurrentIndex(self.hub.food_combo.findData("蛋糕"))
        self.hub.feed_button.click()
        self.assertEqual(events, [("feed", "蛋糕")])
        self.assertEqual(self.store.data["event_count"], 1)
        self.assertEqual(self.store.data["total_points"], 30)

    def test_profile_and_explicit_memories_survive_refresh(self):
        self.hub.profile_fields["nickname"].setText("小雨")
        self.hub._save_profile()
        self.assertEqual(self.store.data["profile"]["nickname"], "小雨")
        self.hub.note_input.setPlainText("工作时喜欢安静")
        self.hub._remember()
        self.hub.memory_search.setText("安静")
        self.assertEqual(self.hub.note_list.count(), 1)
        self.assertIn("手动记住", self.hub.note_list.item(0).text())
        self.hub.note_list.setCurrentRow(0)
        self.hub._forget()
        self.assertEqual(len(self.store.data["notes"]), 1)

    def test_event_search_includes_specific_food(self):
        self.hub.memory_search.setText("虾")
        self.assertEqual(self.hub.timeline_list.count(), 1)
        self.assertIn("虾", self.hub.timeline_list.item(0).text())
        self.hub.memory_search.setText("不存在的东西")
        self.assertIn("没有找到", self.hub.timeline_list.item(0).text())

    def test_voice_can_become_available_after_window_creation(self):
        self.assertIn("正在准备", self.hub.voice_status.text())
        self.speech.voices = [{"id": "dafeiyu-character", "name": "大肥鱼角色语音包"}]
        self.speech.available = True
        self.hub._refresh_voices()
        self.assertIn("角色语音包已就绪", self.hub.voice_status.text())
        self.hub.voice_enabled.setChecked(True)
        self.hub._preview_voice()
        self.assertEqual(self.store.data["settings"]["voice_id"], "dafeiyu-character")
        self.assertTrue(self.speech.configurations[-1][0])
        self.assertIn("大肥鱼", self.speech.spoken[-1])
        self.hub._stop_voice()
        self.assertTrue(self.speech.stopped)

    def test_voice_import_buttons_emit_chosen_paths_without_enabling_or_playing(self):
        imports = []
        self.hub.voice_import_requested.connect(imports.append)
        with patch.object(module.QFileDialog, "getOpenFileName", return_value=("C:/语音/我的角色.zip", "ZIP 语音包 (*.zip)")) as chooser:
            self.hub.voice_import_zip_button.click()
            self.assertIn("*.zip", chooser.call_args.args[3])
        with patch.object(module.QFileDialog, "getExistingDirectory", return_value="C:/语音/我的语音文件夹"):
            self.hub.voice_import_folder_button.click()
        self.assertEqual(imports, ["C:/语音/我的角色.zip", "C:/语音/我的语音文件夹"])
        self.assertFalse(self.hub.voice_enabled.isChecked())
        self.assertFalse(self.store.data["settings"]["voice_enabled"])
        self.assertEqual(self.speech.configurations, [])
        self.assertEqual(self.speech.spoken, [])

    def test_cancelled_voice_choosers_do_nothing_and_status_survives_refresh(self):
        imports = []
        self.hub.voice_import_requested.connect(imports.append)
        self.hub.set_voice_import_status("已导入：我的角色 · 12 条语音")
        with patch.object(module.QFileDialog, "getOpenFileName", return_value=("", "")):
            self.hub.voice_import_zip_button.click()
        with patch.object(module.QFileDialog, "getExistingDirectory", return_value=""):
            self.hub.voice_import_folder_button.click()
        self.hub.refresh()
        self.assertEqual(imports, [])
        self.assertIn("12 条", self.hub.voice_import_status.text())
        self.assertFalse(self.hub.voice_import_status.isHidden())
        self.hub.set_voice_import_status("")
        self.assertTrue(self.hub.voice_import_status.isHidden())

    def test_newly_imported_voice_refreshes_selection_without_autoplay(self):
        self.speech.voices = [{"id": "community", "name": "社区角色原声"}, {"id": "imported-mine", "name": "我的角色"}]
        self.speech.voice_id = "imported-mine"
        self.store.data["settings"]["voice_id"] = "imported-mine"
        self.hub.refresh()
        self.assertEqual(self.hub.voice_choice.currentData(), "imported-mine")
        self.assertEqual(self.speech.spoken, [])
        self.assertEqual(self.speech.configurations, [])
        self.assertFalse(self.hub.voice_enabled.isChecked())

    def test_reminder_and_navigation_work_without_model_or_host(self):
        self.hub.reminder_text.setText("喝一杯水")
        self.hub._add_reminder()
        self.assertEqual(self.store.data["reminders"][0]["text"], "喝一杯水")
        self.hub._complete_reminder("reminder1")
        self.assertTrue(self.store.data["reminders"][0]["done"])
        for name in ("home", "memory", "growth", "settings"):
            self.hub.show_page(name)
            self.assertIs(self.hub.stack.currentWidget(), self.hub._pages[name])
        self.hub.show()
        self.app.processEvents()
        self.hub.close()
        self.assertFalse(self.hub.isVisible())

    def test_refresh_preserves_unsaved_profile_edits(self):
        self.hub.profile_fields["nickname"].setText("还没保存")
        self.hub._profile_edited()
        self.hub.refresh()
        self.assertEqual(self.hub.profile_fields["nickname"].text(), "还没保存")
        self.assertEqual(self.store.data["profile"]["nickname"], "阿青")

    def test_highest_growth_stage_and_calendar_gate_are_clear(self):
        self.store.data.update(total_points=150, next_level_points=120, next_level_days=3, days_together=1)
        self.hub.refresh()
        self.assertIn("2 天陪伴", self.hub.growth_next.text())
        self.store.data.update(level=8, stage="岁月老友", total_points=4200, next_level_points=None, next_level_days=None)
        self.hub.refresh()
        self.assertIn("最高阶段", self.hub.growth_next.text())

    def test_focus_can_start_once_and_stop_without_extra_controller(self):
        requests = []
        self.hub.focus_requested.connect(requests.append)
        self.hub._focus(25)
        self.hub._focus(25)
        self.assertEqual(requests, [25])
        self.assertFalse(self.hub.focus_button.isEnabled())
        self.hub.set_focus_status("还剩 24 分钟", running=True)
        self.assertIn("24", self.hub.focus_status.text())
        self.hub._focus(0)
        self.assertEqual(requests, [25, 0])
        self.assertTrue(self.hub.focus_button.isEnabled())

    def test_rituals_unlock_by_stage_and_only_emit_actions(self):
        events = []
        self.hub.interaction_requested.connect(lambda kind, food: events.append((kind, food)))
        self.assertFalse(self.hub.ritual_buttons[2].isEnabled())
        self.store.data["level"] = 3
        self.hub.refresh()
        self.assertTrue(self.hub.ritual_buttons[2].isEnabled())
        self.assertTrue(self.hub.ritual_buttons[3].isEnabled())
        self.assertFalse(self.hub.ritual_buttons[4].isEnabled())
        self.hub.ritual_buttons[3].click()
        self.assertEqual(events, [("ritual:tidy", "")])
        self.assertEqual(self.store.data["event_count"], 1)

    def test_journal_close_is_accepted_and_escape_and_return_button_work(self):
        event = QCloseEvent()
        self.hub.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.hub.show()
        self.hub.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(self.hub.isVisible())
        self.hub.show()
        self.hub.show_page("settings")
        self.hub.return_to_pet_button.click()
        self.assertFalse(self.hub.isVisible())


if __name__ == "__main__":
    unittest.main()
