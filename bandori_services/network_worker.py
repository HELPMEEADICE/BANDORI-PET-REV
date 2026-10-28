import threading
import urllib.request

from PySide6.QtCore import QThread, QTimer


def delete_thread_when_stopped(worker, delay_ms: int = 25):
    if worker is None:
        return
    try:
        if worker.isRunning():
            QTimer.singleShot(delay_ms, lambda current=worker: delete_thread_when_stopped(current, delay_ms))
            return
        worker.deleteLater()
    except RuntimeError:
        pass


class CancelableNetworkWorker(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_event = threading.Event()
        self._response_lock = threading.Lock()
        self._active_response = None

    @property
    def cancel_event(self):
        return self._cancel_event

    def requestInterruption(self):
        self._cancel_event.set()
        with self._response_lock:
            response = self._active_response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        super().requestInterruption()

    def cancel(self):
        self.requestInterruption()

    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _track_response(self, response) -> bool:
        with self._response_lock:
            if self.cancelled():
                should_close = True
            else:
                self._active_response = response
                should_close = False
        if should_close:
            try:
                response.close()
            except Exception:
                pass
            return False
        return True

    def _release_response(self, response):
        with self._response_lock:
            if self._active_response is response:
                self._active_response = None

    def open_url(self, request, *args, **kwargs):
        if self.cancelled():
            return None
        response = urllib.request.urlopen(request, *args, **kwargs)
        if not self._track_response(response):
            return None
        return response
