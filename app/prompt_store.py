"""Prompt library: one self-contained prompt per ad type (clothes, cosmetics, bag, dance...).

Each prompt says which files it needs (model image, product image, reference video) and may
contain the single variable {{product_name}}. Stored in data/prompts.json; seeded on first run.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .models import DEFAULT_PROMPT_FILE

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_FILE = PROJECT_ROOT / "data" / "prompts.json"
RULES_FILE = PROJECT_ROOT / "data" / "system_rules.json"

PRODUCT_VAR = "{{product_name}}"
CATEGORIES = ("clothes", "cosmetics", "bag", "shoes", "dance", "food", "other")
INPUT_KEYS = ("model_image", "product_image", "ref_video")
MAX_PROMPT_CHARS = 8000

_lock = threading.RLock()
_prompts: list[dict] = []
_rules: dict = {}

RULE_KEYS = ("general", "product", "person")
MAX_RULE_CHARS = 4000

# System rules: appended to every prompt (unless the prompt opts out) to cut the usual video-model
# failures — products vanishing or morphing mid-turn, cuts, extra limbs. "product" applies only to
# prompts with a product image, "person" only to prompts with a model image.
DEFAULT_RULES = {
    "enabled": True,
    "general": """- One continuous shot from start to end: no cuts, no scene changes, no transitions, no fades.
- Slow, smooth, steady motion only; nothing moves fast or jerks.
- Every object visible in the first frame stays visible and unchanged until the last frame:
  nothing appears, disappears, duplicates, merges, melts or changes shape.
- Same background, lighting and colors for the whole video; no flicker, no sudden exposure changes.
- Do not add text, captions, subtitles, logos or watermarks.""",
    "product": """- The product from the reference image is the hero: it stays fully inside the frame, in sharp
  focus and clearly visible in EVERY frame.
- Never hide, crop, cover or block the product (no hands, hair, props or camera angles in front of it).
- The product keeps the exact shape, size, proportions, color, material, texture, logo, printed text
  and small details of the reference image in every frame. Parts such as straps, handles, chains,
  buckles, zippers, caps, labels and soles must never vanish, bend, melt or be redrawn.
- If the product rotates, it turns slowly and evenly (about 10 seconds for a full turn); its sides and
  back stay consistent with the front, with no warping during the turn.
- The camera keeps a distance where the whole product fits in frame; at most one gentle push-in at
  the end, never an extreme close-up that cuts parts off.""",
    "person": """- The person keeps the same face, hairstyle, skin tone, body and clothes in every frame:
  no face morphing, no identity change, no outfit change.
- Natural anatomy at all times: exactly two arms, two hands with five fingers each, two legs;
  no extra, missing, merged or deformed limbs.
- The person's whole body (or the part being shown) stays inside the frame; no fast spins.
- When holding or wearing the product, the grip stays consistent: the product does not pass through
  the body, float, or jump between hands.""",
}


class PromptError(ValueError):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


_QUALITY = """QUALITY:
Photorealistic commercial video, natural lighting, realistic physics, sharp product details.
Avoid: distorted product, wrong logo or text, changed colors, extra limbs, deformed hands,
duplicated objects, flickering, sudden scene changes, watermarks, on-screen text."""


def _seed() -> list[dict]:
    dance = (DEFAULT_PROMPT_FILE.read_text(encoding="utf-8").strip()
             if DEFAULT_PROMPT_FILE.is_file() else "Animate the person dancing naturally.")
    items = [
        ("dance", "Nhảy – theo video mẫu", dict(model_image=True, ref_video=True), dance),
        ("clothes", "Quần áo – người mẫu trình diễn", dict(model_image=True), f"""Create a fashion advertisement video for the outfit "{PRODUCT_VAR}".
The person in the provided image is the model; keep the exact same face, hairstyle, body and outfit.
The outfit must look EXACTLY like in the image: same cut, fabric, colors, patterns and details.
ACTION: the model walks toward the camera like on a runway, turns slowly, poses to show the outfit,
touches the fabric lightly to show its texture.
CAMERA: full-body shot, smooth tracking, ends with a medium shot highlighting the outfit details.
SCENE: clean bright studio with soft light, minimal background.
{_QUALITY}"""),
        ("bag", "Túi xách – người mẫu cầm túi", dict(model_image=True, product_image=True), f"""Create a luxury handbag advertisement video for "{PRODUCT_VAR}".
The person in the FIRST image is the model; keep the exact same face, hairstyle, body and clothes.
The handbag in the SECOND image is the product; it must look EXACTLY the same: shape, size, color,
material, logo, stitching and metal hardware.
ACTION: the model walks confidently on a city street holding the handbag, stops, lifts the bag
slightly and smiles.
CAMERA: medium shot following the model, ends with a slow push-in close-up on the handbag.
{_QUALITY}"""),
        ("bag", "Túi xách – xoay 360° studio", dict(product_image=True), f"""Create a product showcase video for the handbag "{PRODUCT_VAR}".
The handbag in the provided image is the product; it must look EXACTLY the same: shape, color,
material, logo, stitching and hardware. No people.
ACTION: the handbag slowly rotates 360 degrees on a round pedestal.
SCENE: premium studio, soft gradient background, gentle rim light, subtle reflections on the floor.
CAMERA: static, slight slow push-in at the end on the logo and texture.
{_QUALITY}"""),
        ("cosmetics", "Mỹ phẩm – cận cảnh sản phẩm", dict(product_image=True), f"""Create a premium cosmetics advertisement video for "{PRODUCT_VAR}".
The product in the provided image must look EXACTLY the same: packaging shape, color, label text and logo.
No people.
ACTION: the product stands on a wet glossy surface, water droplets and soft petals fall around it,
a gentle splash of water, light reflections glide across the packaging.
CAMERA: macro close-up, slow orbit around the product, ends front-facing on the label.
SCENE: elegant pastel background, soft diffused lighting.
{_QUALITY}"""),
        ("shoes", "Giày – cận cảnh bước đi", dict(model_image=True, product_image=True), f"""Create a footwear advertisement video for "{PRODUCT_VAR}".
The person in the FIRST image is the model; keep the same face, body and clothes.
The shoes in the SECOND image are the product; they must look EXACTLY the same: shape, colors,
sole, laces and logo.
ACTION: the model wears the shoes and walks on a clean urban sidewalk, steps over a small puddle.
CAMERA: starts with a low-angle close-up on the shoes while walking, then tilts up to a full-body shot.
{_QUALITY}"""),
    ]
    now = _now()
    return [{
        "id": "pr_" + uuid.uuid4().hex[:8],
        "name": name,
        "category": cat,
        "content": content,
        "inputs": {k: bool(inputs.get(k)) for k in INPUT_KEYS},
        "created_at": now,
        "updated_at": now,
    } for cat, name, inputs, content in items]


def _persist_locked() -> None:
    PROMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROMPTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_prompts, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, PROMPTS_FILE)


def load() -> None:
    global _prompts
    with _lock:
        if PROMPTS_FILE.is_file():
            try:
                raw = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    _prompts = raw
                    return
            except json.JSONDecodeError:
                pass
        _prompts = _seed()
        _persist_locked()


def _persist_rules_locked() -> None:
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RULES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_rules, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, RULES_FILE)


def load_rules() -> None:
    global _rules
    with _lock:
        if RULES_FILE.is_file():
            try:
                raw = json.loads(RULES_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _rules = {**DEFAULT_RULES, **raw}
                    return
            except json.JSONDecodeError:
                pass
        _rules = dict(DEFAULT_RULES)
        _persist_rules_locked()


def get_rules() -> dict:
    with _lock:
        return {**_rules, "defaults": {k: DEFAULT_RULES[k] for k in RULE_KEYS}}


def set_rules(payload: dict) -> dict:
    data = {"enabled": bool(payload.get("enabled", True))}
    for k in RULE_KEYS:
        text = (payload.get(k) or "").strip()
        if len(text) > MAX_RULE_CHARS:
            raise PromptError(f"{k} rules are too long (max {MAX_RULE_CHARS} chars)")
        data[k] = text
    global _rules
    with _lock:
        _rules = data
        _persist_rules_locked()
    return get_rules()


def rules_for(prompt: dict) -> str:
    """The rule block appended to this prompt ('' if rules are off for it)."""
    with _lock:
        rules = dict(_rules)
    if not rules.get("enabled") or not prompt.get("use_rules", True):
        return ""
    inputs = prompt.get("inputs", {})
    parts = [rules.get("general", "")]
    if inputs.get("product_image"):
        parts.append(rules.get("product", ""))
    if inputs.get("model_image"):
        parts.append(rules.get("person", ""))
    body = "\n".join(x for x in parts if x.strip())
    return f"STRICT CONSISTENCY RULES (must be followed in every frame):\n{body}" if body else ""


def needs_product_name(prompt: dict) -> bool:
    return PRODUCT_VAR in prompt.get("content", "")


def _view(p: dict) -> dict:
    return {**p, "use_rules": p.get("use_rules", True), "needs_product_name": needs_product_name(p)}


def list_prompts() -> list[dict]:
    with _lock:
        return [_view(p) for p in _prompts]


def get_prompt(prompt_id: str) -> dict | None:
    with _lock:
        return next((_view(p) for p in _prompts if p["id"] == prompt_id), None)


def _clean(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    content = (payload.get("content") or "").strip()
    category = payload.get("category") or "other"
    raw_inputs = payload.get("inputs") or {}
    inputs = {k: bool(raw_inputs.get(k)) for k in INPUT_KEYS}
    if not name:
        raise PromptError("name is required")
    if len(name) > 120:
        raise PromptError("name is too long (max 120 chars)")
    if not content:
        raise PromptError("prompt content is required")
    if len(content) > MAX_PROMPT_CHARS:
        raise PromptError(f"prompt is too long (max {MAX_PROMPT_CHARS} chars)")
    if category not in CATEGORIES:
        raise PromptError(f"invalid category: {category}")
    if not (inputs["model_image"] or inputs["product_image"]):
        raise PromptError("a prompt needs at least one image (model or product)")
    return {"name": name, "content": content, "category": category, "inputs": inputs,
            "use_rules": bool(payload.get("use_rules", True))}


def create_prompt(payload: dict) -> dict:
    data = _clean(payload)
    now = _now()
    record = {"id": "pr_" + uuid.uuid4().hex[:8], **data, "created_at": now, "updated_at": now}
    with _lock:
        _prompts.append(record)
        _persist_locked()
    return _view(record)


def update_prompt(prompt_id: str, payload: dict) -> dict | None:
    data = _clean(payload)
    with _lock:
        for p in _prompts:
            if p["id"] == prompt_id:
                p.update(data, updated_at=_now())
                _persist_locked()
                return _view(p)
    return None


def duplicate_prompt(prompt_id: str) -> dict | None:
    src = get_prompt(prompt_id)
    if not src:
        return None
    return create_prompt({**src, "name": f"{src['name']} (bản sao)"[:120]})


def delete_prompt(prompt_id: str) -> bool:
    with _lock:
        for i, p in enumerate(_prompts):
            if p["id"] == prompt_id:
                _prompts.pop(i)
                _persist_locked()
                return True
    return False


def render(prompt: dict, product_name: str | None) -> str:
    """The final text sent to Gemini: the prompt with {{product_name}} filled in, followed by
    the system rules that fit it."""
    content = prompt["content"]
    if PRODUCT_VAR in content:
        name = (product_name or "").strip()
        if not name:
            raise PromptError("product name is required for this prompt")
        content = content.replace(PRODUCT_VAR, name)
    rules = rules_for(prompt)
    if rules:
        content = f"{content}\n\n{rules.replace(PRODUCT_VAR, (product_name or 'the product').strip())}"
    return content


load()
load_rules()
