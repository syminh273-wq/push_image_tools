from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR = PROJECT_ROOT / "accounts"
SCREENSHOTS_DIR = PROJECT_ROOT / "screenshots"
DEFAULT_PROMPT_FILE = PROJECT_ROOT / "prompts" / "default.txt"

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
# Media is pasted into the page as base64; keep it to sizes Gemini accepts comfortably.
MAX_VIDEO_BYTES = 100 * 1024 * 1024
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class ValidationError(ValueError):
    pass


def validate_account(name: str) -> str:
    if not _ACCOUNT_RE.match(name):
        raise ValidationError(
            f"Invalid account name {name!r}: use letters, digits, '_' or '-' only."
        )
    return name


def _validate_file(path: str | Path, kind: str, allowed: set[str]) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValidationError(f"{kind} not found: {p}")
    if not p.is_file():
        raise ValidationError(f"{kind} path is not a file: {p}")
    if not os.access(p, os.R_OK):
        raise ValidationError(f"{kind} is not readable: {p}")
    if p.suffix.lower() not in allowed:
        raise ValidationError(
            f"Unsupported {kind.lower()} type {p.suffix!r}: expected one of {', '.join(sorted(allowed))}"
        )
    return p


def validate_image(path: str | Path) -> Path:
    return _validate_file(path, "Image", ALLOWED_IMAGE_EXTENSIONS)


def validate_video(path: str | Path) -> Path:
    p = _validate_file(path, "Video", ALLOWED_VIDEO_EXTENSIONS)
    if p.stat().st_size > MAX_VIDEO_BYTES:
        raise ValidationError(f"Video is larger than {MAX_VIDEO_BYTES // (1024 * 1024)} MB: {p}")
    return p


def default_prompt() -> str:
    """The prompt used when a job does not give one (prompts/default.txt)."""
    if not DEFAULT_PROMPT_FILE.is_file():
        raise ValidationError(f"No prompt given and default prompt file is missing: {DEFAULT_PROMPT_FILE}")
    text = DEFAULT_PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not text:
        raise ValidationError(f"Default prompt file is empty: {DEFAULT_PROMPT_FILE}")
    return text


def resolve_prompt(prompt: str | None, prompt_file: str | Path | None = None) -> str:
    if prompt_file:
        path = Path(prompt_file).expanduser().resolve()
        if not path.is_file():
            raise ValidationError(f"Prompt file not found: {path}")
        prompt = path.read_text(encoding="utf-8")
    if prompt is not None and prompt.strip():
        return prompt.strip()
    return default_prompt()


@dataclass
class Job:
    image: Path
    prompt: str
    output: Path
    video: Path | None = None  # optional reference video (e.g. the dance to follow)
    video_start: float = 0.0  # where to start the 10s clip when the video is longer
    extra_images: list[Path] = field(default_factory=list)  # e.g. the product after the model

    @property
    def files(self) -> list[Path]:
        """Images first (model, then product), the reference video last — the paste order."""
        return [self.image, *self.extra_images]


def load_jobs(jobs_file: str | Path, output_dir: Path) -> list[Job]:
    jobs_path = Path(jobs_file).expanduser().resolve()
    if not jobs_path.is_file():
        raise ValidationError(f"Jobs file not found: {jobs_path}")
    try:
        raw = json.loads(jobs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON in {jobs_path}: {e}") from e
    if not isinstance(raw, list) or not raw:
        raise ValidationError("Jobs file must contain a non-empty JSON array.")

    def local(value: str) -> Path:
        # Relative paths are resolved against the jobs file's directory first, then the cwd.
        p = Path(value).expanduser()
        if not p.is_absolute() and (jobs_path.parent / p).exists():
            p = jobs_path.parent / p
        return p

    jobs: list[Job] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or "image" not in item:
            raise ValidationError(f"Job #{i} must be an object with at least 'image'.")
        image = validate_image(local(item["image"]))
        video = validate_video(local(item["video"])) if item.get("video") else None
        prompt = resolve_prompt(item.get("prompt"),
                                local(item["prompt_file"]) if item.get("prompt_file") else None)
        output = Path(item["output"]) if item.get("output") else output_dir / f"job-{i:02d}-{image.stem}.mp4"
        jobs.append(Job(image=image, prompt=prompt, output=output.expanduser().resolve(), video=video,
                        video_start=float(item.get("video_start", 0))))
    return jobs
