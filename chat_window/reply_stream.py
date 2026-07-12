from dataclasses import dataclass
from typing import Any


@dataclass(eq=False, slots=True)
class ReplyStreamBinding:
    """Binds one LLM stream to the UI objects it is allowed to update."""

    generation: int
    character: str
    worker: Any | None
    bubble: Any | None

    def owns(self, active_stream: object, worker: object, bubble: object) -> bool:
        """Return whether this binding still owns the active response target."""

        return bool(
            self is active_stream
            and self.worker is not None
            and self.worker is worker
            and self.bubble is not None
            and self.bubble is bubble
        )

    def retarget(self, bubble: object) -> None:
        """Move an auto-continued stream to its newly-created message bubble."""

        self.bubble = bubble

    def detach(self) -> None:
        """Release UI and worker references after the stream is no longer active."""

        self.worker = None
        self.bubble = None
