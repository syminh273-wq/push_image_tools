from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
LOGS_DIR = DATA_DIR / "logs"
PAIRS_FILE = DATA_DIR / "pairs.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory state
_pairs: list[dict] = []
_log_buffers: dict[str, deque[str]] = {}
_log_files: dict[str, Path] = {}
_lock = threading.RLock()

# Debounced persist
_last_save = 0.0
_SAVE_DEBOUNCE = 0.5


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return "p_" + uuid.uuid4().hex[:8]


def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _log_file(pair_id: str) -> Path:
    p = LOGS_DIR / f"{pair_id}.log"
    if pair_id not in _log_files:
        _log_files[pair_id] = p
    return p


def load() -> None:
    """Load pairs.json into memory. Called once at server start."""
    global _pairs
    if PAIRS_FILE.is_file():
        try:
            raw = json.loads(PAIRS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                _pairs = [_migrate(p) for p in raw]
                _fail_orphans()
                return
        except json.JSONDecodeError:
            pass
    _pairs = []


def _migrate(p: dict) -> dict:
    """Pairs saved before the prompt library: image = the model photo, prompt as typed."""
    if "prompt_id" not in p:
        p.setdefault("model_image", p.get("image"))
        p.setdefault("product_image", None)
        p["prompt_id"] = "legacy"
        p["prompt_name"] = "Prompt cũ"
        p["product_name"] = None
        p.pop("use_default_prompt", None)
    return p


def _fail_orphans() -> None:
    """Pairs still 'running' at start-up lost their browser and thread when the server
    stopped; nothing would ever finish them, so mark them failed (Retry runs them again)."""
    orphans = [p for p in _pairs if p.get("status") == "running"]
    for p in orphans:
        p["status"] = "failed"
        p["finished_at"] = _now()
        p["exit_code"] = 1
        try:
            with (LOGS_DIR / f"{p['id']}.log").open("a", encoding="utf-8") as f:
                f.write("[scheduler] server restarted while this pair was running — marked failed\n")
        except OSError:
            pass
    if orphans:
        _persist_locked()


def _persist_locked() -> None:
    """Caller must hold _lock."""
    _atomic_write_json(PAIRS_FILE, _pairs)


def list_pairs() -> list[dict]:
    with _lock:
        return [dict(p) for p in _pairs]


def get_pair(pair_id: str) -> dict | None:
    with _lock:
        for p in _pairs:
            if p["id"] == pair_id:
                return dict(p)
    return None


def add_pair(*, prompt: str, prompt_id: str, prompt_name: str, product_name: str | None,
             model_image: str | None, product_image: str | None, video: str | None,
             video_start: float = 0.0, account: str | None = None,
             timeout: int = 600) -> dict:
    """Queue a job. `prompt` is the final text (product name already filled in), kept as a
    snapshot so editing the prompt library later does not change queued or finished jobs."""
    pair_id = _new_id()
    record = {
        "id": pair_id,
        "prompt_id": prompt_id,
        "prompt_name": prompt_name,
        "product_name": product_name,
        "model_image": model_image,
        "product_image": product_image,
        # First image: thumbnail, output file name and the processes view.
        "image": model_image or product_image,
        "video": video,
        "video_start": float(video_start),
        "prompt": prompt,
        "mode": "account",
        "account": account,
        "email": None,
        "timeout": int(timeout),
        "status": "queued",
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "output": None,
    }
    with _lock:
        _pairs.append(record)
        _persist_locked()
        _log_buffers[pair_id] = deque(maxlen=400)
    return dict(record)


def update_pair(pair_id: str, **fields) -> dict | None:
    allowed = {"prompt", "video_start", "account", "timeout"}
    with _lock:
        for p in _pairs:
            if p["id"] == pair_id:
                for k, v in fields.items():
                    if k in allowed:
                        p[k] = v
                _persist_locked()
                return dict(p)
    return None


def set_status(pair_id: str, status: str, **extra) -> dict | None:
    with _lock:
        for p in _pairs:
            if p["id"] == pair_id:
                p["status"] = status
                for k, v in extra.items():
                    p[k] = v
                if status == "running" and not p.get("started_at"):
                    p["started_at"] = _now()
                if status in ("done", "failed"):
                    p["finished_at"] = _now()
                _persist_locked()
                return dict(p)
    return None


def delete_pair(pair_id: str) -> bool:
    with _lock:
        for i, p in enumerate(_pairs):
            if p["id"] == pair_id:
                if p["status"] == "running":
                    return False
                _pairs.pop(i)
                _persist_locked()
                _log_buffers.pop(pair_id, None)
                _log_files.pop(pair_id, None)
                log_path = LOGS_DIR / f"{pair_id}.log"
                if log_path.exists():
                    try:
                        log_path.unlink()
                    except OSError:
                        pass
                return True
    return False


def _reset_locked(p: dict) -> None:
    p["status"] = "queued"
    p["started_at"] = None
    p["finished_at"] = None
    p["exit_code"] = None
    p["output"] = None
    p["assigned_account"] = None


def retry_pair(pair_id: str) -> dict | None:
    """Reset a failed pair back to queued so it can run again (manual retry: fresh attempts)."""
    with _lock:
        for p in _pairs:
            if p["id"] == pair_id and p["status"] in ("failed", "done"):
                _reset_locked(p)
                p["retry_count"] = 0
                p["abandoned"] = False
                _log_buffers[pair_id] = deque(maxlen=400)
                _persist_locked()
                return dict(p)
    return None


def claim_pair(pair_id: str, account: str) -> dict | None:
    """Atomically take a queued pair for `account` (status -> running). None if already taken."""
    with _lock:
        for p in _pairs:
            if p["id"] == pair_id:
                if p["status"] != "queued" or p.get("abandoned"):
                    return None
                p["status"] = "running"
                p["assigned_account"] = account
                p["started_at"] = _now()
                _persist_locked()
                return dict(p)
    return None


def requeue_pair(pair_id: str, *, count_attempt: bool, max_retries: int) -> dict | None:
    """Put a finished-with-error pair back in the queue.

    count_attempt=False is for account problems (quota / not logged in): the pair itself
    is fine and just moves to another account. Otherwise the attempt counts and the pair
    is abandoned (left failed) after max_retries.
    """
    with _lock:
        for p in _pairs:
            if p["id"] == pair_id:
                if count_attempt:
                    p["retry_count"] = p.get("retry_count", 0) + 1
                    if p["retry_count"] >= max_retries:
                        p["abandoned"] = True
                        _persist_locked()
                        return dict(p)
                _reset_locked(p)
                _persist_locked()
                return dict(p)
    return None


def append_log(pair_id: str, line: str) -> None:
    with _lock:
        buf = _log_buffers.get(pair_id)
        if buf is not None:
            buf.append(line)
        log_path = _log_file(pair_id)
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def get_log(pair_id: str) -> list[str]:
    with _lock:
        buf = _log_buffers.get(pair_id)
        return list(buf) if buf else []


# Initial load when module is imported
load()