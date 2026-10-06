"""Models library: saved model (person) images, reusable across prompts.

Each record points to an existing image under data/uploads/ (the file is not copied or
moved). Deleting a record does not delete the file. Stored in data/models.json.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .paths import PROJECT_ROOT
MODELS_FILE = PROJECT_ROOT / "data" / "models.json"

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_NAME_CHARS = 120
MAX_TAG_CHARS = 40
MAX_TAG_COUNT = 20
MAX_NOTE_CHARS = 1000

_lock = threading.RLock()
_models: list[dict] = []


class ModelsError(ValueError):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _persist_locked() -> None:
    MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODELS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_models, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, MODELS_FILE)


def load() -> None:
    global _models
    with _lock:
        if MODELS_FILE.is_file():
            try:
                raw = json.loads(MODELS_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    _models = [_normalize(m) for m in raw]
                    return
            except json.JSONDecodeError:
                pass
        _models = []


def _normalize(m: dict) -> dict:
    m.setdefault("tags", [])
    m.setdefault("note", "")
    m.setdefault("use_count", 0)
    if not isinstance(m.get("tags"), list):
        m["tags"] = []
    m["tags"] = [str(t)[:MAX_TAG_CHARS] for t in m["tags"][:MAX_TAG_COUNT]]
    m["note"] = str(m.get("note", ""))[:MAX_NOTE_CHARS]
    m["use_count"] = int(m.get("use_count") or 0)
    return m


def _view(m: dict) -> dict:
    """Record with computed `missing` flag (image file no longer exists)."""
    out = dict(m)
    out["missing"] = not Path(m["image"]).is_file()
    return out


def list_models() -> list[dict]:
    with _lock:
        return [_view(m) for m in _models]


def get_model(model_id: str) -> dict | None:
    with _lock:
        for m in _models:
            if m["id"] == model_id:
                return _view(m)
    return None


def _name_exists_locked(name: str, exclude_id: str | None = None) -> bool:
    target = name.casefold()
    return any(m["name"].casefold() == target and m["id"] != exclude_id for m in _models)


def _clean(payload: dict, *, is_create: bool) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ModelsError("name is required")
    if len(name) > MAX_NAME_CHARS:
        raise ModelsError(f"name is too long (max {MAX_NAME_CHARS} chars)")

    image = (payload.get("image") or "").strip()
    if is_create and not image:
        raise ModelsError("image is required")
    if image:
        p = Path(image)
        if p.suffix.lower() not in ALLOWED_EXT:
            raise ModelsError(f"unsupported image type: {p.suffix}")
        if not p.is_file():
            raise ModelsError("image file not found")

    raw_tags = payload.get("tags") or []
    if not isinstance(raw_tags, list):
        raise ModelsError("tags must be a list")
    tags = [str(t).strip()[:MAX_TAG_CHARS] for t in raw_tags if str(t).strip()]
    tags = tags[:MAX_TAG_COUNT]

    note = str(payload.get("note") or "").strip()[:MAX_NOTE_CHARS]
    return {"name": name, "image": image, "tags": tags, "note": note}


def create_model(payload: dict) -> dict:
    data = _clean(payload, is_create=True)
    with _lock:
        if _name_exists_locked(data["name"]):
            raise ModelsError(f"a model named '{data['name']}' already exists")
        now = _now()
        record = {"id": "md_" + uuid.uuid4().hex[:8], **data,
                  "use_count": 0, "created_at": now, "updated_at": now}
        _models.append(record)
        _persist_locked()
    return _view(record)


def update_model(model_id: str, payload: dict) -> dict | None:
    with _lock:
        target = next((m for m in _models if m["id"] == model_id), None)
        if not target:
            return None
        data = _clean({**target, **payload}, is_create=False)
        if data["name"] != target["name"] and _name_exists_locked(data["name"], exclude_id=model_id):
            raise ModelsError(f"a model named '{data['name']}' already exists")
        target.update(data, updated_at=_now())
        _persist_locked()
    return _view(target)


def delete_model(model_id: str) -> bool:
    with _lock:
        for i, m in enumerate(_models):
            if m["id"] == model_id:
                _models.pop(i)
                _persist_locked()
                return True
    return False


def increment_use(image_path: str | None) -> None:
    """Bump use_count of whichever model record points to this image path."""
    if not image_path:
        return
    with _lock:
        for m in _models:
            if m["image"] == image_path:
                m["use_count"] = m.get("use_count", 0) + 1
                _persist_locked()
                return


def find_by_image(image_path: str | None) -> dict | None:
    """Return the model record whose image matches `image_path`, if any."""
    if not image_path:
        return None
    with _lock:
        for m in _models:
            if m["image"] == image_path:
                return _view(m)
    return None


load()