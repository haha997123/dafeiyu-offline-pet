"""Real Qt controls, stub callbacks: never change Windows settings in tests."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from settings.panel import PetControlPanel


DEFAULTS = {
    "mode": "follow", "size": .7, "awareness": True,
    "read_window_title": False, "idle_detection": True, "topmost": True,
    "fullscreen_hide": False, "passthrough": False, "autostart": False,
    "activity_level": "calm", "walk_speed": 104., "reduced_motion": True,
    "hover_pause": False, "desktop_surfaces": True, "state_name": "待机",
}


class SettingsControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.calls = []
        names = ("mode", "size", "feed", "say", "snap", "awareness", "read_window_title", "idle_detection", "topmost", "fullscreen_hide", "passthrough", "autostart", "activity_level", "walk_speed", "reduced_motion", "hover_pause", "desktop_surfaces", "action", "hide", "privacy", "quit", "placement")
        callbacks = {"on_" + name: (lambda *args, n=name: self.calls.append((n, args))) for name in names}
        def boolean_callback(name):
            def callback(checked):
                self.calls.append((name, (checked,)))
            return callback
        for name in ("awareness", "read_window_title", "idle_detection", "topmost", "fullscreen_hide", "passthrough", "autostart", "reduced_motion", "hover_pause", "desktop_surfaces"):
            callbacks["on_" + name] = boolean_callback(name)
        self.panel = PetControlPanel(**callbacks)
        self.panel.sync(**DEFAULTS)

    def tearDown(self):
        self.panel.hide()
        self.panel.deleteLater()
        self.app.processEvents()

    def checked(self, name):
        return [value for value, button in getattr(self.panel, "_" + name + "_buttons").items() if button.isChecked()]

    def test_sync_keeps_all_groups_selected_and_emits_no_callbacks(self):
        self.assertEqual(self.checked("mode"), ["follow"])
        self.assertEqual(self.checked("size"), [.7])
        self.assertEqual(self.checked("activity"), ["calm"])
        self.assertEqual(self.checked("speed"), [104.])
        self.assertEqual(self.checked("placement"), ["floating"])
        self.assertEqual(self.calls, [])
        toggles = []
        for name in ("mode", "size", "activity", "speed", "placement"):
            for button in getattr(self.panel, "_" + name + "_buttons").values():
                button.toggled.connect(lambda value: toggles.append(value))
                self.assertFalse(button.autoExclusive())
        self.panel.sync(**{**DEFAULTS, "mode": "still", "size": .9, "activity_level": "lively", "walk_speed": 64., "placement": "gravity", "autostart": True})
        self.assertEqual(self.checked("mode"), ["still"])
        self.assertEqual(self.checked("size"), [.9])
        self.assertEqual(self.checked("activity"), ["lively"])
        self.assertEqual(self.checked("speed"), [64.])
        self.assertEqual(self.checked("placement"), ["gravity"])
        self.assertEqual(toggles, [])
        self.assertEqual(self.calls, [])

    def test_clicks_are_exclusive_within_each_section_and_independent_across_sections(self):
        self.panel._mode_buttons["still"].click()
        self.panel._size_buttons[.9].click()
        self.panel._activity_buttons["lively"].click()
        self.panel._speed_buttons[82.].click()
        self.panel._placement_buttons["gravity"].click()
        self.assertEqual(self.calls, [("mode", ("still",)), ("size", (.9,)), ("activity_level", ("lively",)), ("walk_speed", (82.,)), ("placement", ("gravity",))])
        self.assertEqual(self.checked("mode"), ["still"])
        self.assertEqual(self.checked("size"), [.9])
        self.assertEqual(self.checked("activity"), ["lively"])
        self.assertEqual(self.checked("speed"), [82.])
        self.assertEqual(self.checked("placement"), ["gravity"])

    def test_original_callback_contract_and_new_placement_default_remain_compatible(self):
        callbacks = {"on_" + name: lambda *args: None for name in ("mode", "size", "feed", "say", "snap", "awareness", "read_window_title", "idle_detection", "topmost", "fullscreen_hide", "passthrough", "autostart", "activity_level", "walk_speed", "reduced_motion", "hover_pause", "desktop_surfaces", "action", "hide", "privacy", "quit")}
        original_client = PetControlPanel(**callbacks)
        original_client.sync(**DEFAULTS)
        original_client._placement_buttons["gravity"].click()
        self.assertTrue(original_client._placement_buttons["gravity"].isChecked())
        original_client.deleteLater()

    def test_checkbox_sync_is_silent_and_user_callback_can_be_restored(self):
        self.panel.autostart.click()
        self.assertEqual(self.calls, [("autostart", (True,))])
        self.panel.sync(**DEFAULTS)
        self.assertFalse(self.panel.autostart.isChecked())
        self.assertEqual(len(self.calls), 1)

    def test_short_screen_expands_with_scroll_and_bottom_controls_are_reachable(self):
        self.panel.show()
        with patch.object(self.panel, "_available_area", return_value=QRect(0, 0, 800, 360)):
            self.panel._toggle_advanced()
            self.app.processEvents()
            self.panel._fit_to_content()
            self.app.processEvents()
            self.assertLessEqual(self.panel.height(), 348)
            self.assertGreater(self.panel._scroll.verticalScrollBar().maximum(), 0)
            quit_button = next(b for b in self.panel.findChildren(QPushButton) if b.text() == "退出")
            self.panel._scroll.ensureWidgetVisible(quit_button)
            self.app.processEvents()
            point = quit_button.mapTo(self.panel._scroll.viewport(), quit_button.rect().center())
            self.assertTrue(self.panel._scroll.viewport().rect().contains(point))
            self.assertTrue(self.panel.close_button.isVisible())
            self.assertTrue(self.panel.rect().contains(self.panel.close_button.mapTo(self.panel, self.panel.close_button.rect().center())))

    def test_collapse_shrinks_and_escape_and_close_allow_reopen(self):
        self.panel.popup_at(QPoint(20, 20))
        self.app.processEvents()
        compact = self.panel.height()
        self.panel._toggle_advanced()
        self.app.processEvents()
        self.assertGreater(self.panel.height(), compact)
        self.panel._toggle_advanced()
        self.app.processEvents()
        self.assertLessEqual(abs(self.panel.height() - compact), 2)
        self.panel.close_button.click()
        self.assertFalse(self.panel.isVisible())
        self.panel.popup_at(QPoint(20, 20))
        self.panel.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(self.panel.isVisible())
        self.panel.popup_near_pet(QRect(500, 300, 120, 170))
        self.assertTrue(self.panel.isVisible())

    def test_updated_action_labels_keep_original_callbacks(self):
        self.assertEqual(self.panel._mode_buttons["still"].text(), "原地")
        organize = next(b for b in self.panel.findChildren(QToolButton) if b.text() == "整理")
        organize.click()
        snap = next(b for b in self.panel.findChildren(QPushButton) if b.text() == "回到主屏")
        snap.click()
        self.assertEqual(self.calls, [("action", ("SWEEPING",)), ("snap", ())])

    def drag_header_by(self, delta):
        header = self.panel.drag_header
        local = QPoint(20, 12)
        start = header.mapToGlobal(local)
        finish = start + delta
        QApplication.sendEvent(header, QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(local), QPointF(start), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        QApplication.sendEvent(header, QMouseEvent(QEvent.Type.MouseMove, QPointF(local + delta), QPointF(finish), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        QApplication.sendEvent(header, QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(local + delta), QPointF(finish), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        self.app.processEvents()

    def test_header_drag_uses_global_offset_and_does_not_jump_back_when_expanding(self):
        self.panel.popup_near_pet(QRect(500, 300, 100, 140))
        self.app.processEvents()
        before = QPoint(self.panel.pos())
        delta = QPoint(70, -100)
        with patch.object(self.panel, "_screen_area", return_value=QRect(0, 0, 1800, 1400)):
            self.drag_header_by(delta)
            self.assertEqual(self.panel.pos(), before + delta)
            dragged = QPoint(self.panel.pos())
            self.panel._toggle_advanced()
            self.app.processEvents()
            self.assertEqual(self.panel.pos(), dragged)
            self.panel._toggle_advanced()
            self.app.processEvents()
            self.assertEqual(self.panel.pos(), dragged)
            self.panel._mode_buttons["still"].click()
            self.panel.sync(**DEFAULTS)
            self.assertEqual(self.panel.pos(), dragged)
        self.assertEqual(self.panel.windowTitle(), "大肥鱼 · 外观设置")
        self.assertEqual(self.panel.drag_header.cursor().shape(), Qt.CursorShape.SizeAllCursor)
        self.assertTrue(self.panel.state_label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_close_button_click_does_not_start_drag_and_popup_resets_anchor(self):
        self.panel.popup_at(QPoint(30, 40))
        self.app.processEvents()
        initial = QPoint(self.panel.pos())
        QTest.mouseClick(self.panel.close_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.panel.isVisible())
        self.assertEqual(self.panel.pos(), initial)
        self.panel.popup_at(QPoint(50, 60))
        self.app.processEvents()
        with patch.object(self.panel, "_screen_area", return_value=QRect(0, 0, 1800, 1400)):
            self.drag_header_by(QPoint(200, 80))
        dragged = QPoint(self.panel.pos())
        self.panel.popup_at(QPoint(50, 60))
        self.app.processEvents()
        self.assertNotEqual(self.panel.pos(), dragged)
        self.assertEqual(self.panel.pos(), QPoint(62, 72))

    def test_drag_clamps_panel_on_negative_coordinate_screen(self):
        self.panel.popup_at(QPoint(30, 40))
        self.app.processEvents()
        area = QRect(-1280, -900, 1280, 900)
        with patch.object(self.panel, "_screen_area", return_value=area):
            self.drag_header_by(QPoint(-3000, -3000))
            self.assertEqual(self.panel.pos(), area.topLeft())
            self.assertTrue(area.contains(self.panel.frameGeometry()))
            self.drag_header_by(QPoint(3000, 3000))
            self.assertEqual(self.panel.pos(), QPoint(area.right() - self.panel.width() + 1, area.bottom() - self.panel.height() + 1))
            header_rect = QRect(self.panel.drag_header.mapToGlobal(QPoint()), self.panel.drag_header.size())
            self.assertTrue(area.contains(header_rect))

    def test_complex_controls_explain_dependencies_and_recovery(self):
        for name in ("mode", "size", "activity", "speed", "placement"):
            for button in getattr(self.panel, "_" + name + "_buttons").values():
                self.assertTrue(button.toolTip().strip())
                self.assertEqual(button.toolTipDuration(), 20000)
        for toggle in (self.panel.awareness, self.panel.read_window_title, self.panel.idle_detection, self.panel.fullscreen_hide, self.panel.passthrough, self.panel.reduced_motion, self.panel.hover_pause, self.panel.desktop_surfaces, self.panel.autostart):
            self.assertTrue(toggle.toolTip().strip())
        for dependent in (self.panel.read_window_title, self.panel.idle_detection, self.panel.fullscreen_hide):
            self.assertIn("先开启本地感知", dependent.toolTip())
        self.assertIn("恢复鼠标互动", self.panel.passthrough.toolTip())
        self.assertIn("重力模式", self.panel.desktop_surfaces.toolTip())
        self.assertIn("聊天正文", self.panel.awareness.toolTip())


if __name__ == "__main__":
    unittest.main()
