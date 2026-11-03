"""Local, inspectable companion memory. This module never calls a model or API."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterator


SCHEMA_VERSION = 1
BACKUP_FORMAT = "dafeiyu-companion-backup"
PROFILE_DEFAULTS = {
    "owner_name": "",
    "nickname": "",
    "pet_name": "大肥鱼",
    "birthday": "",
    "likes": "",
    "dislikes": "",
}
SETTING_DEFAULTS = {
    "voice_enabled": False,
    "voice_auto": False,
    "voice_id": "",
    "voice_rate": 0,
    "voice_volume": 75,
    "quiet_start": 23,
    "quiet_end": 8,
}
DAILY_POINT_LIMIT = 60
# Both the points and calendar-day requirements must be met. The eighth level
# rewards long companionship rather than a large number of clicks in one day.
LEVELS = (
    (0, 1, "初次见面"),
    (120, 3, "渐渐熟悉"),
    (360, 7, "熟悉搭档"),
    (720, 14, "日常陪伴"),
    (1200, 30, "安心相处"),
    (1800, 60, "彼此默契"),
    (2700, 90, "长久陪伴"),
    (4200, 180, "岁月老友"),
)
INTERACTIONS = {
    "feed": (8, 120, "一起吃点东西"),
    "pat": (4, 90, "摸摸头"),
    "play": (10, 180, "一起玩了一会儿"),
    "visit": (2, 0, "又见到你啦"),
    "sleep": (4, 3600, "好好休息"),
    "focus": (8, 1800, "一起认真了一会儿"),
}
EVENT_KINDS = frozenset(INTERACTIONS) | {
    "profile", "memory", "forget", "reminder", "reminder_done", "reminder_due"
}


def _text(value: Any, label: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是文字")
    if nonempty and not value.strip():
        raise ValueError(f"{label}不能为空")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{label}不是有效整数或超出范围")
    return value


def _datetime(value: Any, label: str) -> datetime:
    _text(value, label, nonempty=True)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label}必须是有效的 ISO 日期和时间") from error
    # An unqualified date or a timezone-free timestamp is ambiguous in backups.
    if "T" not in value and " " not in value:
        raise ValueError(f"{label}必须包含时间")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label}必须包含时区")
    return parsed


def _exact_keys(value: Any, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label}字段不完整或包含未知字段")
    return value


def _validate_profile(value: Any) -> dict[str, str]:
    _exact_keys(value, set(PROFILE_DEFAULTS), "相处资料")
    result = {key: _text(value[key], key) for key in PROFILE_DEFAULTS}
    birthday = result["birthday"].strip()
    if birthday:
        try:
            if len(birthday) == 5 and birthday[2] == "-":
                date.fromisoformat("2000-" + birthday)
            else:
                date.fromisoformat(birthday)
        except ValueError as error:
            raise ValueError("生日请填写 YYYY-MM-DD 或 MM-DD") from error
    return result


def _validate_setting(key: str, value: Any) -> Any:
    if key not in SETTING_DEFAULTS:
        raise ValueError(f"未知设置：{key}")
    if key in {"voice_enabled", "voice_auto"}:
        if type(value) is not bool:
            raise ValueError(f"{key}必须是开关值")
    elif key == "voice_id":
        _text(value, key)
    elif key == "voice_rate":
        _integer(value, key, -10, 10)
    elif key == "voice_volume":
        _integer(value, key, 0, 100)
    else:
        _integer(value, key, 0, 23)
    return value


def _json_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"备份包含重复字段：{key}")
        result[key] = value
    return result


class CompanionStore:
    """A transactional SQLite store for care, factual notes, and reminders.

    ``snapshot`` limits only its event *view* to 100 entries. The database and
    backups retain every event and every note until the user explicitly deletes
    a note. ``likes`` and ``dislikes`` are editable text, never inferred facts.
    """

    def __init__(self, data_dir: Path, *, clock: Callable[[], datetime] | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "companion.sqlite3"
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA busy_timeout = 15000")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, SCHEMA_VERSION}:
                raise ValueError(f"记忆数据库版本 {version} 暂不支持，请使用相应版本的程序")
            if version == 0:
                existing = self._db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing:
                    raise ValueError("已有数据库缺少受支持的版本标记，未修改原数据")
                self._create_schema()
            self._check_schema()
            self._profile()
            self._settings()
            _datetime(self._created_at(), "建立时间")
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.execute("PRAGMA synchronous = FULL")
        except Exception:
            self._db.close()
            self._closed = True
            raise

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValueError("clock 必须返回 datetime")
        return value.astimezone() if value.tzinfo is None else value

    @staticmethod
    def _stamp(value: datetime) -> str:
        return value.isoformat(timespec="microseconds")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("记忆数据库已经关闭")

    @contextmanager
    def _transaction(self, *, write: bool = True) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            self._db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _create_schema(self) -> None:
        statements = (
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE TABLE profile (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
                day TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
                detail TEXT NOT NULL, food TEXT NOT NULL,
                points INTEGER NOT NULL CHECK(points BETWEEN 0 AND 60))""",
            "CREATE INDEX events_day_kind ON events(day, kind)",
            "CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, text TEXT NOT NULL)",
            """CREATE TABLE reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
                due_at TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0,1)),
                notified_at TEXT)""",
        )
        with self._transaction():
            for statement in statements:
                self._db.execute(statement)
            self._db.execute("PRAGMA user_version = 1")
            self._db.execute("INSERT INTO metadata VALUES ('created_at', ?)", (self._stamp(self._now()),))
            self._db.executemany("INSERT INTO profile VALUES (?,?)", PROFILE_DEFAULTS.items())
            self._db.executemany(
                "INSERT INTO settings VALUES (?,?)",
                ((key, json.dumps(value, ensure_ascii=False)) for key, value in SETTING_DEFAULTS.items()),
            )

    def _check_schema(self) -> None:
        expected = {
            "metadata": {"key", "value"},
            "profile": {"key", "value"},
            "settings": {"key", "value"},
            "events": {"id", "at", "day", "kind", "title", "detail", "food", "points"},
            "notes": {"id", "at", "text"},
            "reminders": {"id", "text", "due_at", "done", "notified_at"},
        }
        for table, columns in expected.items():
            actual = {row["name"] for row in self._db.execute(f"PRAGMA table_info({table})")}
            if actual != columns:
                raise ValueError(f"记忆数据库的 {table} 结构异常，未修改原数据")
        if self._db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("记忆数据库完整性检查失败")

    def _created_at(self) -> str:
        row = self._db.execute("SELECT value FROM metadata WHERE key='created_at'").fetchone()
        if row is None:
            raise ValueError("记忆数据库缺少建立时间")
        return row[0]

    def _profile(self) -> dict:
        return _validate_profile(dict(self._db.execute("SELECT key,value FROM profile")))

    def _settings(self) -> dict:
        try:
            result = {row[0]: json.loads(row[1]) for row in self._db.execute("SELECT key,value FROM settings")}
        except (ValueError, TypeError) as error:
            raise ValueError("记忆数据库的设置损坏") from error
        _exact_keys(result, set(SETTING_DEFAULTS), "设置")
        for key, value in result.items():
            _validate_setting(key, value)
        return result

    def _days(self, now: datetime) -> int:
        return max(1, (now.date() - _datetime(self._created_at(), "建立时间").date()).days + 1)

    def _total_points(self) -> int:
        return self._db.execute("SELECT COALESCE(SUM(points),0) FROM events").fetchone()[0]

    @staticmethod
    def _level(points: int, days: int) -> int:
        level = 1
        for number, (needed_points, needed_days, _stage) in enumerate(LEVELS, 1):
            if points >= needed_points and days >= needed_days:
                level = number
        return level

    def _add_event(self, now: datetime, kind: str, title: str, detail: str = "", food: str = "", points: int = 0) -> int:
        cursor = self._db.execute(
            "INSERT INTO events(at,day,kind,title,detail,food,points) VALUES (?,?,?,?,?,?,?)",
            (self._stamp(now), now.date().isoformat(), kind, title, detail, food, points),
        )
        return int(cursor.lastrowid)

    def snapshot(self) -> dict:
        now = self._now()
        with self._transaction(write=False):
            points = self._total_points()
            days = self._days(now)
            level = self._level(points, days)
            today = now.date().isoformat()
            today_care = {kind: 0 for kind in ("feed", "pat", "play")}
            total_care = dict(today_care)
            for row in self._db.execute(
                "SELECT kind,COUNT(*) AS total,SUM(CASE WHEN day=? THEN 1 ELSE 0 END) AS today "
                "FROM events WHERE kind IN ('feed','pat','play') GROUP BY kind", (today,)
            ):
                total_care[row["kind"]] = row["total"]
                today_care[row["kind"]] = row["today"]
            events = [dict(row) for row in self._db.execute(
                "SELECT id,at,kind,title,detail,food FROM events ORDER BY id DESC LIMIT 100"
            )]
            return {
                "profile": self._profile(),
                "settings": self._settings(),
                "created_at": self._created_at(),
                "days_together": days,
                "total_points": points,
                "level": level,
                "stage": LEVELS[level - 1][2],
                "next_level_points": LEVELS[level][0] if level < len(LEVELS) else None,
                "next_level_days": LEVELS[level][1] if level < len(LEVELS) else None,
                "daily_points": self._db.execute(
                    "SELECT COALESCE(SUM(points),0) FROM events WHERE day=?", (today,)
                ).fetchone()[0],
                "today_care": today_care,
                "total_care": total_care,
                "events": events,
                "event_count": self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "notes": [dict(row) for row in self._db.execute("SELECT id,at,text FROM notes ORDER BY id DESC")],
                "reminders": [
                    {"id": row["id"], "text": row["text"], "due_at": row["due_at"], "done": bool(row["done"])}
                    for row in self._db.execute("SELECT * FROM reminders ORDER BY done,id DESC")
                ],
            }

    def update_profile(self, fields: dict) -> None:
        if not isinstance(fields, dict) or not set(fields).issubset(PROFILE_DEFAULTS):
            raise ValueError("相处资料包含未知字段")
        with self._transaction():
            current = self._profile()
            updated = _validate_profile({**current, **fields})
            if updated == current:
                return
            self._db.executemany("UPDATE profile SET value=? WHERE key=?", ((value, key) for key, value in updated.items()))
            self._add_event(self._now(), "profile", "更新相处资料", "你调整了称呼或相处偏好。")

    def set_setting(self, key: str, value: Any) -> None:
        _validate_setting(key, value)
        with self._transaction():
            self._db.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(value, ensure_ascii=False), key))

    def record_interaction(self, kind: str, detail: str = "", food: str = "") -> dict:
        if kind not in INTERACTIONS:
            raise ValueError(f"未知互动：{kind}")
        _text(detail, "互动详情")
        _text(food, "食物名称")
        if kind != "feed" and food:
            raise ValueError("只有喂食事件可以记录食物")
        now = self._now()
        stamp = self._stamp(now)
        today = now.date().isoformat()
        base_points, cooldown, title = INTERACTIONS[kind]
        if kind == "feed" and food:
            title = f"一起吃了{food}"
        with self._transaction():
            total_before = self._total_points()
            level_before = self._level(total_before, self._days(now))
            # Calls from a sleep/focus/visit state hook may arrive each frame.
            # Coalesce only identical passive notifications; explicit care is
            # always remembered, even when it earns no additional experience.
            if kind in {"visit", "sleep", "focus"}:
                previous = self._db.execute(
                    "SELECT at,detail,food FROM events WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,)
                ).fetchone()
                if previous and previous["detail"] == detail and previous["food"] == food:
                    elapsed = (now - _datetime(previous["at"], "互动时间")).total_seconds()
                    if 0 <= elapsed < 300 and _datetime(previous["at"], "互动时间").date() == now.date():
                        return {"title": title, "text": "这段相处已经记下啦。", "points": 0, "leveled_up": False}
            earned_today = self._db.execute(
                "SELECT COALESCE(SUM(points),0) FROM events WHERE day=?", (today,)
            ).fetchone()[0]
            last_award = self._db.execute(
                "SELECT at,day FROM events WHERE kind=? AND points>0 ORDER BY id DESC LIMIT 1", (kind,)
            ).fetchone()
            eligible = True
            if last_award:
                elapsed = (now - _datetime(last_award["at"], "互动时间")).total_seconds()
                eligible = elapsed >= cooldown if kind != "visit" else last_award["day"] != today and elapsed >= 0
            points = min(base_points, max(0, DAILY_POINT_LIMIT - earned_today)) if eligible else 0
            self._add_event(now, kind, title, detail, food, points)
            leveled_up = self._level(total_before + points, self._days(now)) > level_before
            address = self._profile()["nickname"] or self._profile()["owner_name"]
            prefix = f"{address}，" if address else ""
            if kind == "feed":
                response = f"{prefix}这次的{food}我记住啦。" if food else f"{prefix}这次喂食已经记下来啦。"
            elif kind == "pat":
                response = f"{prefix}这次摸摸头也收进我们的相处记录啦。"
            elif kind == "play":
                response = f"{prefix}一起玩过的这会儿，我记下啦。"
            else:
                response = f"{prefix}{title}，这段相处已经保存。"
            if leveled_up:
                response += "我们又熟悉了一点！"
            return {"title": title, "text": response, "points": points, "leveled_up": leveled_up}

    def remember(self, text: str) -> dict:
        _text(text, "手写记忆", nonempty=True)
        now = self._now()
        at = self._stamp(now)
        with self._transaction():
            cursor = self._db.execute("INSERT INTO notes(at,text) VALUES (?,?)", (at, text))
            result = {"id": int(cursor.lastrowid), "at": at, "text": text}
            # Keep the fact itself only in notes so forgetting really removes
            # it from every query and subsequent export, not just one panel.
            self._add_event(now, "memory", "记住了一件事", "你新增了一条手写记忆。")
            return result

    def forget_note(self, note_id: int) -> None:
        _integer(note_id, "记忆编号", 1)
        with self._transaction():
            if self._db.execute("DELETE FROM notes WHERE id=?", (note_id,)).rowcount == 0:
                raise ValueError("找不到这条手写记忆")
            self._add_event(self._now(), "forget", "忘记一条笔记", "你删除了一条手写记忆。")

    def recall(self) -> str:
        with self._transaction(write=False):
            profile = self._profile()
            address = profile["nickname"] or profile["owner_name"]
            parts = [f"{address}，" if address else ""]
            feeding = self._db.execute("SELECT at,food FROM events WHERE kind='feed' ORDER BY id DESC LIMIT 1").fetchone()
            note = self._db.execute("SELECT text FROM notes ORDER BY id DESC LIMIT 1").fetchone()
            if feeding:
                when = _datetime(feeding["at"], "喂食时间").strftime("%Y年%m月%d日 %H:%M")
                parts.append(f"我记得你在{when}给我喂了{feeding['food']}。" if feeding["food"] else f"我记得你在{when}喂过我。")
            if note:
                parts.append(f"你让我记住的是：{note['text']}")
            if not feeding and not note:
                parts.append("我们的具体相处记录还很少。你可以喂我一点东西，或者写下一件想让我记住的事。")
            return "".join(parts)

    def add_reminder(self, text: str, due_at: datetime | str) -> dict:
        _text(text, "提醒内容", nonempty=True)
        if isinstance(due_at, datetime):
            due = due_at.astimezone() if due_at.tzinfo is None else due_at
        else:
            # UI date editors commonly emit a timezone-free ISO string. Attach
            # the store clock's local timezone explicitly before persisting it.
            _text(due_at, "提醒时间", nonempty=True)
            try:
                due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("提醒时间无效") from error
            if "T" not in due_at and " " not in due_at:
                raise ValueError("提醒时间必须包含时分")
            if due.tzinfo is None:
                due = due.replace(tzinfo=self._now().tzinfo)
        due_string = self._stamp(due)
        with self._transaction():
            cursor = self._db.execute("INSERT INTO reminders(text,due_at) VALUES (?,?)", (text, due_string))
            self._add_event(self._now(), "reminder", "记下一项提醒", f"{text}（{due_string}）")
            return {"id": int(cursor.lastrowid), "text": text, "due_at": due_string, "done": False}

    def complete_reminder(self, reminder_id: int) -> None:
        _integer(reminder_id, "提醒编号", 1)
        with self._transaction():
            row = self._db.execute("SELECT text,done FROM reminders WHERE id=?", (reminder_id,)).fetchone()
            if row is None:
                raise ValueError("找不到这项提醒")
            if not row["done"]:
                self._db.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))
                self._add_event(self._now(), "reminder_done", "完成一项提醒", row["text"])

    def due_reminders(self) -> list:
        now = self._now()
        with self._transaction():
            due = []
            for row in self._db.execute("SELECT * FROM reminders WHERE done=0 AND notified_at IS NULL ORDER BY id"):
                if _datetime(row["due_at"], "提醒时间") <= now:
                    due.append({"id": row["id"], "text": row["text"], "due_at": row["due_at"], "done": False})
            for item in due:
                self._db.execute("UPDATE reminders SET notified_at=? WHERE id=?", (self._stamp(now), item["id"]))
                self._add_event(now, "reminder_due", "到提醒时间啦", item["text"])
            return due

    def _backup_payload(self) -> dict:
        return {
            "format": BACKUP_FORMAT,
            "version": SCHEMA_VERSION,
            "created_at": self._created_at(),
            "exported_at": self._stamp(self._now()),
            "profile": self._profile(),
            "settings": self._settings(),
            "events": [dict(row) for row in self._db.execute("SELECT * FROM events ORDER BY id")],
            "notes": [dict(row) for row in self._db.execute("SELECT * FROM notes ORDER BY id")],
            "reminders": [
                {**dict(row), "done": bool(row["done"])}
                for row in self._db.execute("SELECT * FROM reminders ORDER BY id")
            ],
        }

    @staticmethod
    def _write_backup(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def export_backup(self, path: Path) -> None:
        path = Path(path)
        if path.resolve() == self.path.resolve():
            raise ValueError("备份文件不能覆盖正在使用的数据库")
        with self._transaction(write=False):
            payload = self._backup_payload()
        self._write_backup(path, payload)

    @staticmethod
    def _validate_backup(payload: Any) -> dict:
        _exact_keys(payload, {"format", "version", "created_at", "exported_at", "profile", "settings", "events", "notes", "reminders"}, "备份")
        if payload["format"] != BACKUP_FORMAT or type(payload["version"]) is not int or payload["version"] != SCHEMA_VERSION:
            raise ValueError("备份格式或版本不受支持")
        _datetime(payload["created_at"], "建立时间")
        _datetime(payload["exported_at"], "导出时间")
        _validate_profile(payload["profile"])
        _exact_keys(payload["settings"], set(SETTING_DEFAULTS), "设置")
        for key, value in payload["settings"].items():
            _validate_setting(key, value)
        daily_points: dict[str, int] = {}
        for collection, keys in (
            ("events", {"id", "at", "day", "kind", "title", "detail", "food", "points"}),
            ("notes", {"id", "at", "text"}),
            ("reminders", {"id", "text", "due_at", "done", "notified_at"}),
        ):
            rows = payload[collection]
            if not isinstance(rows, list):
                raise ValueError(f"备份的 {collection} 必须是列表")
            seen: set[int] = set()
            for row in rows:
                _exact_keys(row, keys, collection)
                row_id = _integer(row["id"], "记录编号", 1, 9223372036854775807)
                if row_id in seen:
                    raise ValueError(f"备份的 {collection} 含重复编号")
                seen.add(row_id)
                if collection == "events":
                    at = _datetime(row["at"], "事件时间")
                    if row["day"] != at.date().isoformat():
                        raise ValueError("事件日期与时间不一致")
                    if row["kind"] not in EVENT_KINDS:
                        raise ValueError("备份包含未知事件类型")
                    for key in ("title", "detail", "food"):
                        _text(row[key], key, nonempty=key == "title")
                    points = _integer(row["points"], "事件积分", 0, DAILY_POINT_LIMIT)
                    if points and row["kind"] not in INTERACTIONS:
                        raise ValueError("非互动事件不能产生积分")
                    if row["food"] and row["kind"] != "feed":
                        raise ValueError("非喂食事件不能包含食物")
                    daily_points[row["day"]] = daily_points.get(row["day"], 0) + points
                    if daily_points[row["day"]] > DAILY_POINT_LIMIT:
                        raise ValueError("备份存在超过每日上限的积分")
                elif collection == "notes":
                    _datetime(row["at"], "记忆时间")
                    _text(row["text"], "手写记忆", nonempty=True)
                else:
                    _text(row["text"], "提醒内容", nonempty=True)
                    _datetime(row["due_at"], "提醒时间")
                    if type(row["done"]) is not bool:
                        raise ValueError("提醒完成状态无效")
                    if row["notified_at"] is not None:
                        _datetime(row["notified_at"], "已提醒时间")
        return payload

    def import_backup(self, path: Path) -> None:
        try:
            with Path(path).open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle, object_pairs_hook=_json_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"无效 JSON 数值：{value}")))
            self._validate_backup(payload)
        except (UnicodeError, json.JSONDecodeError, TypeError, OverflowError) as error:
            raise ValueError("备份文件损坏或格式不正确，原记忆未修改") from error
        with self._transaction():
            # A valid import also gets a complete, usable JSON restore point.
            # Creating that restore point must succeed before any DELETE.
            backup_name = "before-import-" + self._now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".json"
            self._write_backup(self.data_dir / "backups" / backup_name, self._backup_payload())
            for table in ("events", "notes", "reminders", "profile", "settings"):
                self._db.execute(f"DELETE FROM {table}")
            self._db.execute("UPDATE metadata SET value=? WHERE key='created_at'", (payload["created_at"],))
            self._db.executemany("INSERT INTO profile VALUES (?,?)", payload["profile"].items())
            self._db.executemany("INSERT INTO settings VALUES (?,?)", ((key, json.dumps(value, ensure_ascii=False)) for key, value in payload["settings"].items()))
            self._db.executemany(
                "INSERT INTO events(id,at,day,kind,title,detail,food,points) VALUES (:id,:at,:day,:kind,:title,:detail,:food,:points)", payload["events"]
            )
            self._db.executemany("INSERT INTO notes(id,at,text) VALUES (:id,:at,:text)", payload["notes"])
            self._db.executemany(
                "INSERT INTO reminders(id,text,due_at,done,notified_at) VALUES (:id,:text,:due_at,:done,:notified_at)", payload["reminders"]
            )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True
