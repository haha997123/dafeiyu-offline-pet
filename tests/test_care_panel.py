"""Exercise the transient interaction card without a desktop or model."""
import importlib.util
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton

spec = importlib.util.spec_from_file_location("care_panel_under_test", Path(__file__).resolve().parents[1] / "companion/care_panel.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CarePanel = module.CarePanel


class CarePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = CarePanel()

    def tearDown(self):
        self.panel.hide()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_snapshot_changes_relationship_and_voice_without_emitting(self):
        emissions = []
        self.panel.voice_toggled.connect(emissions.append)
        self.panel.refresh({"profile": {"pet_name": "小鲸"}, "days_together": 12, "stage": "熟悉搭档", "settings": {"voice_enabled": True}})
        self.assertEqual(self.panel.pet_name.text(), "小鲸")
        self.assertIn("12", self.panel.relationship.text())
        self.assertIn("熟悉搭档", self.panel.relationship.text())
        self.assertEqual(self.panel.voice_button.text(), "声音 开")
        self.assertEqual(emissions, [])

    def test_every_food_emits_chinese_food_and_hides_card(self):
        events = []
        self.panel.interaction_requested.connect(lambda kind, food: events.append((kind, food)))
        for food, button in self.panel.food_buttons.items():
            self.panel.show()
            button.click()
            self.assertEqual(events[-1], ("feed", food))
            self.assertFalse(self.panel.isVisible())
        self.assertEqual(len(events), 4)

    def test_care_actions_emit_and_journal_appearance_links_hide(self):
        events, links = [], []
        self.panel.interaction_requested.connect(lambda kind, food: events.append((kind, food)))
        self.panel.journal_requested.connect(lambda: links.append("journal"))
        self.panel.appearance_requested.connect(lambda: links.append("appearance"))
        for kind, button in self.panel.action_buttons.items():
            button.click()
            self.assertEqual(events[-1], (kind, ""))
        self.panel.show()
        self.panel.journal_button.click()
        self.assertFalse(self.panel.isVisible())
        self.panel.show()
        self.panel.appearance_button.click()
        self.assertFalse(self.panel.isVisible())
        self.assertEqual(links, ["journal", "appearance"])

    def test_voice_toggle_stays_open_and_preview_is_separate(self):
        voices, previews = [], []
        self.panel.voice_toggled.connect(voices.append)
        self.panel.preview_requested.connect(lambda: previews.append(True))
        self.panel.show()
        self.panel.voice_button.click()
        self.assertTrue(self.panel.isVisible())
        self.assertEqual(voices, [True])
        self.assertEqual(self.panel.voice_button.text(), "声音 开")
        self.panel.preview_button.click()
        self.assertEqual(previews, [True])
        self.assertEqual(voices, [True])
        self.panel.refresh({}, voice_ready=False)
        self.assertFalse(self.panel.voice_button.isEnabled())
        self.assertFalse(self.panel.preview_button.isEnabled())
        self.assertTrue(self.panel.food_buttons["白饭"].isEnabled())

    def test_escape_and_close_hide_without_deleting(self):
        self.panel.show()
        self.panel.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(self.panel.isVisible())
        self.panel.show()
        self.panel.close()
        self.panel.show()
        self.assertTrue(self.panel.isVisible())

    def test_position_stays_inside_primary_and_negative_coordinate_screens(self):
        size = QSize(324, 378)
        for available in (QRect(0, 0, 1280, 720), QRect(-1920, 0, 1920, 1080), QRect(-1280, -900, 1280, 900)):
            for x in (available.left(), available.center().x(), available.right() - 80):
                for y in (available.top(), available.center().y(), available.bottom() - 100):
                    point = CarePanel._position_for(QRect(x, y, 80, 100), available, size)
                    self.assertTrue(available.contains(QRect(point, size)), (available, point))
        beside = CarePanel._position_for(QRect(900, 300, 100, 150), QRect(0, 0, 1280, 720), size)
        self.assertLess(beside.x() + size.width(), 900)

    def test_buttons_have_stable_names_and_card_remains_compact(self):
        buttons = self.panel.findChildren(QPushButton)
        self.assertEqual(len(buttons), 16)
        names = [button.objectName() for button in buttons]
        self.assertTrue(all(names))
        self.assertEqual(len(names), len(set(names)))
        self.assertLessEqual(self.panel.width(), 340)
        self.assertLessEqual(self.panel.height(), 390)
        self.assertTrue(self.panel.windowFlags() & Qt.WindowType.Popup)
        self.panel.popup_near_pet(QRect(900, 300, 120, 160))
        self.assertTrue(self.panel.isVisible())

    def test_voice_settings_has_a_direct_labeled_entry(self):
        opened = []
        self.panel.voice_settings_requested.connect(lambda: opened.append(True))
        self.assertEqual(self.panel.appearance_button.text(), "外观设置")
        self.assertEqual(self.panel.voice_settings_button.text(), "音色")
        self.panel.show()
        self.panel.voice_settings_button.click()
        self.assertEqual(opened, [True])
        self.assertFalse(self.panel.isVisible())

    def test_visible_corner_close_button_reopens_without_recreating(self):
        self.panel.show()
        self.panel.close_button.click()
        self.assertFalse(self.panel.isVisible())
        self.panel.popup_near_pet(QRect(900, 300, 120, 160))
        self.assertTrue(self.panel.isVisible())


if __name__ == "__main__":
    unittest.main()
