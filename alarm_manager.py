from __future__ import annotations

import json
import logging
import random
from datetime import timedelta

from PySide6.QtCore import QObject, QTimer

_log = logging.getLogger(__name__)

from action_bus import publish_lip_sync
from chat_config_snapshots import memory_extraction_api_config, tts_config_snapshot
from database_manager import DatabaseManager
from desktop_state import desktop_state_payload
from i18n_manager import tr as _tr
from llm_api_compat import chat_completions_api_url
from llm_manager import NonStreamWorker, build_system_prompt, parse_action_tags, strip_action_tags
from relationship_memory import build_relationship_context, user_key_from_config
from reminder_core import (
    ALARM_CONFIG_KEY,
    DISPLAY_MODE_SYSTEM,
    FOCUS_SECONDS,
    LONG_BREAK_SECONDS,
    POMODORO_CONFIG_KEY,
    PROACTIVE_COMPANION_CONFIG_KEY,
    REMINDER_DISPLAY_MODE_KEY,
    SHORT_BREAK_SECONDS,
    compute_next_alarm_at,
    compute_next_proactive_at,
    default_reminder_character,
    isoformat,
    local_now,
    normalize_alarms,
    normalize_display_mode,
    normalize_pomodoros,
    normalize_proactive_companion,
    parse_iso_datetime,
    pomodoro_phase_label,
    repeat_days_label,
)
from screen_awareness import ScreenAwarenessVisionWorker, clamp_screen_awareness_interval
from tts_common import SingleShotTTSCallbacksMixin, strip_tts_action_tags

try:
    from tts_manager import TTSPlayer, TTSRequestWorker
    _TTS_AVAILABLE = True
except (ImportError, OSError):
    _TTS_AVAILABLE = False

    class TTSPlayer(QObject):
        def __init__(self, parent=None):
            super().__init__(parent)

        def stop(self): pass
        def enqueue(self, audio, media_type): pass
        def prepare_lip_sync_text(self, text, language=""): pass

    TTSRequestWorker = None


class ReminderScheduler(SingleShotTTSCallbacksMixin, QObject):
    def __init__(self, config_manager, model_manager, broadcast_event, system_notify, parent=None):
        super().__init__(parent)
        self._cfg = config_manager
        self._model_manager = model_manager
        self._broadcast_event = broadcast_event
        self._system_notify = system_notify
        self._db = DatabaseManager()
        self._workers: list[NonStreamWorker] = []
        self._cancelled_tts_workers = []
        self._tts_worker = None
        self._tts_generation = 0
        self._tts_playing_character = ""
        self._tts_player = TTSPlayer(self) if _TTS_AVAILABLE else None
        if self._tts_player is not None:
            self._tts_player.mouth_pose_changed.connect(self._on_tts_mouth_pose_changed)
            self._tts_player.playback_finished.connect(self._on_tts_playback_finished)
            self._tts_player.error.connect(self._on_tts_error)
        self._pending_contexts: list[dict] = []
        self._text_generation_busy = False
        self._active_worker: NonStreamWorker | None = None
        self._active_context: dict | None = None
        self._watchdog_timer: QTimer | None = None
        self._screen_awareness_worker: ScreenAwarenessVisionWorker | None = None
        self._next_screen_awareness_at = None
        self._timer = QTimer(self)
        self._timer.setInterval(15_000)
        self._timer.timeout.connect(self._tick)
        self.reload()
        self._timer.start()
        QTimer.singleShot(1200, self._tick)

    def reload(self):
        if not self._cfg:
            return
        now = local_now()
        alarms = normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, []), now)
        pomodoros = normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, []), now)
        proactive = normalize_proactive_companion(self._cfg.get(PROACTIVE_COMPANION_CONFIG_KEY, {}), now)
        if (
            alarms != self._cfg.get(ALARM_CONFIG_KEY, [])
            or pomodoros != self._cfg.get(POMODORO_CONFIG_KEY, [])
            or proactive != self._cfg.get(PROACTIVE_COMPANION_CONFIG_KEY, {})
        ):
            self._cfg.set(ALARM_CONFIG_KEY, alarms)
            self._cfg.set(POMODORO_CONFIG_KEY, pomodoros)
            self._cfg.set(PROACTIVE_COMPANION_CONFIG_KEY, proactive)
            self._cfg.save()
        self._schedule_next_screen_awareness()

    def trigger_screen_awareness_now(self) -> bool:
        if not self._screen_awareness_enabled():
            return False
        if self._screen_awareness_worker is not None and self._screen_awareness_worker.isRunning():
            return False
        now = local_now()
        self._schedule_next_screen_awareness(now)
        self._start_screen_awareness_capture(now)
        return True

    def stop(self):
        self._timer.stop()
        self._pending_contexts.clear()
        self._text_generation_busy = False
        self._clear_watchdog()
        for worker in list(self._workers):
            if worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                worker.wait(1000)
        self._workers.clear()
        self._reset_tts()
        if self._screen_awareness_worker is not None and self._screen_awareness_worker.isRunning():
            self._screen_awareness_worker.requestInterruption()
            self._screen_awareness_worker.quit()
            self._screen_awareness_worker.wait(1000)
        self._screen_awareness_worker = None
        for worker in list(self._cancelled_tts_workers):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(1000)
        self._cancelled_tts_workers.clear()
        self._db.close()

    def _tick(self):
        if not self._cfg:
            return
        now = local_now()
        alarms = normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, []), now)
        pomodoros = normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, []), now)
        proactive = normalize_proactive_companion(self._cfg.get(PROACTIVE_COMPANION_CONFIG_KEY, {}), now)
        changed = False

        for alarm in alarms:
            if not alarm.get("enabled"):
                continue
            next_at = parse_iso_datetime(alarm.get("next_at"))
            if next_at is None or next_at > now:
                continue
            self._trigger_alarm(alarm, next_at)
            alarm["last_triggered_at"] = isoformat(now)
            if alarm.get("repeat_days"):
                alarm["next_at"] = isoformat(
                    compute_next_alarm_at(
                        alarm["time"],
                        alarm.get("repeat_days", []),
                        now + timedelta(seconds=30),
                    )
                )
            else:
                alarm["enabled"] = False
                alarm["next_at"] = ""
            changed = True

        for pomodoro in pomodoros:
            if pomodoro.get("status") != "running":
                continue
            next_at = parse_iso_datetime(pomodoro.get("next_at"))
            if next_at is None or next_at > now:
                continue
            self._advance_pomodoro(pomodoro, now)
            changed = True

        if proactive.get("enabled"):
            for item in proactive.get("items", []):
                if not item.get("enabled"):
                    continue
                next_at = parse_iso_datetime(item.get("next_at"))
                if next_at is None or next_at > now:
                    continue
                self._trigger_proactive_item(item, proactive, next_at)
                item["last_triggered_at"] = isoformat(now)
                item["next_at"] = isoformat(compute_next_proactive_at(item, now + timedelta(seconds=30)))
                changed = True

        self._maybe_trigger_screen_awareness(now)

        if changed:
            self._cfg.set(ALARM_CONFIG_KEY, alarms)
            self._cfg.set(POMODORO_CONFIG_KEY, pomodoros)
            self._cfg.set(PROACTIVE_COMPANION_CONFIG_KEY, proactive)
            try:
                self._cfg.save()
            except OSError as exc:
                _log.error("ReminderScheduler tick: failed to persist config: %s", exc)

    def _screen_awareness_enabled(self) -> bool:
        return bool(self._cfg and self._cfg.get("screen_awareness_enabled", False))

    def _screen_awareness_interval(self) -> int:
        return clamp_screen_awareness_interval(self._cfg.get("screen_awareness_interval_minutes", 30) if self._cfg else 30)

    def _schedule_next_screen_awareness(self, now=None) -> bool:
        if not self._screen_awareness_enabled():
            self._next_screen_awareness_at = None
            return False
        base = now or local_now()
        self._next_screen_awareness_at = base + timedelta(minutes=self._screen_awareness_interval())
        return True

    def _maybe_trigger_screen_awareness(self, now):
        if not self._screen_awareness_enabled():
            self._next_screen_awareness_at = None
            return
        if self._screen_awareness_worker is not None and self._screen_awareness_worker.isRunning():
            return
        if self._next_screen_awareness_at is None:
            self._schedule_next_screen_awareness(now)
            return
        if now < self._next_screen_awareness_at:
            return
        self._schedule_next_screen_awareness(now)
        self._start_screen_awareness_capture(now)

    def _start_screen_awareness_capture(self, trigger_now):
        character = self._screen_awareness_character()
        worker = ScreenAwarenessVisionWorker(dict(getattr(self._cfg, "_data", {}) or {}), self)
        self._screen_awareness_worker = worker
        worker.finished.connect(
            lambda summary, metrics, worker=worker, character=character, trigger_now=trigger_now:
                self._on_screen_awareness_finished(worker, character, trigger_now, summary, metrics)
        )
        worker.error.connect(
            lambda message, worker=worker:
                self._on_screen_awareness_error(worker, message)
        )
        worker.start()

    def _on_screen_awareness_finished(self, worker: ScreenAwarenessVisionWorker, character: str, trigger_now, summary: str, metrics: dict):
        if worker is not self._screen_awareness_worker:
            return
        self._screen_awareness_worker = None
        worker.deleteLater()
        summary = str(summary or "").strip()
        if not summary:
            return
        self._start_text_generation({
            "kind": "screen_awareness",
            "title": _tr("Reminder.title_screen_awareness", default="屏幕感知"),
            "notification_title": _tr("Reminder.title_screen_awareness", default="屏幕感知"),
            "character": character,
            "description": _tr("Reminder.screen_awareness_description", default="根据当前屏幕内容判断是否主动搭话。"),
            "screen_observation": summary,
            "screen_metrics": metrics if isinstance(metrics, dict) else {},
            "triggered_at": isoformat(trigger_now),
        })

    def _on_screen_awareness_error(self, worker: ScreenAwarenessVisionWorker, message: str):
        if worker is not self._screen_awareness_worker:
            return
        _log.warning("Screen awareness failed: %s", message)
        self._screen_awareness_worker = None
        worker.deleteLater()

    def _screen_awareness_character(self) -> str:
        mode = str(self._cfg.get("screen_awareness_character_mode", "random_visible") or "random_visible").strip()
        if mode == "fixed":
            return self._reminder_character(self._cfg.get("screen_awareness_character", ""))
        if mode == "default":
            return self._reminder_character("")
        candidates = []
        seen = set()
        models = self._cfg.get("models", []) if self._cfg else []
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                character = str(item.get("character", "") or "").strip()
                if character and character not in seen:
                    candidates.append(character)
                    seen.add(character)
        if candidates:
            return random.choice(candidates)
        return self._reminder_character("")

    def _trigger_alarm(self, alarm: dict, scheduled_at):
        character = self._reminder_character(alarm.get("character", ""))
        title = _tr("Reminder.title_alarm", default="闹钟提醒")
        trigger_now = local_now()
        context = {
            "kind": "alarm",
            "title": title,
            "notification_title": title,
            "character": character,
            "description": alarm.get("description", ""),
            "time": alarm.get("time", ""),
            "scheduled_at": isoformat(scheduled_at),
            "repeat_label": repeat_days_label(alarm.get("repeat_days", [])),
            "triggered_at": isoformat(trigger_now),
        }
        self._start_text_generation(context)

    def _trigger_proactive_item(self, item: dict, proactive: dict, scheduled_at):
        character = self._reminder_character(item.get("character", "") or proactive.get("character", ""))
        proactive_kind = str(item.get("kind") or item.get("id") or "")
        title = _tr(
            f"Reminder.proactive_{proactive_kind}_title",
            default=str(item.get("title") or _tr("Reminder.title_proactive", default="生活节奏提醒")),
        )
        description = _tr(
            f"Reminder.proactive_{proactive_kind}_description",
            default=str(item.get("description", "") or ""),
        )
        trigger_now = local_now()
        context = {
            "kind": "proactive_companion",
            "proactive_kind": proactive_kind,
            "title": title,
            "notification_title": _tr("Reminder.title_proactive", default="生活节奏提醒"),
            "character": character,
            "description": description,
            "scheduled_at": isoformat(scheduled_at),
            "triggered_at": isoformat(trigger_now),
            "schedule_type": item.get("schedule_type", ""),
            "interval_minutes": item.get("interval_minutes", 0),
            "active_start": item.get("active_start", ""),
            "active_end": item.get("active_end", ""),
        }
        self._start_text_generation(context)

    def _advance_pomodoro(self, pomodoro: dict, now):
        character = self._reminder_character(pomodoro.get("character", ""))
        repeat_count = int(pomodoro.get("repeat_count", 1) or 1)
        completed = int(pomodoro.get("completed_focus_count", 0) or 0)
        phase = str(pomodoro.get("phase", "focus") or "focus")
        description = pomodoro.get("description", "")

        if phase == "focus":
            completed += 1
            pomodoro["completed_focus_count"] = completed
            long_break = completed % 4 == 0
            next_phase = "long_break" if long_break else "short_break"
            duration = LONG_BREAK_SECONDS if long_break else SHORT_BREAK_SECONDS
            pomodoro["phase"] = next_phase
            self._start_text_generation({
                "kind": "pomodoro_break",
                "title": _tr("Reminder.title_pomodoro_break", default="番茄钟休息"),
                "notification_title": _tr("Reminder.notification_pomodoro", default="番茄钟提醒"),
                "character": character,
                "description": description,
                "completed": completed,
                "repeat_count": repeat_count,
                "phase": next_phase,
                "is_final_break": completed >= repeat_count,
                "triggered_at": isoformat(now),
            })
        else:
            if completed >= repeat_count:
                pomodoro["status"] = "completed"
                pomodoro["phase"] = "completed"
                pomodoro["phase_started_at"] = isoformat(now)
                pomodoro["phase_duration_sec"] = 0
                pomodoro["next_at"] = ""
                pomodoro["updated_at"] = isoformat(now)
                self._start_text_generation({
                    "kind": "pomodoro_done",
                    "title": _tr("Reminder.title_pomodoro_done", default="番茄钟完成"),
                    "notification_title": _tr("Reminder.notification_pomodoro", default="番茄钟提醒"),
                    "character": character,
                    "description": description,
                    "completed": completed,
                    "repeat_count": repeat_count,
                    "triggered_at": isoformat(now),
                })
                return
            pomodoro["phase"] = "focus"
            duration = FOCUS_SECONDS
            self._start_text_generation({
                "kind": "pomodoro_focus",
                "title": _tr("Reminder.title_pomodoro_focus", default="番茄钟专注"),
                "notification_title": _tr("Reminder.notification_pomodoro", default="番茄钟提醒"),
                "character": character,
                "description": description,
                "completed": completed,
                "repeat_count": repeat_count,
                "phase": "focus",
                "triggered_at": isoformat(now),
            })

        pomodoro["phase_started_at"] = isoformat(now)
        pomodoro["phase_duration_sec"] = duration
        pomodoro["next_at"] = isoformat(now + timedelta(seconds=duration))
        pomodoro["updated_at"] = isoformat(now)

    def _reminder_character(self, character: str) -> str:
        character = str(character or "").strip()
        valid = set()
        models = self._cfg.get("models", []) if self._cfg else []
        if isinstance(models, list):
            valid = {
                str(item.get("character", "") or "").strip()
                for item in models
                if isinstance(item, dict) and str(item.get("character", "") or "").strip()
            }
        if not valid:
            try:
                valid = set(self._model_manager.characters)
            except Exception:
                valid = set()
        if character and valid and character in valid:
            return character
        if character and not valid:
            return character
        return default_reminder_character(self._cfg)

    def _display_name(self, character: str) -> str:
        if not character:
            return "BandoriPet"
        try:
            return self._model_manager.get_display_name(character)
        except Exception:
            return character

    def _api_config(self) -> tuple[str, str, str]:
        return memory_extraction_api_config(
            self._cfg,
            lambda _api_url: False,
            chat_completions_api_url,
        )

    def _start_text_generation(self, context: dict):
        self._pending_contexts.append(dict(context))
        self._drain_pending_contexts()

    def _drain_pending_contexts(self):
        if self._text_generation_busy or not self._pending_contexts:
            return
        self._text_generation_busy = True
        context = self._pending_contexts.pop(0)
        character = context.get("character", "")
        api_url, api_key, model_id = self._api_config()
        if not api_url or not api_key or not model_id:
            if context.get("kind") == "screen_awareness":
                self._text_generation_busy = False
                QTimer.singleShot(500, self._drain_pending_contexts)
                return
            self._show_reminder(context, self._fallback_text(context), "surprised")
            self._text_generation_busy = False
            QTimer.singleShot(500, self._drain_pending_contexts)
            return

        display_name = self._display_name(character)
        relationship = build_relationship_context(
            self._db,
            character,
            user_key_from_config(self._cfg),
            display_name,
        ) if character else ""
        system_prompt = build_system_prompt(character, self._cfg) if character else ""
        instruction = _tr(
            "Reminder.llm_instruction",
            default="你正在为桌宠应用生成闹钟、番茄钟或主动生活节奏陪伴提醒。请严格保持角色口吻，结合好感度、长期记忆、"
                    "当前提醒描述和提醒阶段输出。主动陪伴要自然、短促，像日常关心而不是系统公告。"
                    "如果 payload 中包含 desktop_state，请根据用户正在写代码、看网页、打游戏或发呆/离开的状态调整反应，"
                    "但不要主动复述窗口标题、进程名等隐私细节。"
                    "只输出 1 到 2 句简短中文提醒，不要解释设置过程，不要使用 Markdown。可以在末尾保留一个合适动作标签。",
        )
        if context.get("kind") == "screen_awareness":
            instruction += _tr(
                "Reminder.screen_awareness_llm_instruction",
                default=(
                    "\n如果这是 screen_awareness，请根据 screen_observation 判断是否值得主动开口。"
                    "只有在用户可能卡住、专注太久、切换任务、看起来需要鼓励或有自然搭话点时才说话；"
                    "如果不需要打扰，只输出 NO_SPEAK。不要说自己在截图或监控屏幕。"
                ),
            )
        payload = {
            "reminder": context,
            "character_display_name": display_name,
            "relationship_context": relationship,
        }
        if context.get("screen_observation"):
            payload["screen_observation"] = context.get("screen_observation", "")
            payload["screen_metrics"] = context.get("screen_metrics", {})
        desktop_state = desktop_state_payload(self._cfg)
        if desktop_state:
            payload["desktop_state"] = desktop_state
        messages = [
            {"role": "system", "content": (system_prompt + "\n\n" + instruction).strip()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        worker = NonStreamWorker(api_url, api_key, model_id, messages, self._cfg.get("llm_aux_enable_thinking", None), self)
        self._workers.append(worker)
        worker.finished.connect(
            lambda text, _reasoning, _actions, worker=worker, context=dict(context):
                self._on_text_generated(worker, context, text)
        )
        worker.error.connect(
            lambda _error, worker=worker, context=dict(context):
                self._on_text_generation_failed(worker, context)
        )
        worker.start()
        self._active_worker = worker
        self._active_context = dict(context)
        remaining_ms = self._watchdog_remaining_ms(context)
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setSingleShot(True)
        self._watchdog_timer.timeout.connect(self._on_watchdog_timeout)
        self._watchdog_timer.start(remaining_ms)

    def _watchdog_remaining_ms(self, context: dict) -> int:
        triggered_at = parse_iso_datetime(context.get("triggered_at"))
        if triggered_at is None:
            return 50_000
        elapsed = max(0.0, (local_now() - triggered_at).total_seconds())
        return max(1000, int((50.0 - elapsed) * 1000))

    def _on_watchdog_timeout(self):
        worker = self._active_worker
        if worker is None or not self._text_generation_busy:
            return
        _log.warning("ReminderScheduler: watchdog fired, forcing fallback")
        context = dict(self._active_context) if self._active_context else {}
        if worker.isRunning():
            worker.requestInterruption()
            worker.quit()
            worker.wait(1000)
        self._active_worker = None
        self._active_context = None
        if self._watchdog_timer is not None:
            self._watchdog_timer.stop()
            self._watchdog_timer = None
        self._forget_worker(worker)
        if context.get("kind") != "screen_awareness":
            self._show_reminder(context, self._fallback_text(context), "surprised")
        self._text_generation_busy = False
        QTimer.singleShot(300, self._drain_pending_contexts)

    def _clear_watchdog(self):
        if self._watchdog_timer is not None:
            self._watchdog_timer.stop()
            self._watchdog_timer = None
        self._active_worker = None
        self._active_context = None

    def _on_text_generated(self, worker: NonStreamWorker, context: dict, text: str):
        self._clear_watchdog()
        self._forget_worker(worker)
        actions = parse_action_tags(text)
        clean = strip_action_tags(text).strip()
        if context.get("kind") == "screen_awareness" and clean.upper().strip(" 。.!！") == "NO_SPEAK":
            self._text_generation_busy = False
            QTimer.singleShot(300, self._drain_pending_contexts)
            return
        if not clean:
            clean = self._fallback_text(context)
        if context.get("kind") == "screen_awareness" and clean.upper().strip(" 。.!！") == "NO_SPEAK":
            self._text_generation_busy = False
            QTimer.singleShot(300, self._drain_pending_contexts)
            return
        self._show_reminder(context, clean, actions[0] if actions else "surprised")
        self._text_generation_busy = False
        QTimer.singleShot(300, self._drain_pending_contexts)

    def _on_text_generation_failed(self, worker: NonStreamWorker, context: dict):
        self._clear_watchdog()
        self._forget_worker(worker)
        if context.get("kind") == "screen_awareness":
            self._text_generation_busy = False
            QTimer.singleShot(300, self._drain_pending_contexts)
            return
        self._show_reminder(context, self._fallback_text(context), "surprised")
        self._text_generation_busy = False
        QTimer.singleShot(300, self._drain_pending_contexts)

    def _forget_worker(self, worker: NonStreamWorker):
        self._workers = [item for item in self._workers if item is not worker]
        worker.deleteLater()

    def _fallback_text(self, context: dict) -> str:
        character = context.get("character", "")
        display_name = self._display_name(character)
        description = str(context.get("description", "") or "").strip()
        kind = context.get("kind", "")
        if kind == "alarm":
            purpose = description or _tr("Reminder.fallback_alarm_default_purpose", default="时间到了")
            return _tr("Reminder.fallback_alarm", default="{name}：{purpose}，该准备啦。", name=display_name, purpose=purpose)
        if kind == "pomodoro_break":
            phase = pomodoro_phase_label(context.get("phase", "short_break"))
            purpose = f"\u201c{description}\u201d" if description else _tr("Reminder.fallback_break_default_purpose", default="这轮专注")
            return _tr("Reminder.fallback_break", default="{name}：{purpose}结束了，进入{phase}。", name=display_name, purpose=purpose, phase=phase)
        if kind == "pomodoro_focus":
            purpose = f"\u201c{description}\u201d" if description else _tr("Reminder.fallback_focus_default_purpose", default="下一轮")
            return _tr("Reminder.fallback_focus", default="{name}：休息结束，{purpose}开始专注吧。", name=display_name, purpose=purpose)
        if kind == "pomodoro_done":
            purpose = f"\u201c{description}\u201d" if description else _tr("Reminder.fallback_done_default_purpose", default="番茄钟")
            return _tr("Reminder.fallback_done", default="{name}：{purpose}完成了，辛苦啦。", name=display_name, purpose=purpose)
        if kind == "proactive_companion":
            proactive_kind = str(context.get("proactive_kind") or "")
            if proactive_kind == "desktop_state":
                return self._desktop_state_fallback(context, display_name)
            fallback_key = f"Reminder.fallback_proactive_{proactive_kind}"
            defaults = {
                "morning": "{name}：早上好，今天也慢慢进入状态吧。要不要先想想最重要的一件事？",
                "water": "{name}：先喝点水吧，别等口渴了才想起来。",
                "sedentary": "{name}：坐了有一会儿了，起来伸展一下肩颈和手腕吧。",
                "evening_review": "{name}：今天快收尾了，要不要简单复盘一下完成了什么？",
                "bedtime": "{name}：时间不早了，差不多该把事情放一放准备休息啦。",
                "desktop_state": "{name}：我在旁边留意着，你先按自己的节奏来，需要整理一下当前任务也可以叫我。",
            }
            return _tr(fallback_key, default=defaults.get(proactive_kind, "{name}：来照顾一下现在的生活节奏吧。"), name=display_name)
        if kind == "screen_awareness":
            return "NO_SPEAK"
        return _tr("Reminder.fallback_default", default="{name}：提醒时间到了。", name=display_name)

    def _desktop_state_fallback(self, context: dict, display_name: str) -> str:
        state = desktop_state_payload(self._cfg)
        state_key = str(state.get("state") or "unknown")
        defaults = {
            "coding": "{name}：还在写代码呢。先别急，遇到卡住的地方就停一下整理思路。",
            "web": "{name}：你在看网页呀，别被标签页带跑太远，记得回到原本想查的事。",
            "gaming": "{name}：在打游戏的话就好好享受，不过这一局结束后要不要休息一下眼睛？",
            "idle": "{name}：你安静了一会儿。没关系，发会儿呆也算是在充电。",
            "media": "{name}：在看视频或听音乐的话，放松一下也很好，不过别忘了现在的节奏。",
            "writing": "{name}：还在写东西呢。慢慢来，先把最想表达的那一句放下来。",
        }
        return _tr(
            f"Reminder.fallback_desktop_state_{state_key}",
            default=defaults.get(
                state_key,
                "{name}：我在旁边留意着，你先按自己的节奏来，需要整理一下当前任务也可以叫我。",
            ),
            name=display_name,
        )

    def _show_reminder(self, context: dict, text: str, action: str):
        title = str(context.get("title", "") or "提醒")
        character = str(context.get("character", "") or "").strip()
        display_name = self._display_name(character)
        mode = normalize_display_mode(self._cfg.get(REMINDER_DISPLAY_MODE_KEY, "floating"))
        if mode == DISPLAY_MODE_SYSTEM:
            notification_title = str(context.get("notification_title", "") or title)
            self._system_notify(notification_title, display_name, text)
            self._speak_tts_text(text, character)
            return
        self._broadcast_event({
            "source": "screen_awareness" if context.get("kind") == "screen_awareness" else "reminder",
            "state": "done",
            "mode": "replace_raw",
            "title": display_name,
            "text": text,
            "action": action or "surprised",
            "ttl_ms": 18_000,
            "anchor_to_pet": True,
            "character": character,
        })
        self._speak_tts_text(text, character)

    def _tts_enabled(self) -> bool:
        return bool(_TTS_AVAILABLE and self._cfg and self._cfg.get("tts_enabled", False))

    def _clean_tts_payload(self, text: str, character: str) -> str:
        payload = strip_tts_action_tags(text).strip()
        display_name = self._display_name(character)
        for prefix in (f"【{display_name}】", f"{display_name}：", f"{display_name}:"):
            if payload.startswith(prefix):
                payload = payload[len(prefix):].strip()
                break
        return payload

    def _reset_tts(self):
        self._tts_generation += 1
        worker = self._tts_worker
        self._tts_worker = None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            self._park_cancelled_tts_worker(worker)
        if self._tts_player is not None:
            self._tts_player.stop()
        if self._tts_playing_character:
            publish_lip_sync(self._tts_playing_character, 0.0)
        self._tts_playing_character = ""

    def _speak_tts_text(self, text: str, character: str):
        if not self._tts_enabled() or TTSRequestWorker is None or self._tts_player is None:
            return
        character = self._reminder_character(character)
        payload = self._clean_tts_payload(text, character)
        if not payload:
            return
        self._reset_tts()
        generation = self._tts_generation
        self._tts_playing_character = character
        worker = TTSRequestWorker(0, generation, payload, character, tts_config_snapshot(self._cfg), self)
        self._tts_worker = worker
        worker.audio_ready.connect(self._on_tts_audio_ready)
        worker.error.connect(self._on_tts_error)
        worker.finished.connect(self._on_tts_worker_finished)
        worker.start()

    def _park_cancelled_tts_worker(self, worker):
        if worker is None:
            return
        self._cancelled_tts_workers.append(worker)
        QTimer.singleShot(1000, self._prune_cancelled_tts_workers)

    def _prune_cancelled_tts_workers(self):
        self._cancelled_tts_workers = [
            worker for worker in self._cancelled_tts_workers
            if worker is not None and worker.isRunning()
        ]
