"""Real controller/library import checks. No audio or real user data is used."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QMessageBox

from app.paths import AppPaths
from companion.voicepacks import VoicePackLibrary
from companion.window import CompanionPetWindow
from settings.config import ConfigManager


SOURCE_ROOT = Path(__file__).resolve().parents[1]


def silent_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 2400)
    return buffer.getvalue()


class VoiceImportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.previous_quit = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.previous_quit)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dafeiyu-voice-integration-")
        self.root = Path(self.temp.name)
        self.data = self.root / "user-data"
        self.env = patch.dict(os.environ, {"DAFEIYU_DATA_DIR": str(self.data), "DAFEIYU_SILENT": "1", "DAFEIYU_NO_HUB": "1", "DAFEIYU_OPEN_JOURNAL": "0"})
        self.env.start()
        # Even preview tests cannot physically start QMediaPlayer playback.
        self.audio_patch = patch.object(QMediaPlayer, "play")
        self.audio_play = self.audio_patch.start()
        self.windows = []
        self.window = self.make_window()

    def tearDown(self):
        try:
            for window in list(self.windows):
                self.dispose(window)
            self.app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            self.audio_patch.stop()
            self.env.stop()
            self.temp.cleanup()

    def make_window(self):
        paths = AppPaths(app_dir=self.data, bundle_dir=SOURCE_ROOT)
        paths.ensure_user_dirs()
        config = ConfigManager(paths.config_path)
        config.set("topmost", False)
        config.set_nested("awareness", "enabled", False)
        config.set_nested("comfort", "desktop_surfaces", False)
        config.set_nested("updates", "enabled", False)
        window = CompanionPetWindow(paths, config)
        self.windows.append(window)
        for widget in (window, window.hub, window.care_panel, window.food_panel, window.control_panel):
            for timer in widget.findChildren(QTimer):
                timer.stop()
        self.app.processEvents()
        self.assertIsInstance(window.voice_library, VoicePackLibrary)
        self.assertFalse(window.speech.enabled)
        return window

    def dispose(self, window):
        self.windows.remove(window)
        window.shutdown_companion()
        try:
            self.app.aboutToQuit.disconnect(window.shutdown_companion)
        except (RuntimeError, TypeError):
            pass
        window.tray.hide()
        for widget in (window.hub, window.care_panel, window.food_panel, window.control_panel, window):
            widget.hide()
            widget.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def pack_zip(self, name="自己的小鱼", *, manifest=True):
        target = self.root / (name + ".zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            filename = "hello.wav" if manifest else "01_没有校验字幕的小鱼叫声.wav"
            archive.writestr("release/" + filename, silent_wav())
            if manifest:
                archive.writestr("release/manifest.json", json.dumps({"name": name, "clips": [{"id": "mine-greet", "category": "greet", "file": filename, "text": "这是我自己带来的声音。"}]}, ensure_ascii=False))
        return target

    def selected(self):
        return self.window.companion_store.snapshot()["settings"]["voice_id"]

    def test_hub_import_signal_selects_new_pack_without_enabling_or_playing(self):
        store = self.window.companion_store
        store.remember("主人喜欢热茶。")
        before = store.snapshot()
        source = self.pack_zip()
        with patch.object(self.window.speech, "stop", wraps=self.window.speech.stop) as stop:
            self.window.hub.voice_import_requested.emit(str(source))
            stop.assert_called()
        imported = self.window.voice_library.list_packs()
        self.assertEqual(len(imported), 1)
        pack_id = imported[0]["id"]
        self.assertTrue(pack_id.startswith("user:"))
        self.assertEqual(self.selected(), pack_id)
        self.assertEqual(self.window.speech.voice_id, pack_id)
        self.assertEqual(self.window.hub.voice_choice.currentData(), pack_id)
        self.assertFalse(store.snapshot()["settings"]["voice_enabled"])
        self.assertFalse(self.window.speech.enabled)
        self.assertFalse(self.window.hub.voice_enabled.isChecked())
        self.assertEqual(store.snapshot()["notes"], before["notes"])
        self.assertEqual(store.snapshot()["events"], before["events"])
        self.assertIn("已导入", self.window.hub.voice_import_status.text())
        self.audio_play.assert_not_called()

    def test_imported_selection_and_copied_audio_survive_real_window_restart(self):
        source = self.pack_zip()
        self.window.import_voice_pack(source)
        pack_id = self.selected()
        source.unlink()
        self.dispose(self.window)
        self.window = self.make_window()
        self.assertEqual(self.selected(), pack_id)
        self.assertEqual(self.window.speech.voice_id, pack_id)
        self.assertEqual(self.window.hub.voice_choice.currentData(), pack_id)
        pack = next(pack for pack in self.window.voice_library.list_packs() if pack["id"] == pack_id)
        self.assertTrue(pack["clips"][0]["path"].is_file())
        self.assertFalse(self.window.speech.enabled)
        self.audio_play.assert_not_called()

    def test_general_only_pack_can_preview_with_unverified_caption_without_matching_memory(self):
        self.window.import_voice_pack(self.pack_zip(manifest=False))
        self.assertEqual({clip["category"] for clip in self.window.speech._clips}, {"general"})
        self.assertFalse(self.window.speech._clips[0]["caption_known"])
        # This is only a service flag for the tested slot; QMediaPlayer.play is
        # patched for the whole fixture, and no source can produce real audio.
        self.window.speech.configure(True, voice_id=self.selected(), automatic=True)
        self.window._voice_for("preview", manual=True)
        self.audio_play.assert_called_once()
        self.assertEqual(self.window.bubble.text, "（播放导入的语音片段）")
        self.assertNotIn("没有校验字幕", self.window.bubble.text)
        self.audio_play.reset_mock()
        self.assertFalse(self.window.speech.speak("主人喜欢热茶。", automatic=True))
        self.audio_play.assert_not_called()

    def test_invalid_zip_only_warns_and_preserves_selection_memory_and_existing_pack(self):
        self.window.import_voice_pack(self.pack_zip())
        self.window.companion_store.remember("不喜欢冷饮。")
        before = self.window.companion_store.snapshot()
        previous_id = self.selected()
        pack_ids = [pack["id"] for pack in self.window.voice_library.list_packs()]
        bad = self.root / "broken.zip"
        bad.write_bytes(b"PK\x03\x04not-an-archive")
        self.audio_play.reset_mock()
        with patch.object(QMessageBox, "warning") as warning:
            self.window.hub.voice_import_requested.emit(str(bad))
            warning.assert_called_once()
        after = self.window.companion_store.snapshot()
        self.assertEqual(after["settings"], before["settings"])
        self.assertEqual(after["profile"], before["profile"])
        self.assertEqual(after["notes"], before["notes"])
        self.assertEqual(after["events"], before["events"])
        self.assertEqual(self.window.speech.voice_id, previous_id)
        self.assertEqual(self.window.hub.voice_choice.currentData(), previous_id)
        self.assertEqual([pack["id"] for pack in self.window.voice_library.list_packs()], pack_ids)
        self.assertIn("导入没有完成", self.window.hub.voice_import_status.text())
        self.audio_play.assert_not_called()

    def test_settings_preview_displays_actual_unknown_caption_instead_of_previous_dialogue(self):
        self.window.import_voice_pack(self.pack_zip(manifest=False))
        self.window.bubble.text = "上一次显示的旧台词"
        with patch.dict(os.environ, {"DAFEIYU_SILENT": "0"}):
            self.window.hub._preview_voice()
        self.audio_play.assert_called_once()
        self.assertEqual(self.window.bubble.text, "（播放导入的语音片段）")
        self.assertTrue(self.window.companion_store.snapshot()["settings"]["voice_enabled"])

    def test_switching_voice_in_hub_stops_previous_pack_without_autoplay(self):
        self.window.import_voice_pack(self.pack_zip())
        self.window.speech.configure(True, voice_id=self.selected(), automatic=True)
        self.window.companion_store.set_setting("voice_enabled", True)
        self.window.hub.refresh()
        with patch.dict(os.environ, {"DAFEIYU_SILENT": "0"}), patch.object(self.window.speech._player, "stop", wraps=self.window.speech._player.stop) as stop:
            self.window.hub.voice_choice.setCurrentIndex(self.window.hub.voice_choice.findData("community"))
            stop.assert_called()
        self.assertEqual(self.selected(), "community")
        self.audio_play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
