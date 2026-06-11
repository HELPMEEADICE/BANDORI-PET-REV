from PySide6.QtCore import QTimer

from relationship_memory import user_key_from_config


class ChatWindowMixin:
    def _assign_legacy_chat_history(self):
        if not self._cfg or not hasattr(self._cfg, "legacy_chat_user_key"):
            return
        try:
            self._db.assign_legacy_chat_history_user(self._cfg.legacy_chat_user_key())
        except Exception:
            pass

    def _user_memory_key(self) -> str:
        return user_key_from_config(self._cfg)

    def _park_cancelled_worker(self, worker):
        if worker is None:
            return
        self._cancelled_workers.append(worker)
        QTimer.singleShot(1000, self._prune_cancelled_workers)

    def _prune_cancelled_workers(self):
        self._cancelled_workers = [worker for worker in self._cancelled_workers if worker is not None and worker.isRunning()]
