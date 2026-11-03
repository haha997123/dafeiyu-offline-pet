from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QPushButton, QSystemTrayIcon, QTextEdit, QVBoxLayout

from animation.clip import PetAction
from companion.care_panel import CarePanel
from companion.alarms import AlarmDialog
from companion.hub import CompanionHub
from companion.memory import CompanionStore
from companion.voicepack import VoicePackService
from companion.voicepacks import VoicePackLibrary
from pet.window import PetWindow


class CompanionPetWindow(PetWindow):
    """Connect the animated pet to a completely local companionship journal."""

    def __init__(self, paths, config, *, recovery_status=None):
        self.companion_store = None
        self.speech = None
        self.hub = None
        self.care_panel = None
        self.alarm_dialog = None
        self._closed_companion = False
        self._focus_end = 0.0
        self._focus_minutes = 0
        self._focus_previous_mode = None
        self._manual_voice_at = 0.0
        self._next_ambient_voice_at = time.monotonic() + 90.0
        super().__init__(paths, config, recovery_status=recovery_status)
        self.setWindowTitle("大肥鱼 · 桌面陪伴")
        self.companion_store = CompanionStore(paths.data_dir)
        self.alarm_dialog = AlarmDialog()
        self.alarm_dialog.setWindowIcon(QIcon(str(paths.sprite_dir / "icon.png")))
        self.alarm_dialog.snooze_requested.connect(self._snooze_alarms)
        self.alarm_dialog.acknowledged.connect(self._acknowledge_alarms)
        self.alarm_chime = QSoundEffect(self)
        self.alarm_chime.setSource(QUrl.fromLocalFile(str(paths.assets_dir / "chimes" / "reminder.wav")))
        self.alarm_chime.setVolume(0.45)
        self.voice_library = VoicePackLibrary(paths.data_dir)
        self.speech = VoicePackService(paths.assets_dir / "voicepack", self, library=self.voice_library)
        self.hub = CompanionHub(self.companion_store, self.speech, assets_dir=paths.assets_dir)
        self.hub.setWindowIcon(QIcon(str(paths.sprite_dir / "icon.png")))
        self.hub.interaction_requested.connect(self.interact)
        self.hub.settings_changed.connect(self.apply_companion_settings)
        self.hub.profile_changed.connect(self.on_profile_changed)
        self.hub.focus_requested.connect(self.start_focus)
        self.hub.audio_output_requested.connect(self.set_audio_output)
        self.hub.voice_import_requested.connect(self.import_voice_pack)
        self.hub.voice_caption_ready.connect(lambda text: self.say(text, preserve_action=True))
        self.care_panel = CarePanel()
        self.care_panel.interaction_requested.connect(self.interact)
        self.care_panel.journal_requested.connect(lambda: self.open_hub("memory"))
        self.care_panel.appearance_requested.connect(self._open_control_panel_from_tray)
        self.care_panel.voice_toggled.connect(self.set_character_voice)
        self.care_panel.preview_requested.connect(self.preview_voice)
        self.care_panel.voice_settings_requested.connect(lambda: self.open_hub("settings"))
        self.care_panel.alarms_requested.connect(lambda: self.open_hub("alarms"))
        self.apply_companion_settings()
        self.hub.refresh()
        self.companion_store.record_interaction("visit")
        self._sync_relationship()
        self.companion_timer = QTimer(self)
        self.companion_timer.timeout.connect(self._companion_tick)
        self.companion_timer.start(1000)
        QApplication.instance().aboutToQuit.connect(self.shutdown_companion)
        # Companionship starts with the pet; records and settings stay tucked away.
        if os.environ.get("DAFEIYU_OPEN_JOURNAL") == "1":
            QTimer.singleShot(250, self.open_hub)

    def _create_tray(self):
        self.tray = QSystemTrayIcon(QIcon(str(self.paths.sprite_dir / "icon.png")), self)
        self.tray.setToolTip("大肥鱼 · 桌面陪伴\n双击找到她，右键打开互动")
        menu = QMenu()
        menu.addAction("陪陪大肥鱼", self.open_care_panel)
        menu.addAction("投喂大肥鱼", self._open_food_panel)
        menu.addAction("回忆一件小事", self.recall_memory)
        menu.addSeparator()
        menu.addAction("显示 / 隐藏桌宠", self.toggle_visible)
        menu.addAction("外观设置", self._open_control_panel_from_tray)
        menu.addAction("恢复鼠标互动", lambda: self.set_passthrough(False))
        menu.addAction("记忆小本与设置", self.open_hub)
        menu.addAction("闹钟提醒", lambda: self.open_hub("alarms"))
        menu.addAction("试听角色声音", self.preview_voice)
        menu.addSeparator()
        menu.addAction("退出并保存", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.activate_from_shortcut()

    def open_hub(self, page="memory"):
        if self.hub is None:
            return
        self._interrupt_activity()
        self.hub.refresh()
        self.hub.show_page(page if isinstance(page, str) else "memory")
        self.hub.show()
        self.hub.raise_()
        self.hub.activateWindow()

    def activate_from_shortcut(self):
        super().activate_from_shortcut()
        self.say("我在这里呀。右键可以喂饭、摸摸和翻开记忆小本。")

    def open_care_panel(self):
        if self.care_panel is None:
            return
        self._interrupt_activity()
        self.control_panel.hide()
        self.food_panel.hide()
        self.care_panel.refresh(self.companion_store.snapshot(), voice_ready=self.speech.available)
        self.care_panel.popup_near_pet(self.frameGeometry())

    def contextMenuEvent(self, event):
        self._interrupt_activity()
        self.open_care_panel()
        event.accept()

    def set_character_voice(self, enabled):
        self.companion_store.set_setting("voice_enabled", bool(enabled))
        self.apply_companion_settings()
        if self.care_panel is not None:
            self.care_panel.refresh(self.companion_store.snapshot(), voice_ready=self.speech.available)
        if enabled:
            self.preview_voice()

    def preview_voice(self):
        self.companion_store.set_setting("voice_enabled", True)
        self.apply_companion_settings()
        self._voice_for("preview", manual=True)
        if self.speech.error:
            self.say(self.speech.error)

    def set_audio_output(self, device_id):
        self.config.set("voice_output", str(device_id))
        self.apply_companion_settings()

    def import_voice_pack(self, source):
        from PySide6.QtWidgets import QMessageBox
        try:
            pack = self.voice_library.import_pack(Path(source))
            self.speech.stop()
            self.speech.refresh_packs()
            self.companion_store.set_setting("voice_id", pack["id"])
            self.apply_companion_settings()
            self.hub.refresh()
            self.hub.set_voice_import_status(f"已导入“{pack['name']}”，共 {len(pack['clips'])} 条。点“试听一句”听听看。")
        except (OSError, ValueError) as error:
            self.hub.set_voice_import_status("导入没有完成，原语音包和存档保持不变。")
            QMessageBox.warning(self.hub, "语音包没有导入成功", str(error))

    def _auto_check_updates(self):
        # This personal offline edition must never install the upstream app.
        return

    def _tick_micro_motion(self, now):
        if self.asset_registry.manifest.get("community_animation_pack"):
            return  # Blinks and small gestures already exist in the continuous video frames.
        super()._tick_micro_motion(now)

    def _tick_activity(self, now):
        if ((self.care_panel is not None and self.care_panel.isVisible()) or
                (self.hub is not None and self.hub.isVisible())):
            return
        super()._tick_activity(now)

    def _quiet_now(self):
        if self.companion_store is None:
            return True
        settings = self.companion_store.snapshot()["settings"]
        start, end = settings.get("quiet_start", 23), settings.get("quiet_end", 8)
        hour = datetime.now().hour
        return start != end and ((start <= hour < end) if start < end else (hour >= start or hour < end))

    def apply_companion_settings(self):
        if self.speech is None:
            return
        settings = self.companion_store.snapshot()["settings"]
        if not settings.get("alarms_enabled", True):
            if self.alarm_dialog is not None:
                self.alarm_dialog.dismiss(acknowledge=False)
            self.alarm_chime.stop()
        self.speech.configure(
            enabled=bool(settings.get("voice_enabled", False)) and os.environ.get("DAFEIYU_SILENT") != "1",
            voice_id=str(settings.get("voice_id") or "community"),
            rate=0,
            volume=int(settings.get("voice_volume", 75)),
            automatic=bool(settings.get("voice_auto", False)),
        )
        self.speech.set_output(self.config.get("voice_output", ""))

    def _sync_relationship(self):
        if self.companion_store is None:
            return
        snapshot = self.companion_store.snapshot()
        # The long-term daily-capped system drives the original behaviour too.
        self.pet_state.affinity = min(1.0, 0.36 + 0.075 * snapshot["level"])

    def on_profile_changed(self):
        if self.companion_store is None:
            return
        self.apply_companion_settings()
        self._sync_relationship()
        profile = self.companion_store.snapshot()["profile"]
        name = profile.get("pet_name") or "大肥鱼"
        self.setWindowTitle(f"{name} · 桌面陪伴")
        self.say("档案和记忆已经更新好啦。")

    def say(self, text, *, inner=False, from_activity=False, preserve_action=False):
        if self._focus_end and from_activity:
            return False
        result = super().say(text, inner=inner, from_activity=from_activity, preserve_action=preserve_action)
        if result and self.speech is not None and not inner and not self._quiet_now() and not self._focus_end:
            # Only exact prerecorded lines have audio. Never misread a memory
            # using an unrelated clip or silently fall back to a system voice.
            self.speech.speak(text, automatic=True)
        return result

    def _voice_for(self, categories, *, manual=False):
        if self.speech is None or (not manual and (self._quiet_now() or self._focus_end)):
            return
        if isinstance(categories, str):
            categories = (categories,)
        for category in categories:
            line = self.speech.play(category, automatic=not manual)
            if line:
                # Keep the visible caption exactly equal to the recorded line.
                super().say(line, preserve_action=True)
                return

    def _record(self, kind, *, food="", detail=""):
        if self.companion_store is None:
            return None
        try:
            result = self.companion_store.record_interaction(kind, detail=detail, food=food)
            self._sync_relationship()
            self.state_store.save(self.pet_state)
            if self.hub is not None and self.hub.isVisible():
                self.hub.refresh()
            if result.get("leveled_up"):
                QTimer.singleShot(2200, lambda: self.say("我们又熟悉了一点。这些一起度过的小事，我都存好啦。"))
            return result
        except Exception:
            logging.getLogger(__name__).exception("Could not save companionship interaction")
            self.say("这次记录暂时没存好，请打开相处日记检查存档位置。", preserve_action=True)
            return None

    def on_food(self, food):
        super().on_food(food)
        result = self._record("feed", food=str(food))
        if result:
            lines = {"白饭": "白饭！我就知道今天也有好吃的。", "虾": "这只小虾，是给我的吗？", "蛋糕": "一小口蛋糕，今天也变甜啦。", "团子": "圆圆的团子，和我一样可爱。"}
            self.say(lines.get(str(food), f"是{food}呀，闻起来好香。"), preserve_action=True)
        self._voice_for("feed" if "饭" in str(food) else "thanks", manual=True)

    def _do_click_reaction(self):
        region = self._pending_click_region
        super()._do_click_reaction()
        if region == "head":
            self._record("pat")
            self._voice_for("pat", manual=True)
        elif region in {"body", "tail", "face"}:
            self._voice_for("click", manual=True)

    def _do_long_press_reaction(self):
        previous = self._long_press_handled
        super()._do_long_press_reaction()
        if not previous and self._long_press_handled:
            self._record("pat", detail="轻轻摸了好一会儿头")
            self._voice_for("pat", manual=True)

    def mouseMoveEvent(self, event):
        was_dragging = self.interaction.dragging
        super().mouseMoveEvent(event)
        if not was_dragging and self.interaction.dragging:
            self._voice_for("drag", manual=True)

    def _open_control_panel_from_tray(self):
        if self.care_panel is not None:
            self.care_panel.hide()
        super()._open_control_panel_from_tray()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            for panel in (self.care_panel, self.control_panel, self.food_panel, self.hub):
                if panel is not None:
                    panel.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def interact(self, kind, food=""):
        self.show()
        self._hidden_by_fullscreen = False
        if kind == "say":
            self.preview_voice()
            return
        if kind.startswith("ritual:"):
            self._perform_ritual(kind.partition(":")[2])
            return
        if kind == "feed":
            self.on_food(food or "白饭")
            return
        self._interrupt_activity()
        self.physics.cancel()
        if kind == "pat":
            self.pet_state.pet_head()
            self._request_action(PetAction.HEAD_PAT, reason="diary_pat", force=True)
            self._record("pat")
            self.say("再摸一下嘛……就一下。", preserve_action=True)
            self._voice_for("pat", manual=True)
        elif kind == "play":
            self.pet_state.mood = min(1.0, self.pet_state.mood + 0.055)
            self.pet_state.boredom = max(0.0, self.pet_state.boredom - 0.14)
            self.pet_state.energy = max(0.0, self.pet_state.energy - 0.025)
            self._request_action(PetAction.HAPPY, reason="diary_play", force=True)
            self._record("play")
            self.say("好耶，陪我玩一小会儿！", preserve_action=True)
            self._voice_for("encourage", manual=True)
        elif kind == "sleep":
            if self.speech is not None:
                self.speech.stop()
            self._preview_action("SLEEPING")
            self._record("sleep")
            self.say("先眯一小会儿，等精神好了再陪你。", preserve_action=True)
            self._voice_for("sleep", manual=True)

    def _say_daily_line(self):
        self.recall_memory()

    def recall_memory(self):
        if self.companion_store is not None:
            text = self.companion_store.recall()
            self.say(text if len(text) <= 34 else "我记得这些小事，展开日记给你看。")
            dialog = QDialog(self.hub)
            dialog.setWindowTitle("大肥鱼记得的小事")
            dialog.resize(520, 340)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(24, 24, 24, 20)
            layout.addWidget(QLabel("这些来自你实际留下的相处记录。"))
            view = QTextEdit()
            view.setReadOnly(True)
            view.setPlainText(text)
            layout.addWidget(view, 1)
            close = QPushButton("记得就好")
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            self._recall_dialog = dialog
            dialog.show()

    def _perform_ritual(self, kind):
        rituals = {
            "thought": (2, PetAction.THINKING, "一起分享了一点悄悄心声"),
            "tidy": (3, PetAction.SWEEPING, "一起整理了一下桌面"),
            "goodnight": (4, PetAction.SLEEPING, "一起完成了晚安小仪式"),
        }
        ritual = rituals.get(kind)
        if ritual is None:
            return
        level, action, detail = ritual
        if self.companion_store.snapshot()["level"] < level:
            self.say(f"这个小日常要到 Lv.{level} 才解锁，慢慢相处就好。")
            return
        self._interrupt_activity()
        self.physics.cancel()
        self._request_action(action, reason=f"ritual_{kind}", force=True)
        self._record("play", detail=detail)
        if kind == "thought":
            self.say("那些你让我记住的小事，我有好好收着。", preserve_action=True)
            self._voice_for("think", manual=True)
        elif kind == "tidy":
            self.say("我把这小块地方擦一擦，你也松松肩膀吧。", preserve_action=True)
            self._voice_for("work", manual=True)
        else:
            self.say("今天辛苦啦。明天见，我们的相处记录会留在这里。", preserve_action=True)
            self._voice_for("sleep")

    def _show_startup_recovery_line(self):
        if self._closed_companion:
            return
        if self.companion_store is None:
            super()._show_startup_recovery_line()
            return
        if self.recovery_status.safe_mode or self.recovery_status.unclean_exit:
            super()._show_startup_recovery_line()
            return
        snapshot = self.companion_store.snapshot()
        profile = snapshot["profile"]
        nickname = profile.get("nickname") or profile.get("owner_name") or "你"
        self.say(f"{nickname}，又见面啦。今天是我们相处的第 {snapshot['days_together']} 天。")
        self._voice_for(("greet", "wake"))

    def start_focus(self, minutes):
        minutes = int(minutes)
        if minutes <= 0:
            self._end_focus(completed=False)
            return
        minutes = max(1, min(120, minutes))
        if self._focus_end:
            self._end_focus(completed=False)
        self._focus_minutes = minutes
        self._focus_end = time.monotonic() + minutes * 60
        self._focus_previous_mode = self.movement.mode
        self.movement.set_mode("still")
        if self.speech:
            self.speech.stop()
        self.say(f"一起专注 {minutes} 分钟吧。我会安静等你，结束再提醒。")
        self._update_focus_status()

    def _update_focus_status(self):
        if self.hub is None:
            return
        remaining = max(0, int(self._focus_end - time.monotonic())) if self._focus_end else 0
        label = f"正在专注 · {remaining // 60:02d}:{remaining % 60:02d}" if self._focus_end else "留一段安静相处的时间"
        if hasattr(self.hub, "set_focus_status"):
            self.hub.set_focus_status(label, running=bool(self._focus_end))

    def _end_focus(self, *, completed):
        if not self._focus_end:
            return
        self._focus_end = 0.0
        if self._focus_previous_mode is not None:
            self.movement.set_mode(self.config.get("mode", self._focus_previous_mode))
            self._focus_previous_mode = None
        self._update_focus_status()
        if completed:
            self._record("focus", detail=f"一起完成了 {self._focus_minutes} 分钟专注")
            self.say(f"{self._focus_minutes} 分钟完成啦。伸个懒腰、喝口水吧。")
            self._voice_for(("click", "idle"))
            self.tray.showMessage("大肥鱼 · 专注完成", "已经把这段认真相处的时间记进日记了。", QSystemTrayIcon.MessageIcon.Information, 5000)

    def _companion_tick(self):
        if self.companion_store is None:
            return
        if self._focus_end:
            if time.monotonic() >= self._focus_end:
                self._end_focus(completed=True)
            else:
                self._update_focus_status()
        try:
            reminders = (self.companion_store.due_reminders()
                         if self.companion_store.snapshot()["settings"].get("alarms_enabled", True) else [])
        except Exception:
            logging.getLogger(__name__).exception("Could not load local reminders")
            self.companion_timer.stop()
            self.say("提醒记录暂时读不到了，请先备份日记并重新打开。")
            return
        for reminder in reminders:
            self.say(f"约好的小提醒：{reminder['text']}")
            self.tray.showMessage("大肥鱼提醒你", reminder["text"], QSystemTrayIcon.MessageIcon.Information, 7000)
        if reminders:
            self.alarm_dialog.enqueue(reminders)
            settings = self.companion_store.snapshot()["settings"]
            if (settings.get("alarm_sound_enabled", True) and not self._quiet_now()
                    and os.environ.get("DAFEIYU_SILENT") != "1"):
                self.alarm_chime.play()
            if self.hub.isVisible():
                self.hub.refresh()
        else:
            self._ambient_voice_tick()

    def _ambient_voice_tick(self):
        now = time.monotonic()
        if now < self._next_ambient_voice_at:
            return
        # Automatic speech stays opt-in, sparse, and quiet during sleep/focus.
        self._next_ambient_voice_at = now + random.uniform(90.0, 180.0)
        if (not self.speech.enabled or not self.speech.automatic or self._focus_end
                or self._quiet_now() or not self.isVisible() or self.interaction.active
                or self.action_machine.current not in {PetAction.IDLE, PetAction.WALKING, PetAction.THINKING}
                or any(panel is not None and panel.isVisible()
                       for panel in (self.care_panel, self.control_panel, self.food_panel, self.hub, self.alarm_dialog))):
            return
        self._voice_for(random.choice(("idle", "idle", "lore", "think", "sing")))

    def _snooze_alarms(self, reminders):
        if not reminders:
            return
        try:
            # A snooze is a separate one-shot alarm, preserving recurring times.
            self.companion_store.snooze_reminders(reminders, minutes=5)
        except Exception:
            logging.getLogger(__name__).exception("Could not snooze alarms")
            self.alarm_dialog.status.setText("稍后提醒暂时没存好，请重试。")
            return
        self.alarm_dialog.dismiss()
        self.hub.refresh()

    def _acknowledge_alarms(self, reminders):
        if self._closed_companion:
            return
        for reminder in reminders:
            if reminder.get("repeat", "once") == "once":
                try:
                    self.companion_store.complete_reminder(reminder["id"])
                except Exception:
                    logging.getLogger(__name__).exception("Could not mark a delivered alarm complete")
        if self.hub is not None:
            self.hub.refresh()

    def shutdown_companion(self):
        if self._closed_companion:
            return
        self._closed_companion = True
        for name in ("companion_timer", "persistence_timer", "timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        try:
            self.save_snapshot()
        except Exception:
            logging.getLogger(__name__).exception("Could not save final pet snapshot")
        finally:
            try:
                if self.speech is not None:
                    self.speech.close()
            finally:
                if self.companion_store is not None:
                    self.companion_store.close()
                if self.hub is not None:
                    self.hub.hide()
                if self.care_panel is not None:
                    self.care_panel.hide()
                if self.alarm_dialog is not None:
                    self.alarm_dialog.dismiss(acknowledge=False)
                if hasattr(self, "alarm_chime"):
                    self.alarm_chime.stop()

