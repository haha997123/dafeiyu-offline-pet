from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QPoint, QRect
from pet.movement import MovementController


class FakePet:
    def __init__(self):
        self.position = QPoint(0, 0)
        self.area = QRect(0, 0, 1200, 900)
    def x(self): return self.position.x()
    def y(self): return self.position.y()
    def width(self): return 200
    def height(self): return 280
    def cursor(self): return SimpleNamespace(pos=lambda: QPoint(700, 500))
    def screen(self): return SimpleNamespace(availableGeometry=lambda: self.area)
    def move(self, x, y): self.position = QPoint(x, y)


def test_floating_follow_moves_both_axes_towards_mouse():
    pet = FakePet()
    movement = MovementController("follow")
    movement.free_vertical = True
    with patch("pet.movement.QApplication.screenAt", return_value=pet.screen()):
        assert movement.update(pet, now=10, delta_seconds=0.1, set_direction=lambda *_: None)
    assert pet.x() > 0
    assert pet.y() > 0


def test_gravity_follow_preserves_platform_height():
    pet = FakePet()
    movement = MovementController("follow")
    with patch("pet.movement.QApplication.screenAt", return_value=pet.screen()):
        movement.update(pet, now=10, delta_seconds=0.1, set_direction=lambda *_: None)
    assert pet.x() > 0
    assert pet.y() == 0
