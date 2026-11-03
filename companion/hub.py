"""The standalone companion journal window.

Only explicit profile, journal and setting edits are persisted here. Care actions
are emitted for the desktop pet controller to record exactly once.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDateTime, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSlider, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)


STYLE = """
QWidget { color: #24334a; font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QWidget#CompanionHub { background: #f6f8fc; }
QFrame#Sidebar { background: #edf3fb; border-right: 1px solid #e1e8f2; }
QLabel#Brand { color: #264b8c; font-size: 22px; font-weight: 700; }
QLabel#PageTitle { color: #202f4a; font-size: 26px; font-weight: 700; }
QLabel#Subtitle, QLabel#Muted { color: #6b7890; }
QLabel#HeroName { color: #294c89; font-size: 23px; font-weight: 700; }
QLabel#SectionTitle { color: #294064; font-size: 16px; font-weight: 700; }
QLabel#BigNumber { color: #355b9b; font-size: 28px; font-weight: 700; }
QFrame#Card { background: #ffffff; border: 1px solid #e3eaf3; border-radius: 14px; }
QFrame#PetPortrait { background: #eef5fd; border: 0; border-radius: 16px; }
QPushButton { background: #f5f8fd; border: 1px solid #dbe4f0; border-radius: 8px; padding: 9px 14px; color: #344e78; }
QPushButton:hover { background: #eaf1fc; border-color: #b8cdec; }
QPushButton:pressed { background: #dce8f9; }
QPushButton:disabled { color: #9ba7b6; background: #f2f4f7; border-color: #e7ebf1; }
QPushButton#Primary { background: #3c61a6; border-color: #3c61a6; color: white; font-weight: 600; }
QPushButton#Primary:hover { background: #315594; }
QPushButton#Nav { background: transparent; border: 0; text-align: left; padding: 12px 15px; color: #64738c; }
QPushButton#Nav:checked { background: #dce8f9; color: #2c528f; font-weight: 600; }
QPushButton#Nav:hover { background: #e2ecfa; }
QPushButton#Care { background: #f5f8fe; min-height: 35px; font-weight: 600; }
QLineEdit, QTextEdit, QComboBox, QDateTimeEdit, QListWidget { background: #fbfcff; border: 1px solid #dce5f1; border-radius: 7px; padding: 8px; selection-background-color: #d7e6fb; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #83a6d7; }
QListWidget::item { padding: 8px 6px; border-radius: 5px; }
QListWidget::item:selected { background: #e3edfb; color: #254d8b; }
QProgressBar { background: #eaf0f8; border: 0; border-radius: 5px; min-height: 9px; max-height: 9px; }
QProgressBar::chunk { background: #6388c7; border-radius: 5px; }
QScrollArea { background: transparent; border: 0; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px; }
QScrollBar::handle:vertical { background: #cdd9e9; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QCheckBox { spacing: 8px; padding: 3px 0; }
QSlider::groove:horizontal { height: 5px; background: #e1e9f5; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #6388c7; border-radius: 7px; }
"""


def _text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value)
    return "" if value is None else str(value)


def _when(value: Any) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%m月%d日 %H:%M")
    except (ValueError, TypeError):
        return str(value).replace("T", " ")[:16]


class CompanionHub(QWidget):
    interaction_requested = Signal(str, str)
    settings_changed = Signal()
    profile_changed = Signal()
    focus_requested = Signal(int)
    audio_output_requested = Signal(str)
    voice_import_requested = Signal(str)
    voice_caption_ready = Signal(str)

    def __init__(self, store, speech, *, assets_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.speech = speech
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self._snapshot: dict[str, Any] = {}
        self._profile_dirty = False
        self._voice_signature = None
        self._voice_id = ""
        self._focus_running = False
        self._editing_reminder_id = None
        self._voice_save_timer = QTimer(self)
        self._voice_save_timer.setSingleShot(True)
        self._voice_save_timer.setInterval(250)
        self._voice_save_timer.timeout.connect(self._save_voice)
        self._pages: dict[str, QWidget] = {}
        self._nav: dict[str, QPushButton] = {}
        self.setObjectName("CompanionHub")
        self.setWindowTitle("大肥鱼 · 相处日记")
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(960, 740)
        self.setMinimumSize(800, 600)
        self.setStyleSheet(STYLE)
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self._build()
        self.refresh()
        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(1500)
        self._voice_timer.timeout.connect(self._refresh_voices)
        self._voice_timer.start()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(30000)
        self._clock_timer.timeout.connect(self._refresh_home)
        self._clock_timer.start()

    @staticmethod
    def _label(text: str, role: str = "", *, wrap=True) -> QLabel:
        label = QLabel(text)
        if role:
            label.setObjectName(role)
        label.setWordWrap(wrap)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _button(text: str, slot=None, role="") -> QPushButton:
        button = QPushButton(text)
        if role:
            button.setObjectName(role)
        if slot:
            button.clicked.connect(slot)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _card(self, title: str = ""):
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        if title:
            layout.addWidget(self._label(title, "SectionTitle"))
        return frame, layout

    def _page(self, name: str, title: str, subtitle: str):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(25, 25, 20, 20)
        outer.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(self._label(title, "PageTitle"), 1)
        close_button = self._button("关闭", self.close)
        close_button.setObjectName("hubClose_" + name)
        close_button.setToolTip("关闭日记，回到桌宠 · Esc")
        heading.addWidget(close_button, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(heading)
        outer.addWidget(self._label(subtitle, "Subtitle"))
        outer.addSpacing(9)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("ScrollBody")
        body.setStyleSheet("QWidget#ScrollBody { background: transparent; }")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 6, 3)
        content.setSpacing(16)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self._pages[name] = page
        self.stack.addWidget(page)
        return content

    def _build(self):
        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(170)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 29, 18, 22)
        side.setSpacing(8)
        side.addWidget(self._label("大肥鱼", "Brand"))
        side.addWidget(self._label("相处日记", "Muted"))
        side.addSpacing(26)
        self.stack = QStackedWidget()
        for name, label in (("home", "今天一起"), ("alarms", "闹钟提醒"), ("memory", "我们的记忆"), ("growth", "慢慢长大"), ("settings", "习惯与设置")):
            button = self._button(label, lambda checked=False, n=name: self.show_page(n), "Nav")
            button.setCheckable(True)
            self._nav[name] = button
            side.addWidget(button)
        side.addStretch()
        side.addWidget(self._label("独立陪伴 · 本地保存\n不需要账号或模型接口", "Muted"))
        side.addSpacing(10)
        side.addWidget(self._button("收起日记", self.hide))
        shell.addWidget(sidebar)
        shell.addWidget(self.stack, 1)
        self._build_home()
        self._build_alarms()
        self._build_memory()
        self._build_growth()
        self._build_settings()
        self.show_page("home")

    def _build_home(self):
        content = self._page("home", "今天，也一起吧", "每一次照顾，都会留在这台电脑的相处日记里。")
        hero, box = self._card()
        row = QHBoxLayout()
        portrait_frame = QFrame()
        portrait_frame.setObjectName("PetPortrait")
        portrait_frame.setFixedWidth(160)
        portrait_layout = QVBoxLayout(portrait_frame)
        self.portrait = self._label("大肥鱼\n在这里陪你", "HeroName")
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait.setMinimumHeight(160)
        portrait_layout.addWidget(self.portrait)
        self._load_portrait()
        row.addWidget(portrait_frame)
        detail = QVBoxLayout()
        detail.setContentsMargins(17, 8, 0, 5)
        self.hero_name = self._label("大肥鱼", "HeroName")
        self.hero_days = self._label("这是我们相处的第 1 天", "Muted")
        self.hero_stage = self._label("Lv.1 · 初次见面")
        self.hero_progress = QProgressBar()
        self.hero_progress.setTextVisible(False)
        self.hero_points = self._label("", "Muted")
        detail.addWidget(self.hero_name)
        detail.addWidget(self.hero_days)
        detail.addStretch()
        detail.addWidget(self.hero_stage)
        detail.addWidget(self.hero_progress)
        detail.addWidget(self.hero_points)
        row.addLayout(detail, 1)
        box.addLayout(row)
        content.addWidget(hero)

        care, box = self._card("给今天添一点小事")
        self.today_summary = self._label("", "Muted")
        box.addWidget(self.today_summary)
        food_row = QHBoxLayout()
        self.food_combo = QComboBox()
        self.food_combo.setObjectName("foodChoice")
        for name, value in (("一碗白饭", "白饭"), ("一只虾", "虾"), ("一块蛋糕", "蛋糕"), ("一串团子", "团子")):
            self.food_combo.addItem(name, value)
        food_row.addWidget(self.food_combo, 1)
        self.feed_button = self._button("投喂她", lambda: self.interaction_requested.emit("feed", self.food_combo.currentData()), "Primary")
        food_row.addWidget(self.feed_button)
        box.addLayout(food_row)
        actions = QHBoxLayout()
        for text, kind in (("摸摸头", "pat"), ("陪她玩", "play"), ("好好休息", "sleep")):
            button = self._button(text, lambda checked=False, k=kind: self.interaction_requested.emit(k, ""), "Care")
            button.setProperty("careKind", kind)
            actions.addWidget(button, 1)
        box.addLayout(actions)
        content.addWidget(care)

        focus, box = self._card("安静陪你一会儿")
        focus_row = QHBoxLayout()
        self.focus_status = self._label("做自己的事，也有人在旁边陪着。", "Muted")
        focus_row.addWidget(self.focus_status, 1)
        self.focus_button = self._button("一起专注 25 分钟", lambda: self._focus(25))
        self.focus_stop_button = self._button("结束专注", lambda: self._focus(0))
        self.focus_stop_button.setVisible(False)
        focus_row.addWidget(self.focus_button)
        focus_row.addWidget(self.focus_stop_button)
        box.addLayout(focus_row)
        content.addWidget(focus)

        reminder, box = self._card("闹钟提醒")
        self.home_alarm_summary = self._label("还没有设置闹钟。", "Muted")
        box.addWidget(self.home_alarm_summary)
        button = self._button("设置闹钟", lambda: self.show_page("alarms"))
        button.setObjectName("openAlarms")
        box.addWidget(button)
        content.addWidget(reminder)
        content.addStretch()

    def _build_alarms(self):
        content = self._page("alarms", "约好时间，提醒你", "一次、每天或工作日的小约定，都保存在这台电脑。")
        delivery, box = self._card()
        self.alarms_enabled = QCheckBox("启用闹钟提醒")
        self.alarms_enabled.setObjectName("alarmsEnabled")
        self.alarms_enabled.setStyleSheet("font-size:16px;font-weight:600;color:#294064;")
        self.alarms_enabled.setToolTip("关闭后不弹窗、不响铃，但可以继续保存和编辑闹钟。重新开启后，每个过期闹钟最多补提醒一次。")
        self.alarms_enabled.setToolTipDuration(20000)
        self.alarms_enabled.toggled.connect(self._save_alarms_enabled)
        box.addWidget(self.alarms_enabled)
        self.alarms_delivery_status = self._label("", "Muted")
        box.addWidget(self.alarms_delivery_status)
        content.addWidget(delivery)
        editor, box = self._card("设置一个闹钟")
        self.alarm_edit_status = self._label("新闹钟", "Muted")
        box.addWidget(self.alarm_edit_status)
        self.reminder_text = QLineEdit()
        self.reminder_text.setPlaceholderText("比如：今晚记得喝水")
        self.reminder_text.setObjectName("alarmText")
        self.reminder_text.setMaxLength(200)
        box.addWidget(self.reminder_text)
        reminder_row = QHBoxLayout()
        self.reminder_due = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.reminder_due.setObjectName("alarmDue")
        self.reminder_due.setDisplayFormat("yyyy年MM月dd日 HH:mm")
        self.reminder_due.setCalendarPopup(True)
        self.reminder_due.setToolTip("选择第一次提醒的日期和时分。每天沿用这个时分；工作日选到周末时会顺延到周一。")
        self.reminder_due.setToolTipDuration(20000)
        reminder_row.addWidget(self.reminder_due, 1)
        self.reminder_repeat = QComboBox()
        self.reminder_repeat.setObjectName("alarmRepeat")
        for label, value in (("只提醒一次", "once"), ("每天", "daily"), ("工作日", "weekdays")):
            self.reminder_repeat.addItem(label, value)
        self.reminder_repeat.setToolTip("每天按所选时分重复；工作日指周一到周五，不包含节假日调休判断。错过多天只补一次，随后排到下一次。")
        self.reminder_repeat.setToolTipDuration(20000)
        reminder_row.addWidget(self.reminder_repeat)
        box.addLayout(reminder_row)
        buttons = QHBoxLayout()
        self.alarm_cancel_button = self._button("取消编辑", self._cancel_alarm_edit)
        self.alarm_cancel_button.setObjectName("alarmCancelEdit")
        self.alarm_cancel_button.hide()
        buttons.addWidget(self.alarm_cancel_button)
        buttons.addStretch()
        self.alarm_save_button = self._button("添加闹钟", self._add_reminder, "Primary")
        self.alarm_save_button.setObjectName("alarmSave")
        buttons.addWidget(self.alarm_save_button)
        box.addLayout(buttons)
        self.alarm_sound_enabled = QCheckBox("播放闹钟提示音")
        self.alarm_sound_enabled.setObjectName("alarmSoundEnabled")
        self.alarm_sound_enabled.setToolTip("使用简短的离线提示音，独立于角色语音开关。关闭后仍会显示提醒；夜间安静时段也不播放。")
        self.alarm_sound_enabled.setToolTipDuration(20000)
        self.alarm_sound_enabled.toggled.connect(self._save_alarm_sound)
        box.addWidget(self.alarm_sound_enabled)
        box.addWidget(self._label("程序运行时会提醒。关闭程序或电脑睡眠时无法准点响铃；重新打开或唤醒后，错过的每个闹钟只补提醒一次。重复闹钟随后继续下一次，不会逐日补发。", "Muted"))
        content.addWidget(editor)

        alarms, box = self._card("已经约好的时间")
        self.alarm_list = QListWidget()
        self.alarm_list.setObjectName("alarmList")
        self.alarm_list.setWordWrap(True)
        self.alarm_list.setMinimumHeight(175)
        self.alarm_list.itemDoubleClicked.connect(lambda *_: self._edit_selected_alarm())
        self.alarm_list.currentItemChanged.connect(lambda *_: self._update_alarm_actions())
        box.addWidget(self.alarm_list)
        actions = QHBoxLayout()
        self.alarm_edit_button = self._button("编辑", self._edit_selected_alarm)
        self.alarm_edit_button.setObjectName("alarmEdit")
        self.alarm_complete_button = self._button("完成 / 停止重复", self._complete_selected_alarm)
        self.alarm_complete_button.setObjectName("alarmComplete")
        self.alarm_complete_button.setToolTip("一次闹钟标为完成；重复闹钟停止后续提醒。需要重新启用时，可以编辑并保存。")
        self.alarm_complete_button.setToolTipDuration(20000)
        self.alarm_delete_button = self._button("删除", self._delete_selected_alarm)
        self.alarm_delete_button.setObjectName("alarmDelete")
        self.alarm_delete_button.setToolTip("删除所选闹钟。日记里已经发生的提醒记录仍会保留。")
        self.alarm_delete_button.setToolTipDuration(20000)
        for button in (self.alarm_edit_button, self.alarm_complete_button, self.alarm_delete_button):
            actions.addWidget(button)
        box.addLayout(actions)
        self.alarm_list_status = self._label("", "Muted")
        box.addWidget(self.alarm_list_status)
        content.addWidget(alarms)
        content.addStretch()

    def _build_memory(self):
        content = self._page("memory", "我们的记忆", "你亲手留下的小事，以及每一次真实发生的照顾。")
        profile, box = self._card("先认识彼此")
        box.addWidget(self._label("这些内容由你手动填写。离线陪伴会记住它们，不会自动读取其他软件。", "Muted"))
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.profile_fields: dict[str, QLineEdit] = {}
        for key, label, placeholder in (
            ("owner_name", "你的名字", "怎么称呼你？"),
            ("nickname", "亲昵称呼", "比如：阿青"),
            ("pet_name", "她的名字", "大肥鱼"),
            ("birthday", "你的生日", "可不填，例如 06-18"),
            ("likes", "你喜欢", "食物、爱好，或一个小习惯"),
            ("dislikes", "你不喜欢", "希望她记住的小禁忌"),
        ):
            edit = QLineEdit()
            edit.setObjectName("profile_" + key)
            edit.setMaxLength(250)
            edit.setPlaceholderText(placeholder)
            edit.textEdited.connect(self._profile_edited)
            self.profile_fields[key] = edit
            form.addRow(label, edit)
        box.addLayout(form)
        self.profile_status = self._label("", "Muted")
        save_row = QHBoxLayout()
        save_row.addWidget(self.profile_status, 1)
        save_row.addWidget(self._button("保存主人档案", self._save_profile, "Primary"))
        box.addLayout(save_row)
        content.addWidget(profile)

        notes, box = self._card("想让她记住的事")
        box.addWidget(self._label("只保存你明确写下的内容。选中一条记忆后，可以随时删除。", "Muted"))
        self.note_input = QTextEdit()
        self.note_input.setObjectName("noteInput")
        self.note_input.setPlaceholderText("比如：我喜欢下雨天，忙的时候希望她安静陪着。")
        self.note_input.setMaximumHeight(90)
        box.addWidget(self.note_input)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._button("记住这件事", self._remember, "Primary"))
        box.addLayout(row)
        self.memory_search = QLineEdit()
        self.memory_search.setObjectName("memorySearch")
        self.memory_search.setPlaceholderText("搜索记忆与相处记录")
        self.memory_search.textChanged.connect(self._render_memory)
        box.addWidget(self.memory_search)
        self.note_list = QListWidget()
        self.note_list.setObjectName("noteList")
        self.note_list.setMinimumHeight(135)
        self.note_list.setMaximumHeight(230)
        self.note_list.setWordWrap(True)
        self.note_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        box.addWidget(self.note_list)
        row = QHBoxLayout()
        self.memory_count = self._label("", "Muted")
        row.addWidget(self.memory_count, 1)
        row.addWidget(self._button("忘记选中的记忆", self._forget))
        box.addLayout(row)
        content.addWidget(notes)

        timeline, box = self._card("相处的足迹")
        self.timeline_count = self._label("", "Muted")
        box.addWidget(self.timeline_count)
        self.timeline_list = QListWidget()
        self.timeline_list.setObjectName("timelineList")
        self.timeline_list.setWordWrap(True)
        self.timeline_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.timeline_list.setMinimumHeight(220)
        box.addWidget(self.timeline_list)
        content.addWidget(timeline)
        content.addStretch()

    def _build_growth(self):
        content = self._page("growth", "慢慢长大", "成长有记录，相处不用赶进度。")
        current, box = self._card("一起积攒的小小成长")
        self.growth_level = self._label("", "BigNumber")
        self.growth_total = self._label("", "Muted")
        self.growth_progress = QProgressBar()
        self.growth_progress.setTextVisible(False)
        self.growth_next = self._label("", "Muted")
        box.addWidget(self.growth_level)
        box.addWidget(self.growth_total)
        box.addWidget(self.growth_progress)
        box.addWidget(self.growth_next)
        content.addWidget(current)
        daily, box = self._card("今天已经很好了")
        self.daily_progress = QProgressBar()
        self.daily_progress.setRange(0, 60)
        self.daily_progress.setTextVisible(False)
        self.daily_label = self._label("", "BigNumber")
        box.addWidget(self.daily_label)
        box.addWidget(self.daily_progress)
        box.addWidget(self._label("每天最多积累 60 点经验。成长也需要相处时间，经验够了以后，陪伴天数达到下一阶段要求才会升级。达到每日上限后，照顾和相处仍会写进日记。", "Muted"))
        content.addWidget(daily)
        rituals, box = self._card("熟悉后的小日常")
        box.addWidget(self._label("随着彼此熟悉，再一起多做几件小事。", "Muted"))
        self.ritual_buttons = {}
        for level, title, kind, action in (
            (2, "悄悄心声", "ritual:thought", "听听心声"),
            (3, "一起小扫除", "ritual:tidy", "一起打扫"),
            (4, "晚安小仪式", "ritual:goodnight", "说声晚安"),
        ):
            row = QHBoxLayout()
            row.addWidget(self._label(f"Lv.{level} · {title}"), 1)
            button = self._button(action, lambda checked=False, k=kind: self.interaction_requested.emit(k, ""))
            button.setProperty("unlockedText", action)
            self.ritual_buttons[level] = button
            row.addWidget(button)
            box.addLayout(row)
        content.addWidget(rituals)
        milestone, box = self._card("属于我们的里程碑")
        self.milestone_labels = []
        for _ in range(4):
            label = self._label("")
            box.addWidget(label)
            self.milestone_labels.append(label)
        content.addWidget(milestone)
        content.addStretch()

    def _build_settings(self):
        content = self._page("settings", "按你的习惯相处", "语音、记忆和备份，都由你决定。")
        voice, box = self._card("听见她的声音")
        self.voice_enabled = QCheckBox("开启离线语音")
        self.voice_auto = QCheckBox("平时也说话（自动播放）")
        self.voice_auto.setToolTip("开启后，互动和空闲时可自动播放角色台词；空闲约每 1.5～3 分钟尝试一次。睡眠、专注、夜间和面板打开时暂停。")
        self.voice_auto.setToolTipDuration(20000)
        self.voice_enabled.setObjectName("voiceEnabled")
        self.voice_auto.setObjectName("voiceAutomatic")
        box.addWidget(self.voice_enabled)
        box.addWidget(self.voice_auto)
        box.addWidget(self._label("离线语音包", "SectionTitle"))
        self.voice_status = self._label("正在准备离线语音包……", "Muted")
        box.addWidget(self.voice_status)
        self.voice_choice = QComboBox()
        self.voice_choice.setObjectName("characterVoiceChoice")
        self.voice_choice.currentIndexChanged.connect(self._choose_character_voice)
        box.addWidget(self._label("她的音色", "Muted"))
        box.addWidget(self.voice_choice)
        import_row = QHBoxLayout()
        self.voice_import_zip_button = self._button("导入 ZIP 语音包", self._import_voice_zip)
        self.voice_import_zip_button.setObjectName("importZipVoicePack")
        self.voice_import_folder_button = self._button("导入语音文件夹", self._import_voice_folder)
        self.voice_import_folder_button.setObjectName("importFolderVoicePack")
        import_row.addWidget(self.voice_import_zip_button)
        import_row.addWidget(self.voice_import_folder_button)
        box.addLayout(import_row)
        box.addWidget(self._label("支持 WAV、MP3、OGG；ZIP 或文件夹均可，无需 API。根据文件名识别互动类型；有 manifest.json 时，按清单中的分类和字幕播放。语音包只包含音频与清单，不含模型权重。", "Muted"))
        self.voice_import_status = self._label("", "Muted")
        self.voice_import_status.setObjectName("voiceImportStatus")
        self.voice_import_status.hide()
        box.addWidget(self.voice_import_status)
        self.output_choice = QComboBox()
        self.output_choice.setObjectName("audioOutputChoice")
        self.output_choice.addItem("跟随系统默认输出", "")
        self.output_choice.currentIndexChanged.connect(self._choose_output)
        box.addWidget(self._label("声音从哪里播放", "Muted"))
        box.addWidget(self.output_choice)
        self.output_status = self._label("", "Muted")
        box.addWidget(self.output_status)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(14)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_label = self._label("75%", wrap=False)
        volume = QHBoxLayout()
        volume.addWidget(self.volume_slider, 1)
        volume.addWidget(self.volume_label)
        form.addRow("音量", volume)
        box.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(self._button("试听一句", self._preview_voice))
        row.addWidget(self._button("停止朗读", self._stop_voice))
        row.addStretch()
        box.addLayout(row)
        box.addWidget(self._label("默认保留社区角色原声。播放本机语音包中的固定片段，不需要账号或联网合成；导入语音包后，由你选择是否试听。", "Muted"))
        box.addWidget(self._label("主人名字、手动记忆和任意提醒内容目前只显示文字，不会用普通系统女声代读。", "Muted"))
        content.addWidget(voice)
        for control, signal in ((self.voice_enabled, "toggled"), (self.voice_auto, "toggled")):
            getattr(control, signal).connect(self._save_voice)
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.volume_slider.valueChanged.connect(lambda: self._voice_save_timer.start())

        backup, box = self._card("把相处好好保存")
        box.addWidget(self._label("导出主人档案、手动记忆和相处记录。换电脑时，可以通过备份接着陪伴。导入会替换当前记录。", "Muted"))
        row = QHBoxLayout()
        row.addWidget(self._button("导出备份", self._export_backup))
        row.addWidget(self._button("导入备份", self._import_backup))
        row.addStretch()
        box.addLayout(row)
        self.backup_status = self._label("", "Muted")
        box.addWidget(self.backup_status)
        content.addWidget(backup)
        about, box = self._card("简单相处")
        box.addWidget(self._label("关掉这本日记，她仍在桌面陪你。需要重新打开时，使用托盘菜单即可。\n\n主人档案和手动记忆留在本机。这里的回应来自离线规则与台词，不会调用聊天模型，也不会读取其他软件的聊天内容。", "Muted"))
        content.addWidget(about)
        self.return_to_pet_button = self._button("回到桌宠", self.close, "Primary")
        self.return_to_pet_button.setObjectName("hubReturnToPet")
        content.addWidget(self.return_to_pet_button)
        content.addStretch()

    def _load_portrait(self):
        if not self.assets_dir or not self.assets_dir.exists():
            return
        candidates = [self.assets_dir] if self.assets_dir.is_file() else []
        community_portrait = self.assets_dir / "community" / "idle" / "0000.webp"
        if community_portrait.is_file():
            candidates.append(community_portrait)
        for root in (self.assets_dir / "processed" / "runtime" / "states" / "idle_front", self.assets_dir / "processed" / "runtime" / "idle", self.assets_dir / "runtime" / "idle", self.assets_dir / "idle"):
            if root.exists():
                candidates.extend(p for p in root.rglob("*") if p.suffix.lower() in {".png", ".webp", ".gif"})
        if not candidates:
            candidates = list(self.assets_dir.glob("*idle*.png"))
        for candidate in sorted(candidates)[:15]:
            pixmap = QPixmap(str(candidate))
            if not pixmap.isNull():
                self.portrait.setPixmap(pixmap.scaled(140, 190, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                return

    def show_page(self, name: str):
        if name not in self._pages:
            return
        self.stack.setCurrentWidget(self._pages[name])
        for key, button in self._nav.items():
            button.setChecked(key == name)

    def refresh(self):
        self._snapshot = self.store.snapshot()
        data = self._snapshot
        profile = data.get("profile", {})
        if not self._profile_dirty:
            for key, edit in self.profile_fields.items():
                edit.setText(_text(profile.get(key, "")))
        self.hero_name.setText(_text(profile.get("pet_name")) or "大肥鱼")
        self._refresh_home()
        self._render_memory()
        self._render_growth()
        settings = data.get("settings", {})
        controls = (self.voice_enabled, self.voice_auto, self.volume_slider)
        blockers = [QSignalBlocker(control) for control in controls]
        self.voice_enabled.setChecked(bool(settings.get("voice_enabled", False)))
        self.voice_auto.setChecked(bool(settings.get("voice_auto", False)))
        self.volume_slider.setValue(int(settings.get("voice_volume", 75)))
        self._volume_changed(self.volume_slider.value())
        del blockers
        self._refresh_voices()
        self._render_reminders()

    def _refresh_home(self):
        if not self._snapshot:
            return
        data = self._snapshot
        self.hero_days.setText(f"这是我们相处的第 {max(1, int(data.get('days_together', 1)))} 天")
        self.hero_stage.setText(f"Lv.{data.get('level', 1)} · {data.get('stage', '初次见面')}")
        points = int(data.get("total_points", 0))
        next_points = data.get("next_level_points")
        next_points = int(next_points) if next_points is not None else points
        self.hero_progress.setRange(0, max(1, next_points, points))
        self.hero_progress.setValue(points)
        self.hero_points.setText(f"累计 {points} 点经验 · 今日 {data.get('daily_points', 0)} / 60")
        care = data.get("today_care", {})
        self.today_summary.setText(f"今天：投喂 {care.get('feed', 0)} 次  ·  摸头 {care.get('pat', 0)} 次  ·  陪玩 {care.get('play', 0)} 次")

    def _render_memory(self, *_):
        query = self.memory_search.text().strip().casefold()
        data = self._snapshot
        self.note_list.clear()
        all_notes = data.get("notes", [])
        shown_notes = 0
        for note in all_notes:
            body = _text(note.get("text"))
            if query and query not in body.casefold():
                continue
            item = QListWidgetItem(f"{body}\n手动记住 · {_when(note.get('at'))}")
            item.setData(Qt.ItemDataRole.UserRole, note.get("id"))
            self.note_list.addItem(item)
            shown_notes += 1
        self.memory_count.setText(f"手动记忆 {len(all_notes)} 条" + (f" · 找到 {shown_notes} 条" if query else ""))
        if not shown_notes:
            item = QListWidgetItem("没有找到相关记忆。" if query else "还没有手动记忆，写下第一件想让她记住的事吧。")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.note_list.addItem(item)
        self.timeline_list.clear()
        events = data.get("events", [])
        shown_events = 0
        food_names = {"rice": "白饭", "shrimp": "虾", "cake": "蛋糕", "dango": "团子", "fish": "鱼"}
        for event in events:
            detail = _text(event.get("detail"))
            food = food_names.get(event.get("food"), _text(event.get("food")))
            title = _text(event.get("title")) or {"feed": "投喂", "pat": "摸摸头", "play": "一起玩", "sleep": "好好休息"}.get(event.get("kind"), "一件小事")
            if food and food not in detail and food not in title:
                detail = f"{food} · {detail}".rstrip(" ·")
            text = f"{_when(event.get('at'))}  {title}" + (f"\n{detail}" if detail else "")
            if query and query not in text.casefold():
                continue
            self.timeline_list.addItem(text)
            shown_events += 1
        count = data.get("event_count", len(events))
        self.timeline_count.setText(f"共留下 {count} 条相处记录 · 展示最近 {len(events)} 条" + (f" · 找到 {shown_events} 条" if query else ""))
        if not shown_events:
            self.timeline_list.addItem("没有找到相关记录。" if query else "从今天的一次投喂或摸摸头开始。")

    def _render_growth(self):
        data = self._snapshot
        points = int(data.get("total_points", 0))
        next_points = data.get("next_level_points")
        next_days = data.get("next_level_days")
        at_highest = next_points is None
        next_points = int(next_points) if next_points is not None else points
        self.growth_level.setText(f"Lv.{data.get('level', 1)}  {data.get('stage', '初次见面')}")
        self.growth_total.setText(f"已经一起积攒了 {points} 点经验")
        self.growth_progress.setRange(0, max(1, points, next_points))
        self.growth_progress.setValue(points)
        if at_highest:
            self.growth_next.setText("已经到了当前最高阶段。往后的日子，也会继续写进相处日记。")
        elif next_days is not None:
            days = int(data.get("days_together", 1))
            self.growth_next.setText(f"下一阶段：累计 {next_points} 点，且相处 {next_days} 天\n还差 {max(0, next_points - points)} 点经验、{max(0, int(next_days) - days)} 天陪伴")
        else:
            self.growth_next.setText(f"下一阶段的经验门槛：累计 {next_points} 点 · 还差 {max(0, next_points - points)} 点\n升级还需要相处天数达到要求，慢慢来就好。")
        daily = int(data.get("daily_points", 0))
        self.daily_label.setText(f"{daily} / 60 点")
        self.daily_progress.setValue(min(60, daily))
        level = int(data.get("level", 1))
        for requirement, button in self.ritual_buttons.items():
            unlocked = level >= requirement
            button.setEnabled(unlocked)
            button.setText(button.property("unlockedText") if unlocked else f"Lv.{requirement} 解锁")
        totals = data.get("total_care", {})
        rows = (
            f"相处的第 {max(1, int(data.get('days_together', 1)))} 天 · 从 {_when(data.get('created_at')) or '今天'} 开始",
            f"认真照顾过她 · 投喂 {totals.get('feed', 0)} 次，摸头 {totals.get('pat', 0)} 次，陪玩 {totals.get('play', 0)} 次",
            f"亲手记住的小事 · {len(data.get('notes', []))} 条",
            f"留在日记里的足迹 · {data.get('event_count', len(data.get('events', [])))} 条相处记录",
        )
        for label, text in zip(self.milestone_labels, rows):
            label.setText(text)

    def _profile_edited(self, *_):
        self._profile_dirty = True
        self.profile_status.setText("有尚未保存的修改")

    def _save_profile(self):
        try:
            self.store.update_profile({key: edit.text().strip() for key, edit in self.profile_fields.items()})
            self._profile_dirty = False
            self.refresh()
            self.profile_status.setText("主人档案已保存")
            self.profile_changed.emit()
        except Exception as exc:
            self._error("暂时没有保存成功", exc)

    def _remember(self):
        text = self.note_input.toPlainText().strip()
        if not text:
            self.note_input.setFocus()
            return
        try:
            self.store.remember(text)
            self.note_input.clear()
            self.refresh()
            self.profile_changed.emit()
        except Exception as exc:
            self._error("暂时没有记住", exc)

    def _forget(self):
        item = self.note_list.currentItem()
        if not item or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        try:
            self.store.forget_note(item.data(Qt.ItemDataRole.UserRole))
            self.refresh()
            self.profile_changed.emit()
        except Exception as exc:
            self._error("暂时没有删除成功", exc)

    def _focus(self, minutes: int):
        if minutes > 0 and self._focus_running:
            return
        if minutes == 0 and not self._focus_running:
            return
        self.set_focus_status("正在安静陪伴……" if minutes else "这段专注结束了，休息一下吧。", running=minutes > 0)
        self.focus_requested.emit(minutes)

    def set_focus_status(self, text: str, running: bool = False):
        self._focus_running = bool(running)
        self.focus_status.setText(text)
        self.focus_button.setEnabled(not self._focus_running)
        self.focus_stop_button.setVisible(self._focus_running)

    def _add_reminder(self):
        text = self.reminder_text.text().strip()
        if not text:
            self.reminder_text.setFocus()
            return
        try:
            due = self.reminder_due.dateTime().toPython().astimezone().replace(second=0, microsecond=0).isoformat(timespec="seconds")
            repeat = self.reminder_repeat.currentData()
            if self._editing_reminder_id is None:
                self.store.add_reminder(text, due, repeat)
            else:
                self.store.update_reminder(self._editing_reminder_id, text, due, repeat)
            self._cancel_alarm_edit()
            self.refresh()
        except Exception as exc:
            self._error("暂时没有记下提醒", exc)

    def _render_reminders(self):
        current = self.alarm_list.currentItem()
        selected = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.alarm_list.clear()
        reminders = self._snapshot.get("reminders", [])
        pending = [r for r in reminders if not r.get("done")]
        alarms_enabled = bool(self._snapshot.get("settings", {}).get("alarms_enabled", True))
        self.home_alarm_summary.setText((f"还有 {len(pending)} 个闹钟在等约好的时间。" if pending else "还没有待提醒的闹钟，可以设置一次或重复提醒。") if alarms_enabled else "闹钟提醒已关闭；已保存的闹钟保留，可以随时重新开启。")
        repeat_names = {"once": "一次", "daily": "每天", "weekdays": "工作日"}
        for reminder in reminders:
            state = "已停止 / 完成" if reminder.get("done") else "待提醒"
            text = f"{_when(reminder.get('due_at'))} · {repeat_names.get(reminder.get('repeat', 'once'), '一次')} · {state}\n{_text(reminder.get('text'))}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, reminder.get("id"))
            self.alarm_list.addItem(item)
            if reminder.get("id") == selected:
                self.alarm_list.setCurrentItem(item)
        if not reminders:
            item = QListWidgetItem("暂时没有闹钟，写下第一件想让她提醒的事吧。")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.alarm_list.addItem(item)
        blocker = QSignalBlocker(self.alarm_sound_enabled)
        self.alarm_sound_enabled.setChecked(bool(self._snapshot.get("settings", {}).get("alarm_sound_enabled", True)))
        del blocker
        blocker = QSignalBlocker(self.alarms_enabled)
        self.alarms_enabled.setChecked(alarms_enabled)
        del blocker
        self.alarms_delivery_status.setText("已启用。程序运行时到期提醒；关闭程序或睡眠期间无法准点送达。" if alarms_enabled else "已关闭：不弹窗、不响铃。仍可保存和编辑闹钟；重新开启后，每个过期闹钟最多补提醒一次。")
        self.alarm_list_status.setText(f"{len(pending)} 个启用 · 共 {len(reminders)} 个闹钟。选中后可编辑、完成或删除。")
        self._update_alarm_actions()

    def _update_alarm_actions(self):
        selected = self.alarm_list.currentItem()
        reminder_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        for button in (self.alarm_edit_button, self.alarm_delete_button):
            button.setEnabled(reminder_id is not None)
        active = any(r.get("id") == reminder_id and not r.get("done") for r in self._snapshot.get("reminders", []))
        self.alarm_complete_button.setEnabled(active)

    def _edit_selected_alarm(self):
        item = self.alarm_list.currentItem()
        if not item:
            return
        reminder_id = item.data(Qt.ItemDataRole.UserRole)
        reminder = next((r for r in self._snapshot.get("reminders", []) if r.get("id") == reminder_id), None)
        if not reminder:
            return
        self._editing_reminder_id = reminder_id
        self.reminder_text.setText(_text(reminder["text"]))
        due = datetime.fromisoformat(reminder["due_at"].replace("Z", "+00:00")).astimezone()
        self.reminder_due.setDateTime(QDateTime(due))
        self.reminder_repeat.setCurrentIndex(max(0, self.reminder_repeat.findData(reminder.get("repeat", "once"))))
        self.alarm_edit_status.setText("正在编辑闹钟；保存后会重新启用这项提醒。")
        self.alarm_save_button.setText("保存修改")
        self.alarm_cancel_button.show()
        self.reminder_text.setFocus()

    def _cancel_alarm_edit(self):
        self._editing_reminder_id = None
        self.reminder_text.clear()
        self.reminder_due.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.reminder_repeat.setCurrentIndex(0)
        self.alarm_edit_status.setText("新闹钟")
        self.alarm_save_button.setText("添加闹钟")
        self.alarm_cancel_button.hide()

    def _complete_selected_alarm(self):
        item = self.alarm_list.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole) is not None:
            self._complete_reminder(item.data(Qt.ItemDataRole.UserRole))

    def _delete_selected_alarm(self):
        item = self.alarm_list.currentItem()
        if not item or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        reminder_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.store.delete_reminder(reminder_id)
            if self._editing_reminder_id == reminder_id:
                self._cancel_alarm_edit()
            self.refresh()
        except Exception as exc:
            self._error("暂时没有删除闹钟", exc)

    def _save_alarm_sound(self, enabled: bool):
        try:
            self.store.set_setting("alarm_sound_enabled", bool(enabled))
            self._snapshot.setdefault("settings", {})["alarm_sound_enabled"] = bool(enabled)
            self.settings_changed.emit()
        except Exception as exc:
            blocker = QSignalBlocker(self.alarm_sound_enabled)
            self.alarm_sound_enabled.setChecked(bool(self._snapshot.get("settings", {}).get("alarm_sound_enabled", True)))
            del blocker
            self._error("暂时没有保存闹钟声音设置", exc)

    def _save_alarms_enabled(self, enabled: bool):
        try:
            self.store.set_setting("alarms_enabled", bool(enabled))
            self._snapshot.setdefault("settings", {})["alarms_enabled"] = bool(enabled)
            self._render_reminders()
            self.settings_changed.emit()
        except Exception as exc:
            blocker = QSignalBlocker(self.alarms_enabled)
            self.alarms_enabled.setChecked(bool(self._snapshot.get("settings", {}).get("alarms_enabled", True)))
            del blocker
            self._error("暂时没有保存闹钟总开关", exc)

    def _complete_reminder(self, reminder_id):
        try:
            self.store.complete_reminder(reminder_id)
            if self._editing_reminder_id == reminder_id:
                self._cancel_alarm_edit()
            self.refresh()
        except Exception as exc:
            self._error("暂时没有更新提醒", exc)

    @classmethod
    def _clear_layout(cls, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                cls._clear_layout(item.layout())

    def _refresh_voices(self):
        if hasattr(self, "output_choice"):
            outputs = getattr(self.speech, "outputs", []) or []
            signature = tuple((d.get("id", ""), d.get("name", "")) for d in outputs)
            if getattr(self, "_output_signature", None) != signature:
                self._output_signature = signature
                blocker = QSignalBlocker(self.output_choice)
                self.output_choice.clear()
                self.output_choice.addItem("跟随系统默认输出", "")
                for device in outputs:
                    self.output_choice.addItem(str(device.get("name", "音频设备")), str(device.get("id", "")))
                del blocker
            blocker = QSignalBlocker(self.output_choice)
            chosen = self.output_choice.findData(getattr(self.speech, "selected_output", ""))
            self.output_choice.setCurrentIndex(max(0, chosen))
            del blocker
            name = getattr(self.speech, "output_name", "")
            self.output_status.setText(f"当前输出：{name}" if name else "没有检测到音频输出设备")
        raw = getattr(self.speech, "voices", []) or []
        voices = []
        for voice in raw:
            if isinstance(voice, dict):
                voice_id = _text(voice.get("id", voice.get("voice_id", "")))
                name = _text(voice.get("name", voice_id))
            elif isinstance(voice, (tuple, list)) and len(voice) >= 2:
                voice_id, name = str(voice[0]), str(voice[1])
            else:
                voice_id = _text(getattr(voice, "id", voice))
                name = _text(getattr(voice, "name", voice_id))
            if voice_id:
                voices.append((voice_id, name))
        selected = _text(self._snapshot.get("settings", {}).get("voice_id", ""))
        selected = getattr(self.speech, "voice_id", "") or selected
        self._voice_id = selected or (voices[0][0] if voices else "")
        if hasattr(self, "voice_choice"):
            blocker = QSignalBlocker(self.voice_choice)
            if getattr(self, "_character_signature", None) != tuple(voices):
                self._character_signature = tuple(voices)
                self.voice_choice.clear()
                for voice_id, name in voices:
                    self.voice_choice.addItem(name, voice_id)
            chosen = self.voice_choice.findData(self._voice_id)
            self.voice_choice.setCurrentIndex(max(0, chosen))
            del blocker
        error = _text(getattr(self.speech, "error", ""))
        if error:
            self.voice_status.setText("角色语音暂不可用：" + error)
        elif getattr(self.speech, "available", False):
            self.voice_status.setText("角色语音包已就绪 · 全部在本机播放")
        else:
            self.voice_status.setText("正在准备角色语音包；其他陪伴功能可以正常使用。")

    def _volume_changed(self, value: int):
        self.volume_label.setText(f"{value}%")

    def _choose_output(self):
        output_id = self.output_choice.currentData() or ""
        if hasattr(self.speech, "set_output"):
            self.speech.set_output(output_id)
        self.audio_output_requested.emit(output_id)
        self._refresh_voices()

    def _choose_character_voice(self):
        self._voice_id = self.voice_choice.currentData() or "community"
        self._save_voice()

    def _import_voice_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 ZIP 语音包", "", "ZIP 语音包 (*.zip)")
        if path:
            self.voice_import_requested.emit(path)

    def _import_voice_folder(self):
        path = QFileDialog.getExistingDirectory(self, "导入语音文件夹", "")
        if path:
            self.voice_import_requested.emit(path)

    def set_voice_import_status(self, text: str):
        self.voice_import_status.setText(text)
        self.voice_import_status.setVisible(bool(text))

    def _save_voice(self, *_):
        values = {
            "voice_enabled": self.voice_enabled.isChecked(),
            "voice_auto": self.voice_auto.isChecked(),
            "voice_id": self._voice_id,
            "voice_volume": self.volume_slider.value(),
            "voice_rate": 0,
        }
        try:
            for key, value in values.items():
                self.store.set_setting(key, value)
            self.speech.configure(values["voice_enabled"], voice_id=values["voice_id"], rate=values["voice_rate"], volume=values["voice_volume"], automatic=values["voice_auto"])
            self._snapshot["settings"] = {**self._snapshot.get("settings", {}), **values}
            self.settings_changed.emit()
        except Exception as exc:
            self._error("暂时没有保存语音设置", exc)

    def _preview_voice(self):
        if not self.voice_enabled.isChecked():
            self.voice_enabled.setChecked(True)
        self._save_voice()
        if hasattr(self.speech, "play"):
            caption = self.speech.play("preview", automatic=False)
            if caption:
                self.voice_caption_ready.emit(caption)
        else:
            self.speech.speak("你好，我是大肥鱼。今天也会好好陪着你。")

    def _stop_voice(self):
        self.speech.stop()

    def _export_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出相处备份", f"大肥鱼相处备份-{datetime.now():%Y%m%d}.json", "备份文件 (*.json)")
        if not path:
            return
        try:
            self.store.export_backup(Path(path))
            self.backup_status.setText("备份已导出，可以把它留在你信任的位置。")
        except Exception as exc:
            self._error("备份没有导出成功", exc)

    def _import_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入相处备份", "", "备份文件 (*.json)")
        if not path:
            return
        answer = QMessageBox.question(self, "替换当前记录？", "导入备份会替换当前的档案、记忆和相处记录。建议先导出当前备份。\n\n确定导入吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.import_backup(Path(path))
            self._profile_dirty = False
            self.refresh()
            self._save_voice()
            self.backup_status.setText("备份已恢复，相处记录已更新。")
            self.profile_changed.emit()
        except Exception as exc:
            self._error("备份没有导入成功", exc)

    def _error(self, title: str, exc: Exception):
        QMessageBox.warning(self, title, str(exc))

    def closeEvent(self, event: QCloseEvent):
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)
