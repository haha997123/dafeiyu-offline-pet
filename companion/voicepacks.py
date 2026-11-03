"""Import self-contained audio packs into the user's local voice library."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid
import wave
import zipfile

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_FILES = 300
MAX_DEPTH = 8
AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg"}
SIDECAR_SUFFIXES = {".md", ".txt", ".json", ".png", ".jpg", ".jpeg"}
CATEGORY_WORDS = {
    "feed": ("feed", "eat", "喂饭", "喂食", "吃饭", "开饭"),
    "pat": ("pat", "摸头", "摸摸"),
    "sleep": ("sleep", "晚安", "睡觉"),
    "wake": ("wake", "起床", "睡醒"),
    "drag": ("drag", "拖动", "拎起"),
    "greet": ("greet", "hello", "问候", "欢迎", "你好", "回来"),
    "click": ("click", "点击", "戳"),
    "idle": ("idle", "发呆", "闲聊", "待机"),
    "cheer": ("cheer", "play", "加油", "陪玩", "开心"),
    "thanks": ("thanks", "谢谢"),
    "think": ("think", "思考"),
    "general": ("general", "通用"),
}


def _relative(raw: str) -> Path:
    if (not isinstance(raw, str) or not raw or "\\" in raw or ":" in raw or "\x00" in raw
            or raw.startswith("/") or any(part in {"", ".", ".."} for part in raw.split("/"))):
        raise ValueError("语音包中有无效或越界的文件路径")
    parts = PurePosixPath(raw).parts
    if len(parts) > MAX_DEPTH or any(part.endswith((" ", ".")) for part in parts):
        raise ValueError("语音包目录层级过深或路径无效")
    return Path(*parts)


def _category(raw: str) -> str:
    raw = str(raw).casefold()
    for category, words in CATEGORY_WORDS.items():
        if raw == category or any(word in raw for word in words):
            return category
    return "general"


def _check_audio(path: Path) -> None:
    data = path.read_bytes()
    if not data or len(data) > MAX_FILE_BYTES or data.startswith(b"MZ"):
        raise ValueError(f"音频为空、过大或格式不正确：{path.name}")
    suffix = path.suffix.casefold()
    try:
        if suffix == ".wav":
            with wave.open(io.BytesIO(data), "rb") as sound:
                if (sound.getnframes() <= 0 or sound.getnchannels() not in {1, 2}
                        or sound.getframerate() <= 0 or not sound.readframes(1)):
                    raise ValueError("WAV 文件没有有效音频")
        elif suffix == ".mp3":
            if not (data.startswith(b"ID3") or len(data) > 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
                raise ValueError("不是有效的 MP3 文件")
        elif suffix == ".ogg":
            if not data.startswith(b"OggS"):
                raise ValueError("不是有效的 OGG 文件")
        else:
            raise ValueError("不支持的音频格式")
    except (wave.Error, EOFError) as error:
        raise ValueError(f"音频文件损坏：{path.name}") from error


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


class VoicePackLibrary:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir).resolve() / "voicepacks"
        self.root.mkdir(parents=True, exist_ok=True)
        if _is_link(self.root):
            raise ValueError("语音库目录不能是链接")

    def _owned(self, path: Path) -> Path:
        path = path.resolve()
        if path == self.root or not path.is_relative_to(self.root):
            raise ValueError("语音包路径不在本机语音库内")
        return path

    def _clean_temporary(self, path: Path):
        self._owned(path)
        if path.exists():
            shutil.rmtree(path)

    def _copy_source(self, source: Path, destination: Path):
        seen = set()
        total = count = 0

        def reserve(name, size):
            nonlocal count, total
            relative = _relative(name)
            key = relative.as_posix().casefold()
            if key in seen:
                raise ValueError("语音包包含重复文件路径")
            seen.add(key)
            count += 1
            total += size
            if count > MAX_FILES or size <= 0 or size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("语音包超过文件数量或大小限制")
            if relative.suffix.casefold() not in AUDIO_SUFFIXES | SIDECAR_SUFFIXES:
                raise ValueError(f"语音包中包含不支持的文件：{relative.name}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            return target

        if source.is_dir():
            if _is_link(source):
                raise ValueError("导入目录不能是链接")
            if source.resolve() == self.root or self.root.is_relative_to(source.resolve()):
                raise ValueError("不能把语音库本身或其上级作为导入目录")
            for current, directories, filenames in os.walk(source, followlinks=False):
                folder = Path(current)
                for name in directories:
                    if _is_link(folder / name):
                        raise ValueError("语音包不能包含目录链接")
                for name in sorted(filenames):
                    path = folder / name
                    if _is_link(path) or not path.resolve().is_relative_to(source.resolve()):
                        raise ValueError("语音包不能包含文件链接")
                    target = reserve(path.relative_to(source).as_posix(), path.stat().st_size)
                    shutil.copyfile(path, target)
        else:
            if source.suffix.casefold() != ".zip":
                raise ValueError("请选择 ZIP 语音包或包含音频的文件夹")
            try:
                with zipfile.ZipFile(source) as archive:
                    for info in archive.infolist():
                        name = info.filename.rstrip("/")
                        _relative(name)
                        mode = info.external_attr >> 16
                        if stat.S_ISLNK(mode) or info.flag_bits & 1:
                            raise ValueError("语音包不能包含链接或加密文件")
                        if info.is_dir():
                            continue
                        target = reserve(name, info.file_size)
                        with archive.open(info) as stream:
                            data = stream.read(MAX_FILE_BYTES + 1)
                        if len(data) != info.file_size or len(data) > MAX_FILE_BYTES:
                            raise ValueError("语音包文件大小不符合清单")
                        target.write_bytes(data)
            except (zipfile.BadZipFile, RuntimeError, EOFError, NotImplementedError) as error:
                raise ValueError("ZIP 语音包已损坏或格式不支持") from error
        if not count:
            raise ValueError("语音包中没有文件")

    def _input_root(self, staging: Path) -> Path:
        manifests = list(staging.rglob("manifest.json"))
        if len(manifests) > 1:
            raise ValueError("一个语音包只能包含一份 manifest.json")
        if manifests:
            relative = manifests[0].relative_to(staging)
            if len(relative.parts) > 2:
                raise ValueError("清单应放在语音包根目录，最多允许一层外包目录")
            return manifests[0].parent
        entries = list(staging.iterdir())
        return entries[0] if len(entries) == 1 and entries[0].is_dir() else staging

    def _normalize(self, source: Path, name: str) -> dict:
        audio = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.casefold() in AUDIO_SUFFIXES)
        if not audio:
            raise ValueError("语音包没有 WAV、MP3 或 OGG 音频")
        for path in audio:
            _check_audio(path)
        manifest_path = source / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as error:
                raise ValueError("语音清单不是有效的 JSON") from error
            if not isinstance(manifest, dict) or not isinstance(manifest.get("clips"), list) or not manifest["clips"]:
                raise ValueError("语音清单缺少有效 clips 列表")
            name = manifest.get("name") or name
            items = manifest["clips"]
        else:
            items = []
            for index, path in enumerate(audio):
                label = re.sub(r"^\d+[\s_.-]*", "", path.stem).strip() or path.stem
                items.append({"id": f"clip{index + 1}", "category": _category(path.stem),
                              "text": label, "file": path.relative_to(source).as_posix(), "caption_known": False})
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("语音包名称无效或过长")
        clips, ids = [], set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("语音清单中包含无效条目")
            clip_id = item.get("id")
            if not isinstance(clip_id, str) or not re.fullmatch(r"[\w-]{1,80}", clip_id) or clip_id.casefold() in ids:
                raise ValueError("语音片段编号无效或重复")
            ids.add(clip_id.casefold())
            relative = _relative(item.get("file"))
            path = source / relative
            if not path.is_file() or not path.resolve().is_relative_to(source.resolve()) or path.suffix.casefold() not in AUDIO_SUFFIXES:
                raise ValueError("语音清单引用了包外或不存在的音频")
            text = item.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                raise ValueError("语音片段的文字无效")
            clips.append({"id": clip_id, "category": _category(item.get("category", "general")),
                          "text": text, "file": relative.as_posix(), "enabled_default": True,
                          "caption_known": bool(item.get("caption_known", manifest_path.is_file()))})
        return {"name": name.strip(), "clips": clips}

    def import_pack(self, source: Path) -> dict:
        source = Path(source).expanduser()
        if not source.exists():
            raise FileNotFoundError("选择的语音包已经不存在")
        staging = Path(tempfile.mkdtemp(prefix=".import-", dir=self.root))
        try:
            self._copy_source(source, staging)
            content = self._input_root(staging)
            normalized = self._normalize(content, source.stem)
            pack_uuid = str(uuid.uuid4())
            package = Path(tempfile.mkdtemp(prefix=".ready-", dir=self.root))
            try:
                copied = set()
                for clip in normalized["clips"]:
                    if clip["file"].casefold() in copied:
                        continue
                    copied.add(clip["file"].casefold())
                    target = package / clip["file"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(content / clip["file"], target)
                normalized.update({"schema_version": 1, "id": "user:" + pack_uuid})
                (package / "manifest.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
                target = self._owned(self.root / pack_uuid)
                os.replace(package, target)
                return self._read_pack(target)
            finally:
                if package.exists():
                    self._clean_temporary(package)
        finally:
            self._clean_temporary(staging)

    def _read_pack(self, folder: Path) -> dict:
        self._owned(folder)
        if _is_link(folder):
            raise ValueError("语音包不能是链接")
        pack_uuid = str(uuid.UUID(folder.name))
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict) or manifest.get("id") != "user:" + pack_uuid
                or not isinstance(manifest.get("clips"), list) or not 0 < len(manifest["clips"]) <= MAX_FILES
                or not isinstance(manifest.get("name"), str) or not manifest["name"].strip()):
            raise ValueError("语音包清单无效")
        clips, seen = [], set()
        for clip in manifest["clips"]:
            if (not isinstance(clip, dict) or not isinstance(clip.get("id"), str)
                    or clip["id"] in seen or not isinstance(clip.get("text"), str)
                    or clip.get("category") not in CATEGORY_WORDS):
                raise ValueError("已导入的语音清单无效")
            seen.add(clip["id"])
            path = folder / _relative(clip["file"])
            if (not path.is_file() or _is_link(path) or not path.resolve().is_relative_to(folder.resolve())
                    or path.suffix.casefold() not in AUDIO_SUFFIXES or path.stat().st_size > MAX_FILE_BYTES):
                raise ValueError("语音包音频缺失或路径无效")
            clips.append({**clip, "path": path})
        return {"id": manifest["id"], "name": manifest["name"], "clips": clips}

    def list_packs(self) -> list[dict]:
        packs = []
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            try:
                packs.append(self._read_pack(folder))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return packs

    def remove_pack(self, pack_id: str):
        if not isinstance(pack_id, str) or not pack_id.startswith("user:"):
            raise ValueError("只能移除自己导入的语音包")
        try:
            pack_uuid = str(uuid.UUID(pack_id[5:]))
        except (ValueError, AttributeError) as error:
            raise ValueError("语音包编号无效") from error
        folder = self._owned(self.root / pack_uuid)
        if folder.is_dir():
            if _is_link(folder):
                raise ValueError("不能移除链接目录")
            shutil.rmtree(folder)
