"""Guard opt-in ambient audio without opening devices or a microphone."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from animation.clip import PetAction
from companion.window import CompanionPetWindow


def companion():
    return SimpleNamespace(
        _next_ambient_voice_at=0.0,
        speech=SimpleNamespace(enabled=True, automatic=True),
        _focus_end=0.0,
        _quiet_now=lambda: False,
        isVisible=lambda: True,
        interaction=SimpleNamespace(active=False),
        action_machine=SimpleNamespace(current=PetAction.IDLE),
        care_panel=None, control_panel=None, food_panel=None, hub=None, alarm_dialog=None,
        _voice_for=Mock(),
    )


@pytest.mark.parametrize("gate", ["disabled", "manual_only", "focus", "quiet", "hidden", "drag", "sleep", "panel"])
def test_ambient_voice_respects_quiet_and_explicit_opt_in(gate):
    window = companion()
    if gate == "disabled":
        window.speech.enabled = False
    elif gate == "manual_only":
        window.speech.automatic = False
    elif gate == "focus":
        window._focus_end = 500.0
    elif gate == "quiet":
        window._quiet_now = lambda: True
    elif gate == "hidden":
        window.isVisible = lambda: False
    elif gate == "drag":
        window.interaction.active = True
    elif gate == "sleep":
        window.action_machine.current = PetAction.SLEEPING
    else:
        window.hub = SimpleNamespace(isVisible=lambda: True)
    with patch("companion.window.time.monotonic", return_value=100.0):
        CompanionPetWindow._ambient_voice_tick(window)
    window._voice_for.assert_not_called()
    assert 190.0 <= window._next_ambient_voice_at <= 280.0


def test_due_ambient_voice_is_automatic_and_does_not_repeat_every_tick():
    window = companion()
    with patch("companion.window.time.monotonic", return_value=100.0), \
            patch("companion.window.random.uniform", return_value=120.0), \
            patch("companion.window.random.choice", return_value="idle"):
        CompanionPetWindow._ambient_voice_tick(window)
        CompanionPetWindow._ambient_voice_tick(window)
    window._voice_for.assert_called_once_with("idle")
    assert window._next_ambient_voice_at == 220.0


def test_manual_line_button_only_uses_existing_preview():
    window = SimpleNamespace(show=Mock(), preview_voice=Mock())
    CompanionPetWindow.interact(window, "say")
    window.show.assert_called_once_with()
    window.preview_voice.assert_called_once_with()
