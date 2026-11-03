"""Test local voice selection, real decoded data and playback gates without sound."""
import os
import wave
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from companion.voicepack import VoicePackService


def test_character_pack_has_real_pcm_samples_and_manual_preview_works():
    app = QApplication.instance() or QApplication([])
    service = VoicePackService(Path(__file__).resolve().parents[1] / "assets/voicepack")
    try:
        assert service.available
        assert len(service._clips) >= 20
        for clip in service._clips:
            with wave.open(str(clip["path"]), "rb") as sound:
                assert sound.getnframes() > sound.getframerate() / 2
                assert any(sound.readframes(sound.getnframes()))
        service.configure(True, automatic=False)
        with patch.object(service._player, "play") as play:
            assert service.play("preview", automatic=False) == "我一直都在这里的哦。"
            play.assert_called_once()
            assert not service.play("idle", automatic=True)
    finally:
        service.close()


def test_ambient_cooldown_and_voice_switch_are_independent_of_clicks():
    app = QApplication.instance() or QApplication([])
    service = VoicePackService(Path(__file__).resolve().parents[1] / "assets/voicepack")
    try:
        service.configure(True, automatic=True)
        with patch.object(service._player, "play"), patch("companion.voicepack.time.monotonic", return_value=100):
            assert service.play("idle", automatic=True)
            assert service.play("idle", automatic=True) is None
            assert service.play("pat", automatic=False)
        service.configure(False)
        with patch.object(service._player, "play") as play:
            assert not service.speak("试听", automatic=False)
            play.assert_not_called()
    finally:
        service.close()


def test_rejected_synthetic_voices_are_removed_and_legacy_choice_falls_back():
    app = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1] / "assets/voicepack"
    service = VoicePackService(root)
    try:
        assert {voice["id"] for voice in service.voices} == {"community"}
        assert not (root / "styles").exists()
        service.configure(True, voice_id="cute")
        assert service.voice_id == "community"
        with patch.object(service._player, "play"):
            assert service.play("preview") == "我一直都在这里的哦。"
            assert Path(service._player.source().toLocalFile()) == root / "click4.wav"
    finally:
        service.close()
