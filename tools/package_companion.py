"""Build the personal Windows onedir edition with an explicit data allowlist.

Run with the build virtual environment, for example:
    python tools/package_companion.py --outputs <new-output-directory>
No packages or other dependencies are downloaded by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_NAME = "大肥鱼-离线养成版"
PINNED = {"PySide6": "6.8.3", "Pillow": "11.3.0", "psutil": "7.2.2", "PyInstaller": "6.22.3"}
RUNTIME_DIRS = {
    "assets/chimes": {".wav"},
    "assets/community": {".json", ".md", ".webp"},
    "assets/dialogue": {".json"},
    "assets/voicepack": {".json", ".md", ".mp3", ".wav", ".ogg"},
}
RUNTIME_FILES = (
    "assets/manifests/actions.json", "assets/app_categories.json", "assets/privacy_rules.json",
    "sprites/icon.png", "icon.ico",
)
DOCUMENTS = ("LICENSE", "ASSET_LICENSE.md", "CREDITS.md", "companion_voicepack_notice.md",
             "README_DIARY.md", "THIRD_PARTY_NOTICES_DIARY.md")
CODE_DIRS = ("app", "animation", "awareness", "behavior", "companion", "dialogue", "pet", "settings", "tests")
SOURCE_ROOT_FILES = ("main.py", "requirements.txt", "requirements-build.txt", *DOCUMENTS)
SOURCE_TOOLS = ("tools/package_companion.py", "tools/import_community_animation.py")
DEPENDENCIES = ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "Pillow", "psutil",
                "PyInstaller", "pyinstaller-hooks-contrib", "altgraph", "packaging", "pefile", "pywin32-ctypes")
PRIVATE_NAMES = {"config.json", "pet_state.json", "session_recovery.json", "companion.sqlite3"}
FORBIDDEN_PARTS = {".git", "__pycache__", ".venv", "logs", "updates", "backups", "source", "references",
                   "masters", "candidates", "research", "testdata", "test_data", "fixtures", "demo-data", "demo_data"}
LICENSE_MARKERS = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "COPYRIGHT")


def within(path: Path, base: Path) -> Path:
    result = path.resolve()
    if result == base.resolve() or not result.is_relative_to(base.resolve()):
        raise ValueError(f"Expected a child path inside {base.name}: {path.name}")
    return result


def require_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing, empty or linked file: {path}")


def source_file(relative: str | Path) -> Path:
    path = ROOT / relative
    within(path, ROOT)
    require_file(path)
    return path


def runtime_files() -> list[Path]:
    result = {source_file(relative) for relative in RUNTIME_FILES}
    for relative, suffixes in RUNTIME_DIRS.items():
        folder = within(ROOT / relative, ROOT)
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError(f"Missing or linked runtime directory: {relative}")
        for path in sorted(folder.rglob("*")):
            if path.is_dir():
                continue
            if path.suffix.lower() not in suffixes:
                raise ValueError(f"Unexpected file in runtime allowlist: {path.relative_to(ROOT)}")
            source_file(path.relative_to(ROOT))
            result.add(path)
    return sorted(result)


def check_text(path: Path) -> None:
    if path.suffix.lower() not in {".py", ".md", ".txt", ".json"} and path.name not in {"LICENSE", "CREDITS"}:
        return
    text = path.read_text(encoding="utf-8-sig")
    normalized = text.replace("\\\\", "\\").replace("\\", "/").casefold()
    for development_root in (str(ROOT), str(ROOT.parent), str(Path.home())):
        if development_root.replace("\\", "/").casefold() in normalized:
            raise ValueError(f"Development-machine path in distributable text: {path.name}")
    if re.search(r"(?i)\b[a-z]:[/\\]users[/\\]", text):
        raise ValueError(f"User-directory path in distributable text: {path.name}")


def check_members(paths: list[Path], base: Path) -> None:
    for path in paths:
        require_file(path)
        relative = path.relative_to(base)
        lowered = {part.casefold() for part in relative.parts}
        if lowered & FORBIDDEN_PARTS or path.name.casefold() in PRIVATE_NAMES:
            raise ValueError(f"Private or excluded file selected: {relative}")
        if path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".tmp", ".bak"}:
            raise ValueError(f"Runtime data or cache selected: {relative}")
        check_text(path)


def read_json(path: Path) -> object:
    require_file(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def frame_paths(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from frame_paths(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from frame_paths(item)


def assert_relative_file(base: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"Unsafe asset reference: {relative!r}")
    path = within(base / relative, base)
    require_file(path)
    return path


def verify_assets(base: Path) -> dict:
    actions = read_json(base / "assets/manifests/actions.json")
    community = read_json(base / "assets/community/manifest.json")
    voicepack = read_json(base / "assets/voicepack/manifest.json")
    frame_count = 0
    for asset in actions.get("assets", {}).values():
        for relative in frame_paths(asset.get("frames", [])):
            assert_relative_file(base, relative)
            frame_count += 1
    for clip in community.get("clips", []):
        references = clip.get("frames", [])
        if len(references) != clip.get("frame_count") or not references:
            raise ValueError(f"Invalid community frame count: {clip.get('name')}")
        for relative in references:
            assert_relative_file(base, relative)
        if Path(clip.get("source_file", "")).name != clip.get("source_file"):
            raise ValueError("Community source metadata contains a development path")
    clips = voicepack.get("clips", [])
    if not clips:
        raise ValueError("Empty voice pack")
    for clip in clips:
        for key in ("file", "playback_file"):
            filename = clip.get(key)
            if filename:
                if Path(filename).name != filename:
                    raise ValueError(f"Unsafe voice filename: {filename}")
                assert_relative_file(base, "assets/voicepack/" + filename)
    styles_path = base / "assets/voicepack/styles/manifest.json"
    if styles_path.is_file():
        raise ValueError("Rejected synthetic voice candidates must not be shipped")
    return {"action_frame_references": frame_count, "community_clips": len(community["clips"]),
            "community_frames": sum(clip["frame_count"] for clip in community["clips"]),
            "voice_clips": len(clips), "default_voice_clips": sum(bool(clip.get("enabled_default")) for clip in clips)}


def copy_relative(path: Path, destination: Path, base: Path = ROOT) -> None:
    target = destination / path.relative_to(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)


def copy_dependency_licenses(bundle: Path) -> None:
    target = bundle / "licenses"
    target.mkdir(parents=True, exist_ok=True)
    inventory = []
    for name in DEPENDENCIES:
        distribution = metadata.distribution(name)
        copied = []
        for relative in distribution.files or []:
            raw = Path(str(relative))
            if not any(part.lower().endswith(".dist-info") for part in raw.parts):
                continue
            if not any(marker in raw.name.upper() for marker in LICENSE_MARKERS):
                continue
            original = Path(distribution.locate_file(relative))
            if not original.is_file():
                continue
            parts = raw.parts
            index = next(i for i, part in enumerate(parts) if part.lower().endswith(".dist-info"))
            filename = Path(*parts[index + 1:])
            out = target / name / filename
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, out)
            copied.append(out.relative_to(bundle).as_posix())
        if not copied:
            raise ValueError(f"No installed license text found for {name}")
        inventory.append({"name": name, "version": distribution.version, "license_files": copied})
    python_license = next((Path(sys.base_prefix) / name for name in ("LICENSE.txt", "LICENSE")
                           if (Path(sys.base_prefix) / name).is_file()), None)
    if python_license is None:
        raise ValueError("Python's complete license text is missing")
    (target / "Python").mkdir(exist_ok=True)
    shutil.copy2(python_license, target / "Python" / "LICENSE.txt")
    inventory.append({"name": "Python", "version": sys.version.split()[0], "license_files": ["licenses/Python/LICENSE.txt"]})
    notices = source_file("THIRD_PARTY_NOTICES_DIARY.md").read_text(encoding="utf-8-sig")
    (target / "Qt").mkdir(exist_ok=True)
    for name in ("LGPL-3.0-only", "GPL-3.0-only", "LGPL-2.1-only"):
        match = re.search(r"<!-- BEGIN " + re.escape(name) + r" -->\s*\n(.*?)\n<!-- END " + re.escape(name) + r" -->", notices, re.S)
        if not match or len(match.group(1)) < 6000:
            raise ValueError(f"Complete Qt/media license appendix missing: {name}")
        (target / "Qt" / (name + ".txt")).write_text(match.group(1).rstrip() + "\n", encoding="utf-8")
    (target / "DEPENDENCIES.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def selected_source_files(resources: list[Path]) -> list[Path]:
    selected = {source_file(relative) for relative in (*SOURCE_ROOT_FILES, *SOURCE_TOOLS)}
    selected.update(resources)
    for relative in CODE_DIRS:
        directory = within(ROOT / relative, ROOT)
        for path in directory.rglob("*.py"):
            if "__pycache__" not in path.parts:
                source_file(path.relative_to(ROOT))
                selected.add(path)
    result = sorted(selected)
    check_members(result, ROOT)
    return result


def zip_directory(folder: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(folder.name) / path.relative_to(folder)).as_posix())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, default=ROOT.parents[1] / "outputs")
    arguments = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Build this Windows application on Windows.")
    for name, version in PINNED.items():
        if metadata.version(name) != version:
            raise SystemExit(f"Use the pinned build environment: {name}=={version}")
    build = within(ROOT / "build-personal", ROOT)
    dist = within(ROOT / "dist-personal", ROOT)
    within(dist / "大肥鱼", ROOT)
    within(build / "pyinstaller", ROOT)
    outputs = arguments.outputs.expanduser().resolve()
    if outputs == ROOT or outputs.is_relative_to(build) or outputs.is_relative_to(dist):
        raise ValueError("Choose a separate output directory")
    outputs.mkdir(parents=True, exist_ok=True)
    portable = outputs / OUTPUT_NAME
    runtime_zip = outputs / (OUTPUT_NAME + ".zip")
    source_zip = outputs / (OUTPUT_NAME + "-源码.zip")
    for path in (portable, runtime_zip, source_zip):
        if path.exists():
            raise FileExistsError(f"Output already exists; choose another output directory: {path.name}")
    resources = runtime_files()
    check_members(resources, ROOT)
    sources = selected_source_files(resources)
    verify_assets(ROOT)
    build.mkdir(parents=True, exist_ok=True)
    dist.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--noconsole", "--onedir",
               "--name", "大肥鱼", "--icon", str(ROOT / "icon.ico"),
               "--hidden-import", "PySide6.QtMultimedia", "--exclude-module", "companion.speech",
               "--exclude-module", "win32com", "--exclude-module", "pythoncom", "--exclude-module", "pywintypes",
               "--workpath", str(build / "pyinstaller"), "--distpath", str(dist), "--specpath", str(build),
               str(ROOT / "main.py")]
    print("Building the standalone desktop pet…", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    bundle = within(dist / "大肥鱼", ROOT)
    require_file(bundle / "大肥鱼.exe")
    internal = within(bundle / "_internal", ROOT)
    if not internal.is_dir():
        raise ValueError("Expected a PyInstaller onedir _internal runtime")
    for path in resources:
        copy_relative(path, internal)
    for relative in DOCUMENTS:
        shutil.copy2(source_file(relative), bundle / relative)
    shutil.copy2(source_file("README_DIARY.md"), bundle / "使用说明.md")
    copy_dependency_licenses(bundle)
    counts = verify_assets(internal)
    check_members([path for path in bundle.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".md", ".txt"}], bundle)
    for path in bundle.rglob("*"):
        if path.is_file() and (path.name.casefold() in PRIVATE_NAMES or path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".log"}):
            raise ValueError(f"Private data in bundle: {path.relative_to(bundle)}")
    for forbidden in (internal / "pythoncom", internal / "win32com", internal / "pywintypes"):
        if forbidden.exists():
            raise ValueError("Optional system TTS was unexpectedly bundled")
    (bundle / "PACKAGE_CONTENTS.json").write_text(json.dumps({
        "name": OUTPUT_NAME, "assets": counts, "user_data_included": False,
        "runtime_api_or_model_required": False,
        "files": [{"path": path.relative_to(bundle).as_posix(), "bytes": path.stat().st_size}
                  for path in sorted(bundle.rglob("*")) if path.is_file()],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Copying the portable folder and writing archives…", flush=True)
    shutil.copytree(bundle, portable)
    zip_directory(portable, runtime_zip)
    with zipfile.ZipFile(source_zip, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        prefix = Path(OUTPUT_NAME + "-源码")
        for path in sources:
            archive.write(path, (prefix / path.relative_to(ROOT)).as_posix())
        for path in sorted((bundle / "licenses").rglob("*")):
            if path.is_file():
                archive.write(path, (prefix / path.relative_to(bundle)).as_posix())
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (runtime_zip, source_zip)}
    (outputs / (OUTPUT_NAME + "-SHA256.txt")).write_text("\n".join(f"{digest}  {name}" for name, digest in hashes.items()) + "\n", encoding="utf-8")
    print(json.dumps({"portable": str(portable), "runtime_zip": str(runtime_zip), "source_zip": str(source_zip),
                      "assets": counts, "sha256": hashes}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
