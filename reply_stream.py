from dataclasses import dataclass


@dataclass
class ReplyStreamBinding:
    """Owns the UI target for one LLM response stream."""

    generation: int
    character: str
    bubble: object
    worker: object | None = None


def is_active_reply_stream(
    stream: ReplyStreamBinding | None,
    active_stream: ReplyStreamBinding | None,
    worker: object | None,
    bubble: object | None,
) -> bool:
    """Return whether a callback still owns the active response UI."""

    return bool(
        stream is not None
        and stream is active_stream
        and stream.worker is worker
        and stream.bubble is bubble
    )
