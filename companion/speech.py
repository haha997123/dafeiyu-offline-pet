"""Optional Windows system TTS, kept separate from the character voice pack.

The public methods never wait for COM or speech. All SAPI objects belong to one
background STA thread; importing this module needs neither Qt nor pywin32.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import re
import sys
import threading
from typing import Any


_SPEAK_FLAGS = 1 | 2 | 16  # asynchronous, purge old speech, literal text


def _number(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _voice_id(voices: list[dict[str, str]], requested: str) -> str:
    if any(voice["id"] == requested for voice in voices):
        return requested
    chinese: list[str] = []
    for voice in voices:
        for language in voice.get("language", "").split(";"):
            try:
                language_id = int(language.strip(), 16)
            except ValueError:
                continue
            if language_id == 0x804:
                return voice["id"]
            if language_id & 0x3FF == 4:
                chinese.append(voice["id"])
    return chinese[0] if chinese else (voices[0]["id"] if voices else "")


class _SapiBackend:
    """Only instantiate and access this object from its owning COM thread."""

    def __init__(self) -> None:
        self._pythoncom = import_module("pythoncom")
        self._initialized = False
        self._voice: Any = None
        self._tokens: dict[str, Any] = {}
        self.voices: list[dict[str, str]] = []
        try:
            self._pythoncom.CoInitializeEx(self._pythoncom.COINIT_APARTMENTTHREADED)
            self._initialized = True
            self._voice = import_module("win32com.client").Dispatch("SAPI.SpVoice")
            tokens = self._voice.GetVoices()
            for index in range(tokens.Count):
                token = tokens.Item(index)
                identifier = str(token.Id)
                try:
                    language = str(token.GetAttribute("Language"))
                except Exception:
                    language = ""
                self._tokens[identifier] = token
                self.voices.append({"id": identifier, "name": str(token.GetDescription()), "language": language})
            if not self.voices:
                raise RuntimeError("Windows 没有可用的系统语音")
        except Exception:
            self.close()
            raise

    def configure(self, voice_id: str, rate: int, volume: int) -> None:
        token = self._tokens.get(voice_id)
        if token is not None:
            self._voice.Voice = token
        self._voice.Rate = rate
        self._voice.Volume = volume

    def speak(self, text: str) -> None:
        self._voice.Speak(text, _SPEAK_FLAGS)

    def stop(self) -> None:
        if self._voice is not None:
            self._voice.Speak("", _SPEAK_FLAGS)

    def is_busy(self) -> bool:
        return not bool(self._voice.WaitUntilDone(0))

    def pump(self) -> None:
        self._pythoncom.PumpWaitingMessages()

    def close(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
        self._voice = None
        self._tokens.clear()
        if self._initialized:
            self._initialized = False
            self._pythoncom.CoUninitialize()


def _make_backend() -> _SapiBackend:
    if sys.platform != "win32":
        raise RuntimeError("系统朗读仅支持 Windows")
    return _SapiBackend()


@dataclass(frozen=True)
class _Settings:
    enabled: bool = False
    voice_id: str = ""
    rate: int = 0
    volume: int = 75
    automatic: bool = False


class SpeechService:
    """Nonblocking optional SAPI service. ``speak`` reports queue acceptance.

    Initialization is asynchronous: initially ``available`` is false. It becomes
    true once voices are enumerated, or ``error`` explains why it is unavailable.
    ``close`` is intentionally nonblocking and makes future requests fail.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._settings = _Settings()
        self._available = False
        self._error = ""
        self._voices: list[dict[str, str]] = []
        self._pending: tuple[str, bool, int] | None = None
        self._generation = 0
        self._stop_serial = 0
        self._busy = False
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="Dafeiyu-Optional-SAPI", daemon=True)
        self._thread.start()

    @property
    def available(self) -> bool:
        with self._condition:
            return self._available and not self._closed

    @property
    def error(self) -> str:
        with self._condition:
            return self._error

    @property
    def voices(self) -> list[dict[str, str]]:
        with self._condition:
            return [dict(voice) for voice in self._voices]

    def configure(self, enabled: bool, voice_id: str = "", rate: int = 0,
                  volume: int = 75, automatic: bool = False) -> None:
        settings = _Settings(bool(enabled), str(voice_id or ""), _number(rate, 0, -10, 10),
                             _number(volume, 75, 0, 100), bool(automatic))
        with self._condition:
            if self._closed:
                return
            previous = self._settings
            self._settings = settings
            if not settings.enabled or previous.voice_id != settings.voice_id:
                self._cancel_locked()
            elif not settings.automatic and self._pending and self._pending[1]:
                self._pending = None
            self._condition.notify()

    def speak(self, text: str, *, automatic: bool = False) -> bool:
        if not isinstance(text, str):
            return False
        clean = re.sub(r"\s+", " ", re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)).strip()[:300]
        if not clean:
            return False
        with self._condition:
            if self._closed or not self._available or not self._settings.enabled:
                return False
            if automatic and (not self._settings.automatic or self._busy or self._pending is not None):
                return False
            self._generation += 1
            self._pending = (clean, bool(automatic), self._generation)
            self._condition.notify()
            return True

    def _cancel_locked(self) -> None:
        self._pending = None
        self._generation += 1
        self._stop_serial += 1
        self._busy = False

    def stop(self) -> None:
        with self._condition:
            self._cancel_locked()
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._cancel_locked()
            self._condition.notify()

    def _run(self) -> None:
        backend: Any = None
        try:
            backend = _make_backend()
            voices = [dict(voice) for voice in backend.voices]
            if not voices:
                raise RuntimeError("Windows 没有可用的系统语音")
            with self._condition:
                self._voices = voices
                self._available = True
            applied: tuple[str, int, int] | None = None
            stopped = -1
            while True:
                with self._condition:
                    if self._closed:
                        break
                    settings = self._settings
                    stop_serial = self._stop_serial
                    pending = self._pending
                    self._pending = None
                    if pending is not None:
                        self._busy = True  # reserve the slot while COM starts it
                backend.pump()
                if stop_serial != stopped:
                    backend.stop()
                    stopped = stop_serial
                options = (_voice_id(voices, settings.voice_id), settings.rate, settings.volume)
                if options != applied:
                    backend.configure(*options)
                    applied = options
                if pending:
                    text, automatic, generation = pending
                    with self._condition:
                        valid = (not self._closed and self._settings.enabled and
                                 generation == self._generation and
                                 (not automatic or self._settings.automatic))
                    if valid:
                        backend.speak(text)
                busy = backend.is_busy()
                with self._condition:
                    self._busy = busy
                    if not self._closed and self._pending is None:
                        self._condition.wait(timeout=0.025)
        except Exception as exc:
            with self._condition:
                self._available = False
                self._error = f"系统朗读暂不可用：{str(exc)[:250]}"
                self._pending = None
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass
            with self._condition:
                self._available = False
                self._busy = False
