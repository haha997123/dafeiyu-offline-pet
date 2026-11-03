"""Exercise speech control with fakes only: these tests never play sound."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from companion import speech


class FakeBackend:
    def __init__(self):
        self.voices = [
            {"id": "english", "name": "English", "language": "409"},
            {"id": "chinese", "name": "Chinese", "language": "804"},
        ]
        self.spoken = []
        self.configurations = []
        self.busy = False
        self.stop_count = 0
        self.closed = False
        self.thread_ids = set()

    def _record_thread(self):
        self.thread_ids.add(threading.get_ident())

    def configure(self, *values):
        self._record_thread()
        self.configurations.append(values)

    def speak(self, text):
        self._record_thread()
        self.spoken.append(text)
        self.busy = True

    def stop(self):
        self._record_thread()
        self.stop_count += 1
        self.busy = False

    def is_busy(self):
        self._record_thread()
        return self.busy

    def pump(self):
        self._record_thread()

    def close(self):
        self._record_thread()
        self.closed = True


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Speech worker did not reach the expected state")
        time.sleep(0.005)


@pytest.fixture
def service(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(speech, "_make_backend", lambda: backend)
    service = speech.SpeechService()
    wait_for(lambda: service.available)
    yield service, backend
    service.close()
    service._thread.join(timeout=2)
    assert not service._thread.is_alive()


def test_default_is_silent_and_voice_metadata_is_detached(service):
    service, backend = service
    assert service.error == ""
    assert not service.speak("Do not say this")
    voices = service.voices
    voices[0]["name"] = "modified"
    assert service.voices[0]["name"] == "English"
    assert backend.spoken == []


def test_manual_speech_replaces_busy_speech_without_waiting(service):
    service, backend = service
    service.configure(True, rate=50, volume=-4)
    assert service.speak("first")
    wait_for(lambda: backend.spoken == ["first"])
    assert service.speak("replacement")
    wait_for(lambda: backend.spoken == ["first", "replacement"])
    assert backend.configurations[-1] == ("chinese", 10, 0)
    assert backend.thread_ids == {service._thread.ident}


def test_automatic_speech_is_opt_in_and_dropped_when_busy(service):
    service, backend = service
    service.configure(True)
    assert not service.speak("automatic disabled", automatic=True)
    service.configure(True, automatic=True)
    assert service.speak("automatic accepted", automatic=True)
    wait_for(lambda: backend.spoken == ["automatic accepted"])
    assert not service.speak("automatic dropped", automatic=True)
    assert service.speak("manual replaces it")
    wait_for(lambda: backend.spoken[-1] == "manual replaces it")


def test_text_is_bounded_and_control_characters_are_removed(service):
    service, backend = service
    service.configure(True)
    assert not service.speak(" \x00\n\t")
    assert service.speak("  你好\x00\n世界  " + "鱼" * 400)
    wait_for(lambda: bool(backend.spoken))
    assert backend.spoken[0].startswith("你好 世界 ")
    assert len(backend.spoken[0]) == 300
    assert "\x00" not in backend.spoken[0]


def test_stop_disable_and_close_do_not_leave_speech_running(service):
    service, backend = service
    service.configure(True)
    assert service.speak("a line")
    wait_for(lambda: backend.busy)
    previous = backend.stop_count
    service.stop()
    wait_for(lambda: backend.stop_count > previous)
    assert not backend.busy
    service.configure(False)
    assert not service.speak("disabled")
    service.close()
    wait_for(lambda: backend.closed)
    assert not service.available
    assert not service.speak("closed")


def test_missing_backend_fails_gracefully(monkeypatch):
    def missing():
        raise ImportError("pywin32 is not installed")
    monkeypatch.setattr(speech, "_make_backend", missing)
    service = speech.SpeechService()
    wait_for(lambda: bool(service.error))
    assert not service.available
    assert "pywin32" in service.error
    assert not service.speak("never spoken")
    service.close()
    service._thread.join(timeout=2)


def test_initialization_and_close_are_nonblocking(monkeypatch):
    gate = threading.Event()
    entered = threading.Event()
    backend = FakeBackend()
    def slow():
        entered.set()
        gate.wait(timeout=2)
        return backend
    monkeypatch.setattr(speech, "_make_backend", slow)
    started = time.monotonic()
    service = speech.SpeechService()
    assert time.monotonic() - started < 0.5
    assert entered.wait(timeout=1)
    try:
        started = time.monotonic()
        service.close()
        assert time.monotonic() - started < 0.5
    finally:
        gate.set()
        service._thread.join(timeout=2)
    assert backend.closed
    assert not service.available


def test_voice_fallback_prefers_simplified_chinese():
    voices = [
        {"id": "en", "language": "409"},
        {"id": "tw", "language": "404"},
        {"id": "cn", "language": "804;409"},
    ]
    assert speech._voice_id(voices, "missing") == "cn"
    assert speech._voice_id(voices, "tw") == "tw"
    assert speech._voice_id([{"id": "en", "language": "invalid"}], "") == "en"


def test_sapi_backend_uses_plain_text_async_purge_without_real_audio(monkeypatch):
    calls = []
    token = SimpleNamespace(Id="voice-id", GetAttribute=lambda _: "804", GetDescription=lambda: "Fake Chinese")
    voice = SimpleNamespace(
        GetVoices=lambda: SimpleNamespace(Count=1, Item=lambda index: token),
        Speak=lambda text, flags: calls.append((text, flags)),
        WaitUntilDone=lambda timeout: True,
    )
    lifecycle = []
    pythoncom = SimpleNamespace(
        COINIT_APARTMENTTHREADED=2,
        CoInitializeEx=lambda flags: lifecycle.append(("init", flags)),
        CoUninitialize=lambda: lifecycle.append(("uninit",)),
        PumpWaitingMessages=lambda: lifecycle.append(("pump",)),
    )
    client = SimpleNamespace(Dispatch=lambda name: voice)
    monkeypatch.setattr(speech, "import_module", lambda name: {"pythoncom": pythoncom, "win32com.client": client}[name])
    backend = speech._SapiBackend()
    backend.configure("voice-id", -2, 40)
    backend.speak("<tag>literal text</tag>")
    assert voice.Voice is token
    assert (voice.Rate, voice.Volume) == (-2, 40)
    assert calls == [("<tag>literal text</tag>", 19)]
    assert not backend.is_busy()
    backend.pump()
    backend.close()
    backend.close()
    assert calls[-1] == ("", 19)
    assert lifecycle.count(("uninit",)) == 1
