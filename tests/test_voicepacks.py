"""Local voice pack import boundaries. These tests never play any audio."""
from __future__ import annotations

import io
import json
from pathlib import Path
import re
import stat
import uuid
import wave
import zipfile

import pytest

from companion import voicepacks


def pcm_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\xe8\x03\x18\xfc" * 160)
    return buffer.getvalue()


def make_zip(path: Path, entries) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return path


def manifest(text="你回来啦", *, file="hello.wav", name="自己的小鱼") -> bytes:
    return json.dumps({"name": name, "clips": [{"id": "hello", "category": "greet", "text": text, "file": file}]}, ensure_ascii=False).encode("utf-8")


def assert_empty_library(data_dir: Path, library) -> None:
    assert library.list_packs() == []
    folder = data_dir / "voicepacks"
    if folder.exists():
        assert list(folder.iterdir()) == []


def test_manifest_directory_is_copied_and_survives_reopen(tmp_path):
    source = tmp_path / "source"
    (source / "audio").mkdir(parents=True)
    payload = pcm_wav()
    original = source / "audio" / "hello.wav"
    original.write_bytes(payload)
    (source / "manifest.json").write_bytes(manifest(file="audio/hello.wav"))
    data_dir = tmp_path / "user-data"
    library = voicepacks.VoicePackLibrary(data_dir)
    pack = library.import_pack(source)

    assert pack["name"] == "自己的小鱼"
    assert pack["id"].startswith("user:")
    uuid.UUID(pack["id"].split(":", 1)[1])
    assert len(pack["clips"]) == 1
    clip = pack["clips"][0]
    assert (clip["id"], clip["category"], clip["text"]) == ("hello", "greet", "你回来啦")
    assert clip["enabled_default"] is True
    assert clip["caption_known"] is True
    assert isinstance(clip["path"], Path)
    assert clip["path"].resolve().is_relative_to((data_dir / "voicepacks").resolve())
    assert clip["path"].read_bytes() == payload
    assert clip["path"].resolve() != original.resolve()
    assert original.read_bytes() == payload
    assert not Path(clip["file"]).is_absolute()

    reopened = voicepacks.VoicePackLibrary(data_dir).list_packs()
    assert len(reopened) == 1
    assert reopened[0]["id"] == pack["id"]
    assert reopened[0]["clips"][0]["text"] == "你回来啦"
    assert reopened[0]["clips"][0]["path"].read_bytes() == payload


def test_zip_accepts_one_outer_directory_and_relative_audio_subfolder(tmp_path):
    source = make_zip(tmp_path / "pack.zip", [
        ("release/manifest.json", manifest(file="audio/hello.wav", name="下载包")),
        ("release/audio/hello.wav", pcm_wav()),
        ("release/README.md", b"public voice pack"),
    ])
    source_before = source.read_bytes()
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    pack = library.import_pack(source)
    assert pack["name"] == "下载包"
    assert pack["clips"][0]["path"].is_file()
    assert source.read_bytes() == source_before


def test_unmanifested_audio_uses_filename_categories_without_invented_dialogue(tmp_path):
    source = tmp_path / "散装语音"
    source.mkdir()
    names = {"01_喂饭_开饭啦.wav": "feed", "02_摸头_你好.wav": "pat", "03_晚安.wav": "sleep", "04_greet_你回来啦.wav": "greet"}
    for name in names:
        (source / name).write_bytes(pcm_wav())
    pack = voicepacks.VoicePackLibrary(tmp_path / "data").import_pack(source)
    assert len(pack["clips"]) == 4
    by_category = {clip["category"]: clip for clip in pack["clips"]}
    assert set(by_category) == set(names.values())
    assert "开饭啦" in by_category["feed"]["text"]
    assert "你好" in by_category["pat"]["text"]
    assert "晚安" in by_category["sleep"]["text"]
    for clip in pack["clips"]:
        assert not re.match(r"^\d+[ _.-]", clip["text"])
        assert clip["enabled_default"] is True
        assert clip["caption_known"] is False


def test_manifest_free_zip_imports_audio(tmp_path):
    source = make_zip(tmp_path / "simple.zip", [("01_idle_发呆.wav", pcm_wav())])
    pack = voicepacks.VoicePackLibrary(tmp_path / "data").import_pack(source)
    assert len(pack["clips"]) == 1
    assert pack["clips"][0]["category"] == "idle"


def test_unknown_filename_remains_an_unverified_general_label(tmp_path):
    source = make_zip(tmp_path / "simple.zip", [("01_小鱼叫声.wav", pcm_wav())])
    pack = voicepacks.VoicePackLibrary(tmp_path / "data").import_pack(source)
    clip = pack["clips"][0]
    assert clip["category"] == "general"
    assert "小鱼叫声" in clip["text"]
    assert clip["caption_known"] is False


@pytest.mark.parametrize("dangerous", [
    "../escape.wav", "/absolute.wav", "C:/escape.wav", "C:\\escape.wav",
    "folder/../../escape.wav", "folder\\..\\escape.wav", "\\\\server\\share\\escape.wav",
])
def test_zip_rejects_traversal_and_absolute_paths(tmp_path, dangerous):
    data_dir = tmp_path / "data"
    library = voicepacks.VoicePackLibrary(data_dir)
    source = make_zip(tmp_path / "bad.zip", [(dangerous, pcm_wav())])
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert not (tmp_path / "escape.wav").exists()
    assert_empty_library(data_dir, library)


def test_zip_symlink_is_rejected_without_following_target(tmp_path):
    entry = zipfile.ZipInfo("hello.wav")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    source = make_zip(tmp_path / "symlink.zip", [(entry, b"../secret.wav")])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


@pytest.mark.parametrize("other", ["hello.wav", "HELLO.WAV"])
def test_duplicate_zip_paths_are_rejected_case_insensitively(tmp_path, other):
    source = tmp_path / "duplicate.zip"
    # zipfile warns about an exact duplicate but still creates the hostile input.
    if other == "hello.wav":
        with pytest.warns(UserWarning, match="Duplicate name"):
            make_zip(source, [("hello.wav", pcm_wav()), (other, pcm_wav())])
    else:
        make_zip(source, [("hello.wav", pcm_wav()), (other, pcm_wav())])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_encrypted_flag_is_rejected_before_extraction(tmp_path):
    source = make_zip(tmp_path / "encrypted.zip", [("hello.wav", pcm_wav())])
    payload = bytearray(source.read_bytes())
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    payload[local + 6] |= 1
    payload[central + 8] |= 1
    source.write_bytes(payload)
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


@pytest.mark.parametrize("filename,payload", [
    ("fake.wav", b"MZ" + b"\x00" * 128),
    ("fake.mp3", b"MZ" + b"\x00" * 128),
    ("fake.ogg", b"MZ" + b"\x00" * 128),
    ("broken.wav", b"RIFF\x00\x00\x00\x00WAVEgarbage"),
])
def test_invalid_audio_headers_do_not_enter_library(tmp_path, filename, payload):
    source = make_zip(tmp_path / "invalid.zip", [(filename, payload)])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_executable_sidecar_rejects_the_entire_zip(tmp_path):
    source = make_zip(tmp_path / "executable.zip", [("hello.wav", pcm_wav()), ("setup.exe", b"MZmalware")])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


@pytest.mark.parametrize("file", ["../outside.wav", "/outside.wav", "C:/outside.wav"])
def test_manifest_cannot_reference_files_outside_pack(tmp_path, file):
    source = tmp_path / "pack"
    source.mkdir()
    (tmp_path / "outside.wav").write_bytes(pcm_wav())
    (source / "manifest.json").write_bytes(manifest(file=file))
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


@pytest.mark.parametrize("content", [b"not-json", b"[]", b'{"clips":[]}', b'{"clips":["not a clip"]}'])
def test_invalid_or_empty_manifest_is_not_silently_ignored(tmp_path, content):
    source = make_zip(tmp_path / "manifest.zip", [("manifest.json", content), ("hello.wav", pcm_wav())])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_duplicate_manifest_clip_ids_are_rejected(tmp_path):
    clip = {"id": "same", "category": "click", "text": "hello", "file": "hello.wav"}
    metadata = json.dumps({"name": "duplicate", "clips": [clip, clip]}).encode()
    source = make_zip(tmp_path / "manifest.zip", [("manifest.json", metadata), ("hello.wav", pcm_wav())])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_corrupt_archive_leaves_no_half_import(tmp_path):
    source = tmp_path / "corrupt.zip"
    source.write_bytes(b"PK\x03\x04incomplete archive")
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_zip_crc_corruption_is_rejected_without_a_half_pack(tmp_path):
    source = tmp_path / "crc.zip"
    payload = pcm_wav()
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("hello.wav", payload)
    content = bytearray(source.read_bytes())
    offset = content.index(payload)
    content[offset + len(payload) - 1] ^= 1
    source.write_bytes(content)
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_single_file_limit_is_enforced_without_large_fixture(tmp_path, monkeypatch):
    payload = pcm_wav()
    monkeypatch.setattr(voicepacks, "MAX_FILE_BYTES", len(payload) - 1)
    source = make_zip(tmp_path / "large.zip", [("hello.wav", payload)])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_total_size_limit_is_enforced_without_large_fixture(tmp_path, monkeypatch):
    payload = pcm_wav()
    monkeypatch.setattr(voicepacks, "MAX_TOTAL_BYTES", len(payload) * 2 - 1)
    source = make_zip(tmp_path / "large.zip", [("one.wav", payload), ("two.wav", payload)])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_file_count_limit_is_enforced(tmp_path):
    source = make_zip(tmp_path / "many.zip", [(f"clip-{index}.wav", pcm_wav()) for index in range(301)])
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(ValueError):
        library.import_pack(source)
    assert_empty_library(tmp_path / "data", library)


def test_extreme_nesting_and_double_manifest_wrapper_are_rejected(tmp_path):
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    deeply_nested = "/".join(["nested"] * 25) + "/hello.wav"
    source = make_zip(tmp_path / "deep.zip", [(deeply_nested, pcm_wav())])
    with pytest.raises(ValueError):
        library.import_pack(source)
    wrapped = make_zip(tmp_path / "double.zip", [("outer/inner/manifest.json", manifest()), ("outer/inner/hello.wav", pcm_wav())])
    with pytest.raises(ValueError):
        library.import_pack(wrapped)
    assert_empty_library(tmp_path / "data", library)


def test_failed_second_import_does_not_change_existing_pack(tmp_path):
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    good = make_zip(tmp_path / "good.zip", [("hello.wav", pcm_wav())])
    pack = library.import_pack(good)
    saved_path = pack["clips"][0]["path"]
    saved = saved_path.read_bytes()
    bad = make_zip(tmp_path / "bad.zip", [("bad.mp3", b"MZnot audio")])
    with pytest.raises(ValueError):
        library.import_pack(bad)
    listed = library.list_packs()
    assert [item["id"] for item in listed] == [pack["id"]]
    assert saved_path.read_bytes() == saved
    assert len(list((tmp_path / "data" / "voicepacks").iterdir())) == 1


def test_reload_does_not_return_missing_or_escaped_audio(tmp_path):
    data_dir = tmp_path / "data"
    library = voicepacks.VoicePackLibrary(data_dir)
    source = make_zip(tmp_path / "good.zip", [("hello.wav", pcm_wav())])
    pack = library.import_pack(source)
    pack["clips"][0]["path"].unlink()
    reopened = voicepacks.VoicePackLibrary(data_dir).list_packs()
    assert not any(item["id"] == pack["id"] for item in reopened)


def test_remove_only_accepts_owned_user_ids(tmp_path):
    data_dir = tmp_path / "data"
    library = voicepacks.VoicePackLibrary(data_dir)
    source = make_zip(tmp_path / "good.zip", [("hello.wav", pcm_wav())])
    pack = library.import_pack(source)
    outside = tmp_path / "keep-me.txt"
    outside.write_text("keep", encoding="utf-8")
    for malicious_id in ["character-pack", "user:../..", "user:/", "user:C:\\", "user:not-a-uuid"]:
        with pytest.raises(ValueError):
            library.remove_pack(malicious_id)
    assert outside.read_text(encoding="utf-8") == "keep"
    assert len(library.list_packs()) == 1
    library.remove_pack(pack["id"])
    assert library.list_packs() == []
    assert source.is_file()
    assert outside.is_file()


def test_source_must_exist(tmp_path):
    library = voicepacks.VoicePackLibrary(tmp_path / "data")
    with pytest.raises(FileNotFoundError):
        library.import_pack(tmp_path / "missing.zip")
