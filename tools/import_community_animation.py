"""Import a small, attributed noncommercial PC2005-cloud animation pack.

This script only decodes local media; it neither downloads nor executes upstream
code. Requires Pillow and an ffmpeg build containing the libvpx-vp9 decoder.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from PIL import Image


SOURCE_COMMIT = "3229ab287d82d7621af2ee51544a0e746c2e40fd"
SOURCE_REPOSITORY = "https://github.com/PC2005-cloud/dsh-pet"
SOURCES = {
    "idle": ("idle.webm", "待机呼吸休闲", 441437),
    "walk": ("walk.webm", "螃蟹走路", 596902),
    "happy": ("happy.webm", "点击回应-开心跃动", 538110),
    "eat": ("eat.webm", "吃白饭", 459590),
    "sleep": ("sleep_loop-complete.webm", "睡觉-循环", 237002),
    "drag": ("drag.webm", "被鼠标拖拽悬空反馈", 464764),
    "think": ("think-complete.webm", "工作状态-思考冒泡", 408849),
    "murmur": ("murmur-complete.webm", "碎碎念-对屏碎碎念", 364946),
    "pat": ("pat.webm", "点击回应-挠痒咯咯笑", 425393),
    "landing": ("landing.webm", "原地重力下蹲压缩", 215047),
    "tail": ("tail.webm", "用鲸鱼尾巴拍打地面", 352213),
    "turn": ("turn.webm", "东张西望", 427005),
    "sweep": ("sweep.webm", "碎碎念-擦桌碎碎念", 350436),
}
FRAME_COUNT = 120
FRAME_DURATION_MS = 83
SOURCE_WIDTH, SOURCE_HEIGHT = 640, 360
ALPHA_THRESHOLD = 12


def _union(left: tuple[int, ...] | None, right: tuple[int, ...]) -> tuple[int, ...]:
    if left is None:
        return right
    return (min(left[0], right[0]), min(left[1], right[1]),
            max(left[2], right[2]), max(left[3], right[3]))


def _frame_from_bytes(data: bytes) -> Image.Image:
    frame = Image.frombytes("RGBA", (SOURCE_WIDTH, SOURCE_HEIGHT), data)
    alpha = frame.getchannel("A")
    alpha = alpha.point([0 if value < ALPHA_THRESHOLD else value for value in range(256)])
    frame.putalpha(alpha)
    return frame


def _read_raw_frame(stream: Any, frame_bytes: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < frame_bytes:
        chunk = stream.read(frame_bytes - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def _decode(name: str, research: Path, scratch: Path, ffmpeg: str) -> dict[str, Any]:
    filename, original_name, expected_size = SOURCES[name]
    source = research / filename
    payload = source.read_bytes()
    if len(payload) != expected_size:
        raise ValueError(f"Incomplete or unexpected source {source}: {len(payload)} bytes")
    raw_path = scratch / f"{name}.rgba"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-threads", "1",
               "-c:v", "libvpx-vp9", "-i", str(source), "-t", "10",
               "-vf", "fps=12,format=rgba", "-frames:v", str(FRAME_COUNT),
               "-threads", "1", "-f", "rawvideo", "pipe:1"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    bbox: tuple[int, ...] | None = None
    seen = 0
    frame_bytes = SOURCE_WIDTH * SOURCE_HEIGHT * 4
    try:
        with raw_path.open("wb") as raw:
            for _ in range(FRAME_COUNT):
                data = _read_raw_frame(process.stdout, frame_bytes)
                if len(data) != frame_bytes:
                    break
                frame = _frame_from_bytes(data)
                current = frame.getchannel("A").getbbox()
                if current is not None:
                    bbox = _union(bbox, current)
                raw.write(frame.tobytes())
                seen += 1
        process.stdout.close()
        error = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
        returncode = process.wait(timeout=30)
        if returncode or seen != FRAME_COUNT or bbox is None:
            raise RuntimeError(f"Cannot decode {name}: {seen} frames, ffmpeg={returncode}: {error}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    print(f"Decoded {name}: {seen} frames, stable union {bbox}", flush=True)
    return {"name": name, "original_name": original_name, "source_file": filename,
            "source_bytes": len(payload), "source_sha256": hashlib.sha256(payload).hexdigest(),
            "source_path": f"dsh-pet/assets/webm/{original_name}.webm", "raw_path": str(raw_path),
            "union_bbox": list(bbox), "frame_count": seen}


def _encode(record: dict[str, Any], root: Path, scale: float) -> dict[str, Any]:
    name = record["name"]
    folder = root / "assets" / "community" / name
    folder.mkdir(parents=True, exist_ok=True)
    bbox = tuple(record["union_bbox"])
    width = max(1, round((bbox[2] - bbox[0]) * scale))
    height = max(1, round((bbox[3] - bbox[1]) * scale))
    frame_bytes = SOURCE_WIDTH * SOURCE_HEIGHT * 4
    frames: list[str] = []
    alpha_extrema = [255, 0]
    total_bytes = 0
    with Path(record["raw_path"]).open("rb") as raw:
        for index in range(record["frame_count"]):
            frame = Image.frombytes("RGBA", (SOURCE_WIDTH, SOURCE_HEIGHT), raw.read(frame_bytes))
            frame = frame.crop(bbox).resize((width, height), Image.Resampling.LANCZOS)
            # Resampling may introduce tiny edge alpha; keep background fully clear.
            alpha = frame.getchannel("A").point([0 if value < ALPHA_THRESHOLD else value for value in range(256)])
            frame.putalpha(alpha)
            minimum, maximum = alpha.getextrema()
            alpha_extrema = [min(alpha_extrema[0], minimum), max(alpha_extrema[1], maximum)]
            destination = folder / f"{index:04d}.webp"
            frame.save(destination, "WEBP", lossless=True, exact=True, method=2)
            total_bytes += destination.stat().st_size
            frames.append(destination.relative_to(root).as_posix())
    result = {key: value for key, value in record.items() if key != "raw_path"}
    result.update({"duration_ms": record["frame_count"] * FRAME_DURATION_MS,
                   "source_duration_ms": 10042, "frame_duration_ms": FRAME_DURATION_MS,
                   "size": {"width": width, "height": height}, "width": width, "height": height,
                   "canvas": {"width": width, "height": height}, "anchor": {"x": width / 2, "y": height},
                   "anchor_mode": "ground", "scale": scale, "frames": frames,
                   "alpha": {"source_alpha_mode": 1, "threshold": ALPHA_THRESHOLD,
                             "extrema": alpha_extrema, "verified": alpha_extrema == [0, 255]},
                   "encoded_bytes": total_bytes,
                   "source_url": f"{SOURCE_REPOSITORY}/blob/{SOURCE_COMMIT}/{record['source_path']}"})
    if height > 306 or alpha_extrema != [0, 255]:
        raise RuntimeError(f"Invalid output dimensions/transparency for {name}")
    print(f"Encoded {name}: {width}x{height}, {total_bytes:,} bytes", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", type=Path, default=Path(__file__).resolve().parents[2] / "animation-research")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--workers", type=int, default=3)
    arguments = parser.parse_args()
    workers = max(1, min(3, arguments.workers))
    root = arguments.project.resolve()
    output = root / "assets" / "community"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="community-animation-", dir=arguments.research) as temp:
        scratch = Path(temp)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            decoded = list(pool.map(lambda name: _decode(name, arguments.research, scratch, arguments.ffmpeg), SOURCES))
        maximum_height = max(record["union_bbox"][3] - record["union_bbox"][1] for record in decoded)
        scale = 306 / maximum_height
        with ThreadPoolExecutor(max_workers=workers) as pool:
            clips = list(pool.map(lambda record: _encode(record, root, scale), decoded))
    manifest = {"schema_version": 1, "name": "大肥鱼·社区连续动画", "source_repository": SOURCE_REPOSITORY,
                "source_commit": SOURCE_COMMIT, "license": "CC BY-NC-SA 4.0 / upstream noncommercial asset terms",
                "modifications": "VP9-alpha decoded with libvpx-vp9; 12 fps / 120 frames; alpha<12 cleared; stable per-clip union crop; one shared scale; lossless RGBA WebP.",
                "frame_duration_ms": FRAME_DURATION_MS, "global_scale": scale,
                "maximum_source_union_height": maximum_height, "maximum_output_height": 306,
                "clips": clips}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    notice = arguments.research / "ANIMATION_SOURCE_NOTICE.md"
    if notice.is_file():
        shutil.copyfile(notice, output / "NOTICE.md")
    print(f"Imported {len(clips)} clips / {sum(clip['frame_count'] for clip in clips)} frames to {output}", flush=True)


if __name__ == "__main__":
    main()
