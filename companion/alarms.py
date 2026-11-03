"""Visible local alarm delivery; closing the window acknowledges its contents."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout


class AlarmDialog(QDialog):
    snooze_requested = Signal(object)
    acknowledged = Signal(object)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("大肥鱼 · 到时间啦")
        self.setMinimumSize(380, 260)
        self.resize(430, 300)
        self._pending = []
        self.setStyleSheet(
            'QDialog { background: #f6f8fc; } '
            'QWidget { color: #344864; font-family: "Microsoft YaHei UI"; font-size: 14px; } '
            'QTextEdit { background: white; border: 1px solid #dce5ef; border-radius: 10px; padding: 12px; } '
            'QPushButton { background: #e7f0fb; border: 1px solid #c4d8ef; border-radius: 8px; padding: 9px 12px; } '
            'QPushButton:hover { background: #dceafa; }'
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        self.title = QLabel("约好的时间到啦")
        layout.addWidget(self.title)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        self.status = QLabel("关掉这个窗口也表示收到提醒。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.snooze_button = QPushButton("5 分钟后再提醒")
        self.snooze_button.clicked.connect(lambda: self.snooze_requested.emit(self.pending))
        self.dismiss_button = QPushButton("收到啦")
        self.dismiss_button.clicked.connect(lambda: self.dismiss())
        row.addWidget(self.snooze_button)
        row.addWidget(self.dismiss_button)
        layout.addLayout(row)

    @property
    def pending(self):
        return [dict(item) for item in self._pending]

    def enqueue(self, reminders):
        keys = {(item["id"], item["due_at"]) for item in self._pending}
        for reminder in reminders:
            key = (reminder["id"], reminder["due_at"])
            if key not in keys:
                self._pending.append(dict(reminder))
                keys.add(key)
        if not self._pending:
            return
        self.title.setText(f"约好的时间到啦 · {len(self._pending)} 项提醒")
        self.details.setPlainText("\n\n".join(item["text"] for item in self._pending))
        self.status.setText("关掉这个窗口也表示收到提醒。")
        self.show()
        self.raise_()

    def dismiss(self, *, acknowledge=True):
        if acknowledge and self._pending:
            self.acknowledged.emit(self.pending)
        self._pending.clear()
        self.hide()

    def reject(self):
        self.dismiss()

    def closeEvent(self, event):
        self.dismiss()
        event.accept()
