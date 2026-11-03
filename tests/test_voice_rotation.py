"""Voice variety uses real manifests but never opens an audio stream."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from companion.voicepack import VoicePackService


@pytest.fixture
def voice():
    application = QApplication.instance() or QApplication([])
    service = VoicePackService(Path(__file__).resolve().parents[1] / "assets/voicepack")
    service.configure(True, automatic=True)
    clock = [100.0]
    with patch.object(service._player, "play"), patch.object(service._player, "setSource"), patch(
        "companion.voicepack.time.monotonic", side_effect=lambda: clock[0]
    ):
        yield service, clock
    service.close()


def next_line(service, clock, category):
    clock[0] += 10
    result = service.play(category)
    assert result
    return service._last_id


def test_preview_cycles_every_available_line_before_repeating(voice):
    service, clock = voice
    expected = {clip["id"] for clip in service._clips}
    first = [next_line(service, clock, "preview") for _ in expected]
    assert len(first) == len(set(first)) == 22
    assert set(first) == expected
    following = next_line(service, clock, "preview")
    assert following != first[-1]


def test_each_scene_rotates_without_preview_spending_its_lines(voice):
    service, clock = voice
    expected = {clip["id"] for clip in service._clips if clip["category"] == "idle"}
    selected = []
    for _ in expected:
        selected.append(next_line(service, clock, "idle"))
        next_line(service, clock, "preview")
    assert set(selected) == expected
    assert len(selected) == len(set(selected))


def test_failed_cooldown_and_disabled_voice_do_not_consume_rotation(voice):
    service, clock = voice
    next_line(service, clock, "preview")
    before = {key: list(value) for key, value in service._rotation_bags.items()}
    assert service.play("preview") is None
    assert service._rotation_bags == before
    service.configure(False)
    clock[0] += 10
    assert service.play("preview") is None
    assert service._rotation_bags == before


def test_full_pool_is_explicit_and_changing_packs_resets_rotation(voice):
    service, clock = voice
    assert service.voice_id == "community"
    assert all(clip["enabled_default"] for clip in service._clips)
    next_line(service, clock, "preview")
    with patch.object(service, "stop", wraps=service.stop) as stop:
        service.configure(True, voice_id="community-full")
        stop.assert_called_once()
    assert not service._rotation_bags
    assert len(service._clips) == 49
    assert any(not clip["enabled_default"] for clip in service._clips)
    selected = [next_line(service, clock, "preview") for _ in range(49)]
    assert len(set(selected)) == 49
    assert all(clip["path"].is_file() for clip in service._clips)
    service.configure(True, voice_id="community")
    assert not service._rotation_bags
    assert len(service._clips) == 22


def test_pat_and_work_have_several_appropriate_responses(voice):
    service, clock = voice
    assert {next_line(service, clock, "pat") for _ in range(3)} == {"click2", "click4", "idle6"}
    assert {next_line(service, clock, "work") for _ in range(4)} == {"think1", "idle3", "click3", "click4"}
