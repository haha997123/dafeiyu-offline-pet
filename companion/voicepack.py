"""Local, prerecorded character audio. No network or fallback system voice."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer


class VoicePackService(QObject):
    def __init__(self, pack_dir: Path, parent=None, *, library=None):
        super().__init__(parent)
        self.pack_dir = Path(pack_dir).resolve()
        self.available = False
        self.error = ""
        self.voices = []
        self.voice_id = "community"
        self.library = library
        self._packs = {}
        self._builtin_clips = []
        self.enabled = False
        self.automatic = False
        self.volume = 75
        self._clips = []
        self._last_id = ""
        self._last_automatic_at = 0.0
        self._last_manual_at = 0.0
        self._closed = False
        self.selected_output = ""
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._devices = QMediaDevices(self)
        self._player.setAudioOutput(self._output)
        self._player.errorOccurred.connect(self._on_error)
        self._load()
        self.refresh_packs()

    def _load(self):
        try:
            manifest = json.loads((self.pack_dir / "manifest.json").read_text(encoding="utf-8"))
            clips = manifest.get("clips", [])
            if not isinstance(clips, list):
                raise ValueError("语音包清单格式错误")
            for clip in clips:
                if not isinstance(clip, dict) or not clip.get("enabled_default", False):
                    continue
                path = (self.pack_dir / str(clip.get("playback_file") or clip.get("file", ""))).resolve()
                if not path.is_relative_to(self.pack_dir) or not path.is_file():
                    continue
                if path.suffix.lower() not in {".mp3", ".wav", ".ogg"}:
                    continue
                if not all(isinstance(clip.get(key), str) and clip[key] for key in ("id", "category", "text")):
                    continue
                self._builtin_clips.append({**clip, "path": path, "caption_known": True})
            if not self._builtin_clips:
                raise ValueError("没有找到可播放的默认角色语音")
        except (OSError, ValueError, TypeError) as error:
            self.error = f"角色语音包不可用：{error}"

    def refresh_packs(self):
        packs = {}
        if self._builtin_clips:
            packs["community"] = {"id": "community", "name": "大肥鱼 · 社区角色原声", "clips": self._builtin_clips}
        if self.library is not None:
            try:
                for pack in self.library.list_packs():
                    if pack.get("clips"):
                        packs[pack["id"]] = pack
            except (OSError, ValueError) as error:
                self.error = f"导入语音库暂时无法读取：{error}"
        self._packs = packs
        self.voices = [{"id": pack["id"], "language": "zh-CN", "name": pack["name"]} for pack in packs.values()]
        if self.voice_id not in packs:
            self.voice_id = "community" if "community" in packs else next(iter(packs), "")
        self._clips = packs.get(self.voice_id, {}).get("clips", [])
        self.available = bool(self._clips)

    def configure(self, enabled, voice_id="", rate=0, volume=75, automatic=False):
        self.enabled = bool(enabled)
        chosen = voice_id if voice_id in self._packs else "community"
        if chosen != self.voice_id:
            self.stop()
        self.voice_id = chosen
        self._clips = self._packs.get(self.voice_id, {}).get("clips", [])
        self.available = bool(self._clips)
        self.automatic = bool(automatic)
        self.volume = max(0, min(100, int(volume)))
        self._output.setVolume(self.volume / 100)
        if not self.enabled or self.volume == 0:
            self.stop()
        if self.available and not self._output.device().isNull():
            self.error = ""

    @property
    def outputs(self):
        return [{"id": bytes(device.id().toHex()).decode("ascii"), "name": device.description(), "default": device.isDefault()}
                for device in QMediaDevices.audioOutputs()]

    @property
    def output_name(self):
        return self._output.device().description()

    def set_output(self, device_id=""):
        devices = QMediaDevices.audioOutputs()
        target = next((d for d in devices if bytes(d.id().toHex()).decode("ascii") == device_id), None)
        target = target or QMediaDevices.defaultAudioOutput()
        if not target.isNull():
            self._output.setDevice(target)
            self.error = "" if self.available else self.error
            self.selected_output = device_id if any(bytes(d.id().toHex()).decode("ascii") == device_id for d in devices) else ""
        elif self.available:
            self.error = "没有找到音频输出设备，请在设置中检查输出。"

    def _allowed(self, automatic):
        if self._closed or not self.enabled or not self.available or self.volume == 0:
            return False
        if automatic:
            if not self.automatic or self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                return False
            if time.monotonic() - self._last_automatic_at < 7.0:
                return False
        elif time.monotonic() - self._last_manual_at < 0.8:
            return False
        return True

    def _play_clip(self, clip, *, automatic):
        if not self._allowed(automatic):
            return None
        self._player.stop()
        self.error = ""
        path = clip["path"]
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        self._last_id = clip["id"]
        if automatic:
            self._last_automatic_at = time.monotonic()
        else:
            self._last_manual_at = time.monotonic()
        return clip["text"] if clip.get("caption_known", True) else "（播放导入的语音片段）"

    def play(self, category: str, *, automatic=False):
        preferred = {
            "preview": ("click4",),
            "pat": ("click4", "click2"),
            "thanks": ("click2",),
        }.get(category)
        candidates = [clip for clip in self._clips if clip["category"] == category]
        if not candidates and preferred:
            candidates = [clip for clip in self._clips if clip["id"] in preferred]
        if not candidates and category == "preview":
            candidates = self._clips[:1]
        if not candidates:
            candidates = [clip for clip in self._clips if clip["category"] == "general"]
        if not candidates:
            return None
        fresh = [clip for clip in candidates if clip["id"] != self._last_id]
        return self._play_clip(random.choice(fresh or candidates), automatic=automatic)

    def speak(self, text: str, *, automatic=False):
        # This API also serves the settings preview. Arbitrary journal text is
        # deliberately not paired with unrelated audio.
        normalized = str(text or "").strip()
        for clip in self._clips:
            if clip["text"].strip() == normalized:
                return bool(self._play_clip(clip, automatic=automatic))
        if not automatic:
            return bool(self.play("preview", automatic=False))
        return False

    def stop(self):
        self._player.stop()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.stop()
        self._player.setSource(QUrl())

    def _on_error(self, error, message):
        self.error = f"语音播放失败：{message or str(error)}"
