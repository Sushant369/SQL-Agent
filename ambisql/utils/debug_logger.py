import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_ROOT = REPO_ROOT / "logs" / "chatbot_debug"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _sanitize_for_json(value, max_string_length=200000):
    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        if len(value) <= max_string_length:
            return value
        return (
            value[:max_string_length]
            + f"\n[TRUNCATED {len(value) - max_string_length} CHARACTERS]"
        )

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {
            str(key): _sanitize_for_json(item, max_string_length=max_string_length)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_for_json(item, max_string_length=max_string_length)
            for item in value
        ]

    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


class LocalDebugLogger:
    def __init__(self, log_file_path, session_id=None, channel="session"):
        self.log_file_path = Path(log_file_path)
        self.session_id = session_id
        self.channel = channel
        self.current_request_id = None
        self._lock = Lock()
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

    def set_request_id(self, request_id):
        self.current_request_id = request_id

    def clear_request_id(self):
        self.current_request_id = None

    def log_event(self, component, event, payload=None, level="INFO"):
        record = {
            "timestamp_utc": _utc_now_iso(),
            "level": level,
            "channel": self.channel,
            "session_id": self.session_id,
            "request_id": self.current_request_id,
            "component": component,
            "event": event,
            "payload": _sanitize_for_json(payload),
        }
        self._write_record(record)

    def log_exception(self, component, event, exception, payload=None):
        record = {
            "timestamp_utc": _utc_now_iso(),
            "level": "ERROR",
            "channel": self.channel,
            "session_id": self.session_id,
            "request_id": self.current_request_id,
            "component": component,
            "event": event,
            "payload": _sanitize_for_json(payload),
            "error": {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc(),
            },
        }
        self._write_record(record)

    def _write_record(self, record):
        with self._lock:
            with open(self.log_file_path, "a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(record, ensure_ascii=False, default=str))
                log_file.write("\n")


def create_session_debug_logger(session_id, base_dir=None):
    base_dir = Path(base_dir or DEFAULT_LOG_ROOT)
    created_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_dir = base_dir / "sessions" / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file_path = session_dir / f"session_{created_at}_{session_id}.jsonl"
    return LocalDebugLogger(
        log_file_path=log_file_path,
        session_id=session_id,
        channel="session",
    )


def create_system_debug_logger(name="application", base_dir=None):
    base_dir = Path(base_dir or DEFAULT_LOG_ROOT)
    log_file_path = base_dir / "system" / f"{name}.jsonl"
    return LocalDebugLogger(
        log_file_path=log_file_path,
        session_id=None,
        channel="system",
    )
