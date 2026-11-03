"""A small transient care card that belongs beside the desktop pet."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)


_STYLE = """
QWidget { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; color: #344864; font-size: 12px; }
QLabel { background: transparent; border: 0; }
QLabel#carePetName { font-size: 20px; font-weight: 700; color: #345785; }
QLabel#careRelationship { font-size: 11px; color: #7b899a; }
QLabel#carePrompt { font-size: 12px; color: #667c96; }
QPushButton { background: #f1f6fc; border: 1px solid #e0e9f4; border-radius: 9px; color: #456488; padding: 5px 9px; }
QPushButton:hover { background: #e7f0fb; border-color: #c4d8ef; }
QPushButton:pressed { background: #dceafa; }
QPushButton:disabled { color: #a2aebb; background: #f3f5f8; border-color: #e9edf2; }
QPushButton[careFood="true"] { background: #fffdf7; border-color: #eee8dc; color: #78684b; font-size: 14px; font-weight: 600; }
QPushButton[careFood="true"]:hover { background: #fff5de; border-color: #e4d4ad; }
QPushButton[careFood="true"]:pressed { background: #f8ebcd; }
QPushButton[careAction="true"] { font-size: 12px; font-weight: 600; }
QPushButton[careQuiet="true"] { background: transparent; border: 0; color: #7e8b9c; padding: 4px 7px; }
QPushButton[careQuiet="true"]:hover { background: #eef3fa; color: #456488; }
QPushButton#careVoice[voiceOn="true"] { color: #426e8d; background: #e8f3f6; border-color: #d1e6ec; }
QPushButton#careClose { background: #edf3f9; border: 0; border-radius: 12px; padding: 0; font-size: 18px; color: #6b7d94; }
QPushButton#careClose:hover { background: #dee9f6; color: #385b86; }
QFrame#careDivider { background: #e9edf3; border: 0; max-height: 1px; min-height: 1px; }
"""


class CarePanel(QWidget):
    interaction_requested = Signal(str, str)
    journal_requested = Signal()
    appearance_requested = Signal()
    voice_toggled = Signal(bool)
    preview_requested = Signal()
    voice_settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("carePanel")
        self.setWindowTitle("陪陪大肥鱼")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self.setStyleSheet(_STYLE)
        self.setFixedSize(324, 378)
        self._voice_on = False
        self._voice_ready = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 19, 20, 17)
        layout.setSpacing(0)

        self.pet_name = QLabel("大肥鱼")
        self.pet_name.setObjectName("carePetName")
        self.pet_name.setTextFormat(Qt.TextFormat.PlainText)
        self.pet_name.setMaximumWidth(244)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self.pet_name, 1)
        self.close_button = self._button("×", "careClose")
        self.close_button.setAccessibleName("关闭互动卡片")
        self.close_button.setToolTip("关闭 · Esc")
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(3)
        self.relationship = QLabel("相处第 1 天 · 初次见面")
        self.relationship.setObjectName("careRelationship")
        self.relationship.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.relationship)
        layout.addSpacing(17)

        prompt = QLabel("想吃一点什么？")
        prompt.setObjectName("carePrompt")
        layout.addWidget(prompt)
        layout.addSpacing(8)
        food_grid = QGridLayout()
        food_grid.setSpacing(8)
        self.food_buttons = {}
        for index, (food, name) in enumerate((("白饭", "rice"), ("虾", "shrimp"), ("蛋糕", "cake"), ("团子", "dango"))):
            button = self._button(food, f"careFood_{name}")
            button.setProperty("careFood", True)
            button.setFixedHeight(42)
            button.clicked.connect(lambda checked=False, value=food: self._interact("feed", value))
            self.food_buttons[food] = button
            food_grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(food_grid)
        layout.addSpacing(11)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.action_buttons = {}
        for label, kind in (("摸摸", "pat"), ("陪玩", "play"), ("睡觉", "sleep")):
            button = self._button(label, f"careAction_{kind}")
            button.setProperty("careAction", True)
            button.setFixedHeight(34)
            button.clicked.connect(lambda checked=False, value=kind: self._interact(value))
            self.action_buttons[kind] = button
            actions.addWidget(button, 1)
        layout.addLayout(actions)
        layout.addSpacing(14)

        divider = QFrame()
        divider.setObjectName("careDivider")
        layout.addWidget(divider)
        layout.addSpacing(11)
        links = QHBoxLayout()
        links.setSpacing(8)
        self.journal_button = self._button("记忆小本", "careJournal")
        self.journal_button.setFixedHeight(30)
        self.journal_button.clicked.connect(self._open_journal)
        self.appearance_button = self._button("外观设置", "careAppearance")
        self.appearance_button.setFixedHeight(30)
        self.appearance_button.clicked.connect(self._open_appearance)
        links.addWidget(self.journal_button, 1)
        links.addWidget(self.appearance_button, 1)
        layout.addLayout(links)
        layout.addSpacing(7)

        bottom = QHBoxLayout()
        bottom.setSpacing(5)
        self.voice_button = self._button("声音 关", "careVoice")
        self.voice_button.setFixedHeight(28)
        self.voice_button.clicked.connect(self._toggle_voice)
        self.preview_button = self._button("试听", "carePreview")
        self.preview_button.setProperty("careQuiet", True)
        self.preview_button.setFixedHeight(28)
        self.preview_button.clicked.connect(self.preview_requested)
        self.voice_settings_button = self._button("音色", "careVoiceSettings")
        self.voice_settings_button.setProperty("careQuiet", True)
        self.voice_settings_button.setFixedHeight(28)
        self.voice_settings_button.setToolTip("切换角色音色，或试听不同声音")
        self.voice_settings_button.clicked.connect(self._open_voice_settings)
        self.hide_button = self._button("收起", "careHide")
        self.hide_button.setProperty("careQuiet", True)
        self.hide_button.setFixedHeight(28)
        self.hide_button.clicked.connect(self.hide)
        bottom.addWidget(self.voice_button)
        bottom.addWidget(self.preview_button)
        bottom.addWidget(self.voice_settings_button)
        bottom.addStretch(1)
        bottom.addWidget(self.hide_button)
        layout.addLayout(bottom)
        layout.addStretch(1)
        self.refresh({})

    @staticmethod
    def _button(text: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return button

    def refresh(self, snapshot: dict, voice_ready: bool = True):
        profile = snapshot.get("profile", {})
        name = str(profile.get("pet_name") or "大肥鱼")
        metrics = self.pet_name.fontMetrics()
        self.pet_name.setText(metrics.elidedText(name, Qt.TextElideMode.ElideRight, 244))
        self.pet_name.setToolTip(name)
        days = max(1, int(snapshot.get("days_together", 1)))
        stage = str(snapshot.get("stage") or "初次见面")
        relationship = f"相处第 {days} 天 · {stage}"
        self.relationship.setText(self.relationship.fontMetrics().elidedText(relationship, Qt.TextElideMode.ElideRight, 280))
        self.relationship.setToolTip(relationship)
        self.setWindowTitle(f"陪陪{name}")
        self._voice_on = bool(snapshot.get("settings", {}).get("voice_enabled", False))
        self._voice_ready = bool(voice_ready)
        self._update_voice_button()

    def _update_voice_button(self):
        self.voice_button.setText("声音 开" if self._voice_on else "声音 关")
        self.voice_button.setProperty("voiceOn", self._voice_on)
        self.voice_button.setEnabled(self._voice_ready)
        self.preview_button.setEnabled(self._voice_ready)
        hint = "播放大肥鱼的角色语音" if self._voice_ready else "角色语音正在准备，其他互动可以照常使用"
        self.voice_button.setToolTip(hint)
        self.preview_button.setToolTip(hint)
        self.voice_button.style().unpolish(self.voice_button)
        self.voice_button.style().polish(self.voice_button)

    def _interact(self, kind: str, food: str = ""):
        self.hide()
        self.interaction_requested.emit(kind, food)

    def _open_journal(self):
        self.hide()
        self.journal_requested.emit()

    def _open_appearance(self):
        self.hide()
        self.appearance_requested.emit()

    def _open_voice_settings(self):
        self.hide()
        self.voice_settings_requested.emit()

    def _toggle_voice(self):
        self._voice_on = not self._voice_on
        self._update_voice_button()
        self.voice_toggled.emit(self._voice_on)

    @staticmethod
    def _position_for(pet_rect: QRect, available: QRect, panel_size: QSize) -> QPoint:
        """Prefer beside the pet, then above it, and clamp to the chosen screen."""
        width, height = panel_size.width(), panel_size.height()
        gap = 12
        mid_y = pet_rect.center().y() - height // 2
        above_y = pet_rect.top() - height - gap
        candidates = (
            QPoint(pet_rect.left() - width - gap, mid_y),
            QPoint(pet_rect.center().x() - width // 2, above_y),
            QPoint(pet_rect.right() + gap + 1, mid_y),
            QPoint(pet_rect.center().x() - width // 2, pet_rect.bottom() + gap + 1),
        )
        # Each preference only needs room in its main direction: the other
        # coordinate can be adjusted near a screen edge without losing context.
        chosen = candidates[0]
        if chosen.x() < available.left():
            if above_y >= available.top():
                chosen = candidates[1]
            elif candidates[2].x() + width <= available.right() + 1:
                chosen = candidates[2]
            else:
                chosen = candidates[3]
        max_x = max(available.left(), available.right() - width + 1)
        max_y = max(available.top(), available.bottom() - height + 1)
        return QPoint(min(max_x, max(available.left(), chosen.x())), min(max_y, max(available.top(), chosen.y())))

    def popup_near_pet(self, pet_rect: QRect):
        screen = QApplication.screenAt(pet_rect.center()) or QApplication.primaryScreen()
        if screen is None:
            self.move(pet_rect.topLeft())
        else:
            available = screen.availableGeometry()
            self.move(self._position_for(pet_rect, available, self.size()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.food_buttons["白饭"].setFocus(Qt.FocusReason.PopupFocusReason)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#dce5ef"), 1))
        painter.setBrush(QColor("#fffefa"))
        painter.drawRoundedRect(rect, 18, 18)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)
