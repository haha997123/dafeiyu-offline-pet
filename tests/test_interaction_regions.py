from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from pet.interaction import InteractionController


class InteractionRegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def classify(self, x: float, y: float) -> str:
        return InteractionController.classify_region(x, y, 0.0, 0.0, 100.0, 100.0)

    def test_face_head_tail_and_body_have_distinct_hit_regions(self) -> None:
        self.assertEqual(self.classify(50, 30), "face")
        self.assertEqual(self.classify(20, 15), "head")
        self.assertEqual(self.classify(82, 66), "tail")
        self.assertEqual(self.classify(50, 70), "body")

    def test_points_outside_character_bounds_fall_back_to_body(self) -> None:
        self.assertEqual(self.classify(-4, 50), "body")
        self.assertEqual(
            InteractionController.classify_region(1, 1, 0, 0, 0, 100),
            "body",
        )

    @staticmethod
    def press(controller: InteractionController) -> None:
        controller.press(QPoint(200, 200), 50, 70, 0, 0, 100, 100)

    def test_eight_pixel_pointer_jitter_remains_a_click(self) -> None:
        controller = InteractionController()
        self.press(controller)
        self.assertFalse(controller.move(QPoint(208, 200)))
        self.assertFalse(controller.dragging)
        outcome = controller.release(QPoint(208, 200))
        self.assertEqual(outcome.kind, "click")
        self.assertEqual(outcome.body_region, "body")
        self.assertFalse(controller.active)

    def test_drag_threshold_respects_system_distance_and_ten_pixel_minimum(self) -> None:
        for system_distance in (4, 10, 18):
            with self.subTest(system_distance=system_distance), patch.object(
                QApplication, "startDragDistance", return_value=system_distance
            ):
                controller = InteractionController()
                self.press(controller)
                threshold = max(10, system_distance)
                self.assertFalse(controller.move(QPoint(200 + threshold, 200)))
                self.assertTrue(controller.move(QPoint(201 + threshold, 200)))
                # Returning near the press point does not undo a real drag.
                self.assertTrue(controller.move(QPoint(202, 200)))
                outcome = controller.release(QPoint(202, 200))
                self.assertEqual(outcome.kind, "drag")
                self.assertFalse(controller.active)
                self.assertFalse(controller.dragging)

    def test_pointer_movement_without_a_press_cannot_start_a_drag(self) -> None:
        controller = InteractionController()
        self.assertFalse(controller.move(QPoint(500, 400)))
        self.assertIsNone(controller.release(QPoint(500, 400)))


if __name__ == "__main__":
    unittest.main()
