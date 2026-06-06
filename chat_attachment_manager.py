import re
from datetime import datetime, timedelta
from pathlib import Path

from process_utils import app_base_dir


_ATTACHMENT_NAME_TIME_RE = re.compile(r"^(?P<stamp>\d{14})-[0-9a-fA-F]+")


def chat_attachment_dir() -> Path:
    return app_base_dir() / "chat_attachments"


def clamp_attachment_retention_days(value) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = 30
    return max(1, min(3650, days))


def attachment_upload_time(path: Path) -> datetime:
    match = _ATTACHMENT_NAME_TIME_RE.match(path.name)
    if match:
        try:
            return datetime.strptime(match.group("stamp"), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    stat = path.stat()
    # A copied file preserves its source mtime, while ctime reflects when the
    # local attachment copy was created on supported platforms.
    return datetime.fromtimestamp(max(stat.st_ctime, stat.st_mtime))


def get_chat_attachment_stats(directory: Path | None = None) -> dict:
    root = Path(directory) if directory is not None else chat_attachment_dir()
    files = []
    total_bytes = 0
    if root.exists():
        for path in root.iterdir():
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
                uploaded_at = attachment_upload_time(path)
            except OSError:
                continue
            files.append((path, uploaded_at))
            total_bytes += size
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "oldest_uploaded_at": min((item[1] for item in files), default=None),
        "newest_uploaded_at": max((item[1] for item in files), default=None),
    }


def cleanup_chat_attachments(
    older_than_days: int | None = None,
    *,
    directory: Path | None = None,
    now: datetime | None = None,
    sanitize_database: bool = True,
) -> dict:
    root = Path(directory) if directory is not None else chat_attachment_dir()
    cutoff = None
    if older_than_days is not None:
        cutoff = (now or datetime.now()) - timedelta(
            days=clamp_attachment_retention_days(older_than_days)
        )

    deleted_files = 0
    deleted_bytes = 0
    failed_files = 0
    if root.exists():
        for path in list(root.iterdir()):
            if not path.is_file():
                continue
            try:
                if cutoff is not None and attachment_upload_time(path) >= cutoff:
                    continue
                size = path.stat().st_size
                path.unlink()
                deleted_files += 1
                deleted_bytes += size
            except OSError:
                failed_files += 1

    removed_references = 0
    if sanitize_database and deleted_files:
        from database_manager import sanitize_chat_attachment_references

        removed_references = sanitize_chat_attachment_references()

    remaining = get_chat_attachment_stats(root)
    return {
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "failed_files": failed_files,
        "removed_references": removed_references,
        "remaining_files": remaining["file_count"],
        "remaining_bytes": remaining["total_bytes"],
    }
