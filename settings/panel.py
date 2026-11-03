"""A compact, pet-adjacent control surface with progressive disclosure."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QColor, QKeyEvent, QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class DragHeader(QWidget):
    """A real title-bar drag target without taking input from its close button."""

    def __init__(self, panel: "PetControlPanel") -> None:
        super().__init__(panel)
        self._panel = panel
        self._offset: QPoint | None = None
        self._press_global: QPoint | None = None
        self.setObjectName("dragHeader")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("拖动标题栏，移动外观设置")
        self.setToolTipDuration(20000)
        self.setMinimumHeight(30)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.globalPosition().toPoint()
            self._offset = point - self._panel.frameGeometry().topLeft()
            self._press_global = point
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            point = event.globalPosition().toPoint()
            if point != self._press_global:
                self._panel._drag_to(point - self._offset, point)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = None
            self._press_global = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PetControlPanel(QWidget):
    """Quick interaction first; secondary settings are explicitly revealed."""

    def __init__(
        self,
        *,
        on_mode: Callable[[str], None],
        on_size: Callable[[float], None],
        on_feed: Callable[[], None],
        on_say: Callable[[], None],
        on_snap: Callable[[], None],
        on_awareness: Callable[[bool], None],
        on_read_window_title: Callable[[bool], None],
        on_idle_detection: Callable[[bool], None],
        on_topmost: Callable[[bool], None],
        on_fullscreen_hide: Callable[[bool], None],
        on_passthrough: Callable[[bool], None],
        on_autostart: Callable[[bool], None],
        on_activity_level: Callable[[str], None],
        on_walk_speed: Callable[[float], None],
        on_reduced_motion: Callable[[bool], None],
        on_hover_pause: Callable[[bool], None],
        on_desktop_surfaces: Callable[[bool], None],
        on_action: Callable[[str], None],
        on_hide: Callable[[], None],
        on_privacy: Callable[[], None],
        on_quit: Callable[[], None],
        on_placement: Callable[[str], None] | None = None,
        placement: str = "floating",
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("petControlPanel")
        self.setWindowTitle("大肥鱼 · 外观设置")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(316)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._escape_shortcut.activated.connect(self.close)
        self._mode_buttons: dict[str, QToolButton] = {}
        self._size_buttons: dict[float, QToolButton] = {}
        self._activity_buttons: dict[str, QToolButton] = {}
        self._speed_buttons: dict[float, QToolButton] = {}
        self._placement_buttons: dict[str, QToolButton] = {}
        self._mode_group = QButtonGroup(self)
        self._size_group = QButtonGroup(self)
        self._activity_group = QButtonGroup(self)
        self._speed_group = QButtonGroup(self)
        self._placement_group = QButtonGroup(self)
        for group in (self._mode_group, self._size_group, self._activity_group, self._speed_group, self._placement_group):
            group.setExclusive(True)
        self._expanded = False
        self._pet_rect: QRect | None = None
        self._anchor_point: QPoint | None = None
        self._user_positioned = False

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 8)
        self._root_layout = root
        surface = QFrame()
        surface.setObjectName("controlSurface")
        shadow = QGraphicsDropShadowEffect(surface)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(3, 19, 37, 130))
        surface.setGraphicsEffect(shadow)
        root.addWidget(surface)

        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(14, 13, 14, 13)
        surface_layout.setSpacing(9)
        self._surface_layout = surface_layout

        self.drag_header = DragHeader(self)
        header = QHBoxLayout(self.drag_header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("外观设置")
        title.setObjectName("panelTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(title)
        self.state_label = QLabel("待机")
        self.state_label.setObjectName("stateLabel")
        self.state_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(self.state_label)
        header.addStretch(1)
        close = QToolButton()
        self.close_button = close
        close.setObjectName("closeButton")
        close.setText("×")
        close.setFixedSize(28, 28)
        close.setToolTip("关闭")
        close.setAccessibleName("关闭")
        close.setCursor(Qt.CursorShape.ArrowCursor)
        close.clicked.connect(self.close)
        header.addWidget(close)
        surface_layout.addWidget(self.drag_header)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("controlScroll")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMinimumHeight(0)
        self._body = QWidget()
        self._body.setObjectName("controlBody")
        self._scroll.setWidget(self._body)
        surface_layout.addWidget(self._scroll, 1)
        layout = QVBoxLayout(self._body)
        layout.setContentsMargins(0, 0, 3, 0)
        layout.setSpacing(9)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(5)
        for label, callback in (
            ("投喂", on_feed),
            ("说话", on_say),
            ("开心", lambda: on_action("HAPPY")),
            ("休息", lambda: on_action("SLEEPING")),
        ):
            button = self._quick_button(label)
            button.clicked.connect(callback)
            quick_row.addWidget(button)
        layout.addLayout(quick_row)

        layout.addWidget(self._divider())
        mode_label = QLabel("移动")
        mode_label.setObjectName("compactLabel")
        layout.addWidget(mode_label)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(5)
        for label, value in (("散步", "wander"), ("跟随", "follow"), ("原地", "still")):
            button = self._choice_button(label)
            button.clicked.connect(lambda _checked=False, key=value: on_mode(key))
            self._mode_group.addButton(button)
            self._mode_buttons[value] = button
            mode_row.addWidget(button)
        layout.addLayout(mode_row)
        mode_help = QLabel("散步会自己走动；原地会待着；跟随会靠近鼠标。")
        mode_help.setObjectName("compactHelp")
        mode_help.setWordWrap(True)
        layout.addWidget(mode_help)

        placement_label = QLabel("停留方式")
        placement_label.setObjectName("compactLabel")
        layout.addWidget(placement_label)
        placement_row = QHBoxLayout()
        placement_row.setSpacing(5)
        for label, value in (("悬停原位", "floating"), ("重力落地", "gravity")):
            button = self._choice_button(label)
            button.setProperty("placement", value)
            if on_placement is not None:
                button.clicked.connect(lambda _checked=False, key=value: on_placement(key))
            self._placement_group.addButton(button)
            self._placement_buttons[value] = button
            placement_row.addWidget(button)
        self._placement_buttons.get(placement, self._placement_buttons["floating"]).setChecked(True)
        layout.addLayout(placement_row)
        placement_help = QLabel("悬停保留摆放高度；重力会让她自然落下。")
        placement_help.setObjectName("compactHelp")
        placement_help.setWordWrap(True)
        layout.addWidget(placement_help)

        footer = QHBoxLayout()
        footer.setSpacing(5)
        self.more_button = QToolButton()
        self.more_button.setObjectName("moreButton")
        self.more_button.setText("更多设置")
        self.more_button.clicked.connect(self._toggle_advanced)
        footer.addWidget(self.more_button, 1)
        hide = QToolButton()
        hide.setObjectName("moreButton")
        hide.setText("隐藏")
        hide.clicked.connect(on_hide)
        footer.addWidget(hide)
        layout.addLayout(footer)

        self._advanced = QWidget()
        advanced_layout = QVBoxLayout(self._advanced)
        advanced_layout.setContentsMargins(0, 1, 0, 0)
        advanced_layout.setSpacing(8)
        advanced_layout.addWidget(self._divider())

        size_label = QLabel("大小")
        size_label.setObjectName("compactLabel")
        advanced_layout.addWidget(size_label)
        size_row = QHBoxLayout()
        size_row.setSpacing(5)
        for label, value in (("小", 0.55), ("中", 0.70), ("大", 0.90)):
            button = self._choice_button(label)
            button.clicked.connect(lambda _checked=False, size=value: on_size(size))
            self._size_group.addButton(button)
            self._size_buttons[value] = button
            size_row.addWidget(button)
        advanced_layout.addLayout(size_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(5)
        for label, action in (("发呆", "THINKING"), ("整理", "SWEEPING")):
            button = self._quick_button(label)
            button.clicked.connect(lambda _checked=False, value=action: on_action(value))
            action_row.addWidget(button)
        action_row.addStretch(1)
        advanced_layout.addLayout(action_row)

        rhythm_label = QLabel("陪伴节奏")
        rhythm_label.setObjectName("compactLabel")
        advanced_layout.addWidget(rhythm_label)
        rhythm_row = QHBoxLayout()
        rhythm_row.setSpacing(5)
        for label, value in (("安静", "calm"), ("适中", "balanced"), ("活泼", "lively")):
            button = self._choice_button(label)
            button.clicked.connect(lambda _checked=False, key=value: on_activity_level(key))
            self._activity_group.addButton(button)
            self._activity_buttons[value] = button
            rhythm_row.addWidget(button)
        advanced_layout.addLayout(rhythm_row)

        speed_label = QLabel("走路速度")
        speed_label.setObjectName("compactLabel")
        advanced_layout.addWidget(speed_label)
        speed_row = QHBoxLayout()
        speed_row.setSpacing(5)
        for label, value in (("慢", 64.0), ("适中", 82.0), ("快", 104.0)):
            button = self._choice_button(label)
            button.clicked.connect(lambda _checked=False, speed=value: on_walk_speed(speed))
            self._speed_group.addButton(button)
            self._speed_buttons[value] = button
            speed_row.addWidget(button)
        advanced_layout.addLayout(speed_row)

        self.awareness = self._toggle("本地感知", on_awareness)
        self.topmost = self._toggle("窗口置顶", on_topmost)
        self.read_window_title = self._toggle("读取标题", on_read_window_title)
        self.fullscreen_hide = self._toggle("全屏隐藏", on_fullscreen_hide)
        self.idle_detection = self._toggle("检测空闲", on_idle_detection)
        self.passthrough = self._toggle("鼠标穿透", on_passthrough)
        self.autostart = self._toggle("开机自启", on_autostart)
        self.reduced_motion = self._toggle("减少动态", on_reduced_motion)
        self.hover_pause = self._toggle("悬停暂停", on_hover_pause)
        self.desktop_surfaces = self._toggle("窗口落脚", on_desktop_surfaces)
        toggle_grid = QGridLayout()
        toggle_grid.setHorizontalSpacing(10)
        toggle_grid.setVerticalSpacing(2)
        for index, toggle in enumerate(
            (
                self.awareness,
                self.topmost,
                self.read_window_title,
                self.fullscreen_hide,
                self.idle_detection,
                self.passthrough,
                self.autostart,
                self.reduced_motion,
                self.hover_pause,
                self.desktop_surfaces,
            )
        ):
            toggle_grid.addWidget(toggle, index // 2, index % 2)
        advanced_layout.addLayout(toggle_grid)

        tools = QHBoxLayout()
        tools.setSpacing(5)
        for label, callback, object_name in (
            ("回到主屏", on_snap, "utilityButton"),
            ("隐私", on_privacy, "utilityButton"),
            ("退出", on_quit, "dangerButton"),
        ):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.clicked.connect(callback)
            tools.addWidget(button)
        advanced_layout.addLayout(tools)
        self._advanced.setVisible(False)
        layout.addWidget(self._advanced)

        self.setStyleSheet(
            "#controlSurface{background:#0b2b45;border-radius:14px;}"
            "#panelTitle{color:#f6fbff;font-size:16px;font-weight:700;}"
            "#stateLabel{padding:2px 7px;background:#174767;border-radius:8px;color:#c3e5f7;font-size:10px;font-weight:600;}"
            "QLabel#compactLabel{color:#a8cde4;font-size:10px;font-weight:600;}"
            "QLabel#compactHelp{color:#91b7ce;font-size:10px;}"
            "QScrollArea#controlScroll,QWidget#controlBody{background:transparent;border:0;}"
            "QScrollBar:vertical{background:transparent;width:7px;margin:0;}"
            "QScrollBar::handle:vertical{background:#315f7b;min-height:24px;border-radius:3px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QFrame#divider{background:rgba(184,220,240,38);min-height:1px;max-height:1px;}"
            "QToolButton#quickButton{min-height:31px;padding:0 7px;background:#16415f;border:none;border-radius:9px;"
            "color:#e4f3fb;font-size:11px;font-weight:600;}"
            "QToolButton#quickButton:hover{background:#215779;color:#ffffff;}"
            "QToolButton#choiceButton{min-height:29px;padding:0 8px;background:#123750;border:none;border-radius:8px;"
            "color:#cfe8f6;font-size:11px;font-weight:600;}"
            "QToolButton#choiceButton:hover{background:#1b5275;}"
            "QToolButton#choiceButton:checked{background:#56b9e3;color:#06243a;}"
            "QToolButton#moreButton,QToolButton#closeButton{min-height:28px;padding:0 8px;background:transparent;border:none;"
            "border-radius:8px;color:#a9cfe5;font-size:11px;font-weight:600;}"
            "QToolButton#moreButton:hover,QToolButton#closeButton:hover{background:#173f5d;color:#f7fcff;}"
            "QToolButton#closeButton{padding:0;color:#d7eaf7;font-size:18px;}"
            "QCheckBox{min-height:20px;color:#d9edf8;font-size:11px;spacing:6px;}"
            "QCheckBox::indicator{width:26px;height:14px;border-radius:7px;background:#224b67;}"
            "QCheckBox::indicator:checked{background:#55b9e3;}"
            "QPushButton#utilityButton,QPushButton#dangerButton{min-height:29px;padding:0 8px;border:none;border-radius:8px;"
            "font-size:11px;font-weight:600;}"
            "QPushButton#utilityButton{background:#dff1fb;color:#123750;}"
            "QPushButton#utilityButton:hover{background:#ffffff;}"
            "QPushButton#dangerButton{background:#874457;color:#fff5f6;}"
            "QPushButton#dangerButton:hover{background:#aa566c;}"
        )
        self._configure_tooltips()

    @staticmethod
    def _explain(widget: QWidget, text: str) -> None:
        widget.setToolTip(text)
        widget.setToolTipDuration(20000)

    def _configure_tooltips(self) -> None:
        explanations = {
            self._mode_buttons["wander"]: "按陪伴节奏自主散步。悬停时保留摆放高度，重力模式沿落脚面走动。",
            self._mode_buttons["follow"]: "悬停时会在上下左右靠近鼠标；重力模式沿落脚面横向跟随。",
            self._mode_buttons["still"]: "停在原地做小动作，保留眨眼和互动。重力模式仍会自然下落。",
            self._placement_buttons["floating"]: "拖到喜欢的位置，松手就停住，并切到原地陪伴；仍会做小动作。",
            self._placement_buttons["gravity"]: "松手后自然下落到桌面底部；开启窗口落脚时，也可以落到窗口顶上。",
            self.awareness: "只使用本机的前台程序、窗口等元数据，不读取聊天正文。开启后，标题、空闲和全屏相关选项才会生效。",
            self.read_window_title: "需要先开启本地感知。允许使用前台窗口标题，让小动作更贴近当前情境；可随时取消。",
            self.idle_detection: "需要先开启本地感知。按鼠标键盘的空闲时间调整陪伴状态。",
            self.fullscreen_hide: "需要先开启本地感知。前台程序全屏时暂时隐藏桌宠，退出全屏后恢复。",
            self.topmost: "让桌宠显示在普通窗口上方。取消后，其他窗口可以盖住她。",
            self.passthrough: "鼠标点击会穿过桌宠，不能直接拖动或点击她。可从托盘的“恢复鼠标互动”关闭穿透。",
            self.autostart: "为当前 Windows 用户添加启动快捷方式；取消勾选即可移除。",
            self.reduced_motion: "停用连续动画帧，以静态关键姿势呈现；仍然可以拖动和互动。",
            self.hover_pause: "鼠标放在宠物身上时，暂停自主移动；移开后恢复。",
            self.desktop_surfaces: "重力模式下可以落在窗口顶上并随窗口移动。关闭后会解除当前落脚。",
        }
        for widget, explanation in explanations.items():
            self._explain(widget, explanation)
        for size, button in self._size_buttons.items():
            self._explain(button, f"将桌宠缩放设为 {round(size * 100)}%；可随时切换其他大小。")
        for button in self._activity_buttons.values():
            self._explain(button, "只调整自主活动出现的频次。安静更少活动，活泼更常做小动作。")
        for button in self._speed_buttons.values():
            self._explain(button, "只调整走路和跟随的位移速度；原地模式仍会待在原处。")
        labels = {
            "更多设置": "展开大小、陪伴节奏、移动速度和其他选项；小屏幕可以向下滚动。",
            "回到主屏": "返回主显示器中间并停住；重力模式下仍可继续落下。",
            "隐藏": "暂时隐藏桌宠；可从系统托盘重新显示。",
            "投喂": "打开投喂小卡，给她选一点吃的。",
            "说话": "让她说一句陪伴小台词。",
            "开心": "播放开心的小动作。",
            "休息": "让她安静休息一会儿。",
            "发呆": "看看她认真想事情的小动作。",
            "整理": "播放整理的小动作。",
            "隐私": "查看本地感知和保存内容的说明。",
            "退出": "保存当前状态并退出桌宠；下次打开会继续保留相处记录。",
            "×": "关闭外观设置，回到桌宠。也可以按 Esc。",
        }
        for button in self.findChildren(QToolButton) + self.findChildren(QPushButton):
            if button.text() in labels:
                self._explain(button, labels[button.text()])

    @staticmethod
    def _divider() -> QFrame:
        divider = QFrame()
        divider.setObjectName("divider")
        return divider

    @staticmethod
    def _choice_button(text: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("choiceButton")
        button.setText(text)
        button.setCheckable(True)
        # Each section belongs to its own explicit QButtonGroup. Parent-based
        # autoExclusive must never couple sibling sections or layout changes.
        button.setAutoExclusive(False)
        return button

    @staticmethod
    def _quick_button(text: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("quickButton")
        button.setText(text)
        return button

    @staticmethod
    def _toggle(text: str, callback: Callable[[bool], None]) -> QCheckBox:
        checkbox = QCheckBox(text)
        checkbox.clicked.connect(callback)
        return checkbox

    def _toggle_advanced(self) -> None:
        self._expanded = not self._expanded
        self._advanced.setVisible(self._expanded)
        self.more_button.setText("收起设置" if self._expanded else "更多设置")
        self._explain(self.more_button, "收起次要选项，保留常用互动和移动设置。" if self._expanded else "展开大小、陪伴节奏、移动速度和其他选项；小屏幕可以向下滚动。")
        # Hiding a child queues a layout recalculation.  Resize on the next Qt
        # turn so the compact hint is already current instead of retaining the
        # expanded tool window's old height.
        QTimer.singleShot(0, self._fit_to_content)

    def _fit_to_content(self) -> None:
        self._body.layout().invalidate()
        self._body.layout().activate()
        self._root_layout.invalidate()
        self._root_layout.activate()
        # Keep the header and close button outside the scroll viewport. Expanded
        # controls can exceed a laptop's available height without becoming
        # unreachable or pushing the window under the taskbar.
        chrome_height = self.drag_header.sizeHint().height() + 9 + 26 + 14
        target_height = self._body.sizeHint().height() + chrome_height
        area = self._available_area()
        if area is not None:
            target_height = min(target_height, max(1, area.height() - 12))
        self.setMinimumHeight(0)
        self.setMaximumHeight(target_height)
        self.resize(self.width(), target_height)
        if self._user_positioned:
            if area is not None:
                self.move(self._clamp(self.pos(), area))
        elif self._pet_rect is not None:
            self._move_near_pet(self._pet_rect)
        elif self._anchor_point is not None and area is not None:
            self.move(self._clamp(self._anchor_point + QPoint(12, 12), area))

    def _available_area(self) -> QRect | None:
        if self._user_positioned:
            point = self.drag_header.mapToGlobal(self.drag_header.rect().center())
        else:
            point = self._pet_rect.center() if self._pet_rect is not None else self._anchor_point or self.pos()
        return self._screen_area(point)

    @staticmethod
    def _screen_area(point: QPoint) -> QRect | None:
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _drag_to(self, position: QPoint, pointer: QPoint) -> None:
        area = self._screen_area(pointer)
        self._user_positioned = True
        self.move(self._clamp(position, area) if area is not None else position)

    def sync(
        self,
        *,
        mode: str,
        size: float,
        awareness: bool,
        read_window_title: bool,
        idle_detection: bool,
        topmost: bool,
        fullscreen_hide: bool,
        passthrough: bool,
        autostart: bool,
        activity_level: str,
        walk_speed: float,
        reduced_motion: bool,
        hover_pause: bool,
        desktop_surfaces: bool,
        state_name: str,
        placement: str = "floating",
    ) -> None:
        choices = tuple(self._mode_buttons.values()) + tuple(self._size_buttons.values()) + tuple(self._activity_buttons.values()) + tuple(self._speed_buttons.values()) + tuple(self._placement_buttons.values())
        checkboxes = (self.awareness, self.read_window_title, self.idle_detection, self.topmost, self.fullscreen_hide, self.passthrough, self.autostart, self.reduced_motion, self.hover_pause, self.desktop_surfaces)
        blockers = [QSignalBlocker(control) for control in choices + checkboxes]
        if mode in self._mode_buttons:
            self._mode_buttons[mode].setChecked(True)
        closest_size = min(self._size_buttons, key=lambda value: abs(value - size))
        self._size_buttons[closest_size].setChecked(True)
        if activity_level in self._activity_buttons:
            self._activity_buttons[activity_level].setChecked(True)
        closest_speed = min(self._speed_buttons, key=lambda value: abs(value - walk_speed))
        self._speed_buttons[closest_speed].setChecked(True)
        if placement in self._placement_buttons:
            self._placement_buttons[placement].setChecked(True)
        self.awareness.setChecked(awareness)
        self.read_window_title.setChecked(read_window_title)
        self.idle_detection.setChecked(idle_detection)
        self.topmost.setChecked(topmost)
        self.fullscreen_hide.setChecked(fullscreen_hide)
        self.passthrough.setChecked(passthrough)
        self.autostart.setChecked(autostart)
        self.reduced_motion.setChecked(reduced_motion)
        self.hover_pause.setChecked(hover_pause)
        self.desktop_surfaces.setChecked(desktop_surfaces)
        self.state_label.setText(state_name)
        del blockers

    def popup_near_pet(self, pet_rect: QRect) -> None:
        self._pet_rect = QRect(pet_rect)
        self._anchor_point = None
        self._user_positioned = False
        self._fit_to_content()
        self.show()
        self.raise_()

    def popup_at(self, point: QPoint) -> None:
        """Fallback used from the tray when there is no visible pet anchor."""

        self._pet_rect = None
        self._anchor_point = QPoint(point)
        self._user_positioned = False
        self._fit_to_content()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(self._clamp(QPoint(point.x() + 12, point.y() + 12), area))
        else:
            self.move(point + QPoint(12, 12))
        self.show()
        self.raise_()

    def _move_near_pet(self, pet_rect: QRect) -> None:
        screen = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
        if screen is None:
            self.move(pet_rect.topRight() + QPoint(14, 8))
            return
        area = screen.availableGeometry()
        gap = 14
        aligned_y = pet_rect.top() + max(0, min(24, pet_rect.height() - self.height()))
        centered_x = pet_rect.center().x() - self.width() // 2
        candidates = (
            QPoint(pet_rect.right() + gap, aligned_y),
            QPoint(pet_rect.left() - self.width() - gap, aligned_y),
            QPoint(centered_x, pet_rect.top() - self.height() - gap),
            QPoint(centered_x, pet_rect.bottom() + gap),
        )
        for candidate in candidates:
            rect = QRect(candidate, self.size())
            if area.contains(rect):
                self.move(candidate)
                return

        # On a very small screen, pick the clamped candidate that hides the
        # least of the pet rather than anchoring blindly over its centre.
        def overlap(candidate: QPoint) -> int:
            rect = QRect(self._clamp(candidate, area), self.size())
            intersection = rect.intersected(pet_rect)
            return intersection.width() * intersection.height()

        self.move(min(candidates, key=overlap))
        self.move(self._clamp(self.pos(), area))

    def _clamp(self, point: QPoint, area: QRect) -> QPoint:
        return QPoint(
            min(max(area.left(), point.x()), max(area.left(), area.right() - self.width() + 1)),
            min(max(area.top(), point.y()), max(area.top(), area.bottom() - self.height() + 1)),
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)
