from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys_path = str(PROJECT_ROOT)
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from app import accounts, credentials, models_store, prompt_store, runner, store, tabs, tiktok_runner  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("gemini_video_tool.web")

# Run settings. Fewer parallel browsers and slower launches mean fewer verification pages
# from Google. HEADLESS=0 (default) shows the Chrome windows, which Google accepts more
# readily and which lets you clear a verification page by hand.
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "2"))
LAUNCH_DELAY_S = float(os.environ.get("LAUNCH_DELAY_S", "15"))
HEADLESS_DEFAULT = os.environ.get("HEADLESS", "0") == "1"

ALLOWED_IMAGE = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_VIDEO = {".mp4", ".mov", ".webm"}

OUTPUT_DIR = store.PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# The React app (web/) is built into web/dist and served from here.
WEB_DIST = PROJECT_ROOT / "web" / "dist"

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB
CORS(app, resources={r"/api/*": {"origins": "*"}})


# A single asyncio loop for the whole app, owned by a daemon thread. Flask handlers
# run in worker threads; they must NOT call asyncio.new_event_loop() because
# `tabs.ChromeConnector` and other async resources are bound to the loop where they
# were first awaited, which causes subsequent requests to deadlock on
# asyncio.Lock / connect_over_cdp. Use _run_async() instead.
_async_loop: asyncio.AbstractEventLoop | None = None
_async_thread: threading.Thread | None = None


def _ensure_async_loop() -> asyncio.AbstractEventLoop:
    global _async_loop, _async_thread
    if _async_loop is not None and _async_thread is not None and _async_thread.is_alive():
        return _async_loop
    loop = asyncio.new_event_loop()

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.close()

    t = threading.Thread(target=_runner, daemon=True, name="asyncio-shared")
    t.start()
    _async_loop = loop
    _async_thread = t
    return loop


def _run_async(coro, *, timeout: float = 30.0):
    """Submit a coroutine to the shared loop from any thread and wait for the result.

    Flask threads block on this — that's fine for short async calls (CDP scans, page
    lookups). For long-running work the caller should hand the coroutine to a background
    task via _submit_async() so the HTTP response returns immediately.
    """
    loop = _ensure_async_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _submit_async(coro) -> None:
    """Fire-and-forget: schedule a coroutine on the shared loop without waiting."""
    loop = _ensure_async_loop()
    asyncio.run_coroutine_threadsafe(coro, loop)

# Per-pair log queue: pair_id -> queue.Queue of new lines (consumed by SSE).
_pair_log_q: dict[str, queue.Queue] = {}
_q_lock = threading.Lock()

# Per-pair subscribers (SSE generators): pair_id -> list of queue.Queue.
_pair_subs: dict[str, list[queue.Queue]] = {}
_sub_lock = threading.Lock()


def _new_pair_log_q(pair_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=1000)
    with _q_lock:
        _pair_log_q[pair_id] = q
    return q


def _get_or_make_q(pair_id: str) -> queue.Queue:
    with _q_lock:
        q = _pair_log_q.get(pair_id)
    if q is None:
        q = _new_pair_log_q(pair_id)
    return q


def _subscribe(pair_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=500)
    with _sub_lock:
        _pair_subs.setdefault(pair_id, []).append(q)
    return q


def _unsubscribe(pair_id: str, q: queue.Queue) -> None:
    with _sub_lock:
        subs = _pair_subs.get(pair_id, [])
        if q in subs:
            subs.remove(q)


def _broadcast(pair_id: str, event: str, data: str) -> None:
    with _sub_lock:
        subs = list(_pair_subs.get(pair_id, []))
    for q in subs:
        try:
            q.put_nowait((event, data))
        except queue.Full:
            pass


def _save_upload(file_storage, allowed_exts: set[str]) -> Path:
    if not file_storage or not file_storage.filename:
        raise ValueError("missing file")
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in allowed_exts:
        raise ValueError(f"unsupported type: {ext}")
    safe = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}{ext}"
    dest = store.UPLOADS_DIR / safe
    file_storage.save(dest)
    return dest


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path: str):
    """Serve the built frontend; unknown paths fall back to index.html (client-side routes)."""
    if path.startswith("api/"):
        return jsonify({"ok": False, "error": "not found"}), 404
    if path and (WEB_DIST / path).is_file():
        return send_from_directory(str(WEB_DIST), path)
    if not (WEB_DIST / "index.html").is_file():
        return ("Frontend not built. Run: cd web && npm install && npm run build", 503)
    return send_from_directory(str(WEB_DIST), "index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    kind = request.form.get("kind", "image")
    file = request.files.get("file")
    try:
        dest = _save_upload(file, ALLOWED_IMAGE if kind == "image" else ALLOWED_VIDEO)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "path": str(dest), "name": dest.name, "kind": kind})


# ---------- Pair CRUD ----------

@app.get("/api/pairs")
def list_pairs():
    pairs = store.list_pairs()
    counts = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    for p in pairs:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return jsonify({"pairs": pairs, "counts": counts})


@app.post("/api/pairs")
def create_pair():
    """Queue a job from a library prompt: {prompt_id, product_name, model_image?,
    product_image?, video?, video_start?, account?, timeout?, prompt_override?}."""
    payload = request.get_json(force=True) or {}
    prompt = prompt_store.get_prompt((payload.get("prompt_id") or "").strip())
    if not prompt:
        return jsonify({"ok": False, "error": "choose a prompt"}), 400
    files: dict[str, str | None] = {}
    labels = {"model_image": "model image", "product_image": "product image", "ref_video": "reference video"}
    for key, field in (("model_image", "model_image"), ("product_image", "product_image"),
                       ("ref_video", "video")):
        value = (payload.get(field) or "").strip() or None
        if prompt["inputs"].get(key):
            if not value:
                return jsonify({"ok": False, "error": f"{labels[key]} is required for this prompt"}), 400
            if not Path(value).is_file():
                return jsonify({"ok": False, "error": f"{labels[key]} file not found"}), 400
        files[field] = value if prompt["inputs"].get(key) else None
    product_name = (payload.get("product_name") or "").strip() or None
    override = (payload.get("prompt_override") or "").strip()
    try:
        text = override or prompt_store.render(prompt, product_name)
    except prompt_store.PromptError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    record = store.add_pair(prompt=text, prompt_id=prompt["id"], prompt_name=prompt["name"],
                            product_name=product_name, model_image=files["model_image"],
                            product_image=files["product_image"], video=files["video"],
                            video_start=float(payload.get("video_start", 0) or 0),
                            account=(payload.get("account") or "").strip() or AUTO_ACCOUNT,
                            timeout=int(payload.get("timeout", 600) or 600))
    return jsonify({"ok": True, "pair": record})


# ---------- Prompt library ----------

@app.get("/api/prompts")
def list_prompts():
    return jsonify({"prompts": prompt_store.list_prompts(), "categories": list(prompt_store.CATEGORIES)})


@app.post("/api/prompts")
def create_prompt():
    try:
        return jsonify({"ok": True, "prompt": prompt_store.create_prompt(request.get_json(force=True) or {})})
    except prompt_store.PromptError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.put("/api/prompts/<prompt_id>")
def update_prompt(prompt_id: str):
    try:
        updated = prompt_store.update_prompt(prompt_id, request.get_json(force=True) or {})
    except prompt_store.PromptError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if not updated:
        return jsonify({"ok": False, "error": "prompt not found"}), 404
    return jsonify({"ok": True, "prompt": updated})


@app.post("/api/prompts/<prompt_id>/duplicate")
def duplicate_prompt(prompt_id: str):
    copy = prompt_store.duplicate_prompt(prompt_id)
    if not copy:
        return jsonify({"ok": False, "error": "prompt not found"}), 404
    return jsonify({"ok": True, "prompt": copy})


@app.get("/api/system-rules")
def get_system_rules():
    return jsonify(prompt_store.get_rules())


@app.put("/api/system-rules")
def put_system_rules():
    try:
        return jsonify({"ok": True, **prompt_store.set_rules(request.get_json(force=True) or {})})
    except prompt_store.PromptError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.delete("/api/prompts/<prompt_id>")
def delete_prompt(prompt_id: str):
    # Queued jobs keep their own copy of the prompt text, so they still run after a delete.
    if not prompt_store.delete_prompt(prompt_id):
        return jsonify({"ok": False, "error": "prompt not found"}), 404
    return jsonify({"ok": True})


# ---------- Models library ----------

@app.get("/api/models")
def list_models():
    return jsonify({"models": models_store.list_models()})


@app.post("/api/models")
def create_model():
    try:
        m = models_store.create_model(request.get_json(force=True) or {})
    except models_store.ModelsError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "model": m})


@app.put("/api/models/<model_id>")
def update_model(model_id: str):
    try:
        m = models_store.update_model(model_id, request.get_json(force=True) or {})
    except models_store.ModelsError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if not m:
        return jsonify({"ok": False, "error": "model not found"}), 404
    return jsonify({"ok": True, "model": m})


@app.delete("/api/models/<model_id>")
def delete_model(model_id: str):
    if not models_store.delete_model(model_id):
        return jsonify({"ok": False, "error": "model not found"}), 404
    return jsonify({"ok": True})


@app.patch("/api/pairs/<pair_id>")
def patch_pair(pair_id: str):
    payload = request.get_json(force=True) or {}
    updated = store.update_pair(pair_id, **payload)
    if not updated:
        return jsonify({"ok": False, "error": "pair not found"}), 404
    return jsonify({"ok": True, "pair": updated})


@app.delete("/api/pairs/<pair_id>")
def delete_pair(pair_id: str):
    if not store.delete_pair(pair_id):
        return jsonify({"ok": False, "error": "cannot delete (not found or currently running)"}), 409
    return jsonify({"ok": True})


@app.post("/api/pairs/<pair_id>/retry")
def retry_pair(pair_id: str):
    updated = store.retry_pair(pair_id)
    if not updated:
        return jsonify({"ok": False, "error": "pair not found or not in failed/done state"}), 400
    return jsonify({"ok": True, "pair": updated})


# ---------- Run single / batch ----------

class _PairLogHandler(logging.Handler):
    """Each pair runs in its own thread named run-<pair id>; route that thread's log records
    (the [n/7] steps, "still generating ...") into the pair's log and SSE stream."""

    def emit(self, record: logging.LogRecord) -> None:
        name = threading.current_thread().name
        if not name.startswith("run-p_"):
            return
        pid = name[4:]
        try:
            line = record.getMessage()
        except Exception:
            return
        store.append_log(pid, line)
        _broadcast(pid, "log", json.dumps(line))


logging.getLogger().addHandler(_PairLogHandler(level=logging.INFO))

def _make_log_cb(pair_id: str):
    q = _get_or_make_q(pair_id)

    def cb(line: str) -> None:
        store.append_log(pair_id, line)
        _broadcast(pair_id, "log", json.dumps(line))  # the page JSON.parses every log event
        # Status changes happen inside runner via store.set_status; broadcast on poll/SSE.

    return cb, q


# ---------- Account pool ----------
#
# Each account = one Chrome profile, and a profile can only be open in one browser at a
# time, so an account runs at most one pair at once. Parallelism comes from using many
# accounts. Pairs with account "auto" (or empty) go to whichever account is free.

AUTO_ACCOUNT = "auto"
ATTACH_SLOT = "__attach__"
MAX_RETRIES = 3
QUOTA_COOLDOWN_S = float(os.environ.get("QUOTA_COOLDOWN_HOURS", "12")) * 3600

_acc_lock = threading.Lock()
_busy_accounts: set[str] = set()
# name -> {"reason": "quota" | "auth", "message": str, "until": epoch seconds or None}
# None = blocked until the next Run All click (used for "not logged in").
_blocked: dict[str, dict] = {}

# pair id -> {"account", "started", "loop", "task"} for runs in progress (Processes tab, Stop).
_running: dict[str, dict] = {}
_run_lock = threading.Lock()


def _logged_in_accounts() -> list[str]:
    # Accounts the last scan (or run) found signed in. __attach__ counts like any profile.
    return accounts.ready_names()


def _slot_of(pair: dict) -> str:
    if pair.get("mode") == "attach":
        return ATTACH_SLOT
    return (pair.get("account") or "").strip() or AUTO_ACCOUNT


def _block_info(name: str) -> dict | None:
    """Caller must hold _acc_lock. Drops expired quota blocks."""
    info = _blocked.get(name)
    if info and info["until"] is not None and info["until"] <= time.time():
        _blocked.pop(name, None)
        return None
    return info


def _try_acquire(name: str) -> bool:
    with _acc_lock:
        # A profile with a login window open is locked by that Chrome.
        if name in _busy_accounts or _block_info(name) or accounts.login_active(name):
            return False
        _busy_accounts.add(name)
        return True


def _release(name: str) -> None:
    with _acc_lock:
        _busy_accounts.discard(name)


def _block(name: str, reason: str, message: str) -> None:
    until = time.time() + QUOTA_COOLDOWN_S if reason == "quota" else None
    with _acc_lock:
        _blocked[name] = {"reason": reason, "message": message, "until": until}
    log.warning("account %s blocked (%s): %s", name, reason, message)


def _pool_snapshot() -> dict:
    with _acc_lock:
        blocked = {}
        for name in list(_blocked):
            info = _block_info(name)
            if info:
                blocked[name] = {"reason": info["reason"],
                                 "until": datetime.fromtimestamp(info["until"]).isoformat(timespec="minutes")
                                 if info["until"] else None}
        return {"busy": sorted(_busy_accounts), "blocked": blocked}


def _spawn_run_thread(pair: dict, account: str, headless: bool, requeue: bool) -> threading.Thread:
    """Run `pair` on `account` (already acquired by the caller; released when done).

    requeue=True (Run All): account problems move the pair to another account, other
    failures retry up to MAX_RETRIES. requeue=False (single Run): the pair stays failed.
    """
    pid = pair["id"]
    log_cb, _ = _make_log_cb(pid)
    run_pair = dict(pair)
    if account != ATTACH_SLOT or _slot_of(pair) == AUTO_ACCOUNT:
        # An auto pair may land on any profile, __attach__ included: open that exact profile.
        run_pair["mode"] = "account"
        run_pair["account"] = account
        if _slot_of(pair) == AUTO_ACCOUNT:
            run_pair["email"] = None  # the expected email belongs to a specific account

    def emit_status(status: str, **extra) -> None:
        payload = json.dumps({"status": status, **extra})
        _broadcast(pid, "status", payload)

    def run_in_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        rc = runner.RC_FAILED
        try:
            log_cb(f"[scheduler] running on account {account}")
            task = loop.create_task(runner.run_pair(run_pair, headless=headless, log_cb=log_cb))
            with _run_lock:
                _running[pid] = {"account": account, "started": time.time(),
                                 "loop": loop, "task": task, "headless": headless}
            rc = loop.run_until_complete(task)
        except BaseException as e:  # pragma: no cover  (CancelledError if stopped before start)
            log_cb(f"[fatal] {e!r}")
            store.set_status(pid, "failed")
        finally:
            with _run_lock:
                _running.pop(pid, None)
            loop.close()
            if rc == runner.RC_QUOTA:
                _block(account, "quota", "video generation limit reached")
            elif rc == runner.RC_AUTH:
                _block(account, "auth", "not logged in / wrong Gmail")
            elif rc == runner.RC_NO_VIDEO:
                _block(account, "no_video", "this account's plan cannot create videos")
            elif rc == runner.RC_CHALLENGE:
                _block(account, "verify", "Google asks for verification; open it with login_accounts")
            if requeue and rc not in (runner.RC_OK, runner.RC_INVALID, runner.RC_STOPPED):
                account_problem = rc in (runner.RC_QUOTA, runner.RC_AUTH, runner.RC_CHALLENGE,
                                         runner.RC_NO_VIDEO)
                cur = store.requeue_pair(pid, count_attempt=not account_problem,
                                         max_retries=MAX_RETRIES)
                if cur and cur["status"] == "queued":
                    why = (f"account {account} unusable" if account_problem
                           else f"attempt {cur.get('retry_count', 0)}/{MAX_RETRIES} failed")
                    log_cb(f"[scheduler] requeued: {why}")
                else:
                    log_cb(f"[scheduler] giving up after {MAX_RETRIES} attempts")
            _release(account)
            cur = store.get_pair(pid) or {}
            emit_status(cur.get("status", "failed"), exit_code=rc, output=cur.get("output"))

    t = threading.Thread(target=run_in_thread, daemon=True, name=f"run-{pid}")
    t.start()
    return t


@app.post("/api/pairs/<pair_id>/run")
def run_one(pair_id: str):
    headless = bool((request.get_json(silent=True) or {}).get("headless", HEADLESS_DEFAULT))
    pair = store.get_pair(pair_id)
    if not pair:
        return jsonify({"ok": False, "error": "pair not found"}), 404
    if pair["status"] == "running":
        return jsonify({"ok": False, "error": "already running"}), 409
    if pair["status"] not in ("queued", "failed", "done"):
        return jsonify({"ok": False, "error": f"cannot run from status {pair['status']}"}), 400
    slot = _slot_of(pair)
    candidates = _logged_in_accounts() if slot == AUTO_ACCOUNT else [slot]
    account = next((a for a in candidates if _try_acquire(a)), None)
    if not account:
        hint = (" — accounts are being scanned, try again in a moment" if accounts.is_scanning()
                else " — add or sign in an account in the Accounts tab" if not candidates else "")
        return jsonify({"ok": False, "error": f"no free account for '{slot}' "
                        f"(busy, out of quota, or not logged in){hint}"}), 409
    store.retry_pair(pair_id)  # reset if failed/done
    pair = store.claim_pair(pair_id, account)
    if not pair:
        _release(account)
        return jsonify({"ok": False, "error": "pair was taken by another run"}), 409
    _spawn_run_thread(pair, account, headless=headless, requeue=False)
    return jsonify({"ok": True, "pair_id": pair_id, "account": account, "headless": headless})


@app.post("/api/run-all")
def run_all():
    """Run every queued pair across the account pool (one pair per free account at a time)."""
    payload = request.get_json(silent=True) or {}
    result = _kickoff_run_all(headless=bool(payload.get("headless", HEADLESS_DEFAULT)),
                              delay=float(payload.get("delay", LAUNCH_DELAY_S)),
                              max_parallel=int(payload.get("max_parallel", MAX_PARALLEL) or 0))
    return jsonify(result), 200 if result.get("ok") else 400


def _broadcast_batch_status(batch_id: str, event: str, **extra) -> None:
    # Reuse per-pair SSE channel for batch events by broadcasting to a sentinel pair id.
    sentinel = f"_batch:{batch_id}"
    payload = json.dumps({"event": event, **extra})
    with _sub_lock:
        subs = list(_pair_subs.get(sentinel, []))
    for q in subs:
        try:
            q.put_nowait(("batch", payload))
        except queue.Full:
            pass


# ---------- SSE streams ----------

@app.get("/api/stream/<pair_id>")
def stream(pair_id: str):
    """SSE for one pair (or batch sentinel 'b_<id>')."""
    q = _subscribe(pair_id)

    def gen():
        # First send existing log lines from the store buffer (so reconnect catches up).
        if pair_id.startswith("p_"):
            for line in store.get_log(pair_id):
                yield f"event: log\ndata: {json.dumps(line)}\n\n"
            cur = store.get_pair(pair_id)
            if cur:
                payload = json.dumps({"status": cur["status"],
                                      "exit_code": cur.get("exit_code"),
                                      "output": cur.get("output")})
                yield f"event: status\ndata: {payload}\n\n"
                if cur["status"] in ("done", "failed"):
                    yield "event: end\ndata: {}\n\n"
                    return
        try:
            import time
            while True:
                try:
                    event, data = q.get(timeout=15.0)
                    yield f"event: {event}\ndata: {data}\n\n"
                    if event == "status":
                        try:
                            obj = json.loads(data)
                            if obj.get("status") in ("done", "failed") and not pair_id.startswith("_batch"):
                                yield "event: end\ndata: {}\n\n"
                                return
                        except json.JSONDecodeError:
                            pass
                    if event == "batch":
                        try:
                            obj = json.loads(data)
                            if obj.get("event") == "finished":
                                yield "event: end\ndata: {}\n\n"
                                return
                        except json.JSONDecodeError:
                            pass
                except queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            _unsubscribe(pair_id, q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- Outputs (existing helper, used by gallery) ----------

@app.get("/api/outputs")
def list_outputs():
    by_output = {Path(p["output"]).name: p for p in store.list_pairs() if p.get("output")}
    categories = {p["id"]: p["category"] for p in prompt_store.list_prompts()}
    files = []
    for p in sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True):
        pair = by_output.get(p.name) or {}
        files.append({
            "pair_id": pair.get("id"),
            "prompt_name": pair.get("prompt_name"),
            "product_name": pair.get("product_name"),
            "category": categories.get(pair.get("prompt_id")),
            "name": p.name,
            "size": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            "url": f"/outputs/{p.name}",
        })
    return jsonify({"files": files})


@app.route("/outputs/<path:name>")
def outputs(name: str):
    return send_from_directory(str(OUTPUT_DIR), name, as_attachment=False)


@app.route("/uploads/<path:name>")
def uploads(name: str):
    # 1) Try data/uploads/ first (new uploads)
    p = store.UPLOADS_DIR / name
    if p.is_file():
        return send_from_directory(str(store.UPLOADS_DIR), name, as_attachment=False)
    # 2) Fallback: any file with that name under the project (legacy paths in pairs.json)
    for candidate in store.PROJECT_ROOT.rglob(name):
        if candidate.is_file() and "data/uploads" not in str(candidate):
            return send_from_directory(str(candidate.parent), name, as_attachment=False)
    return ("not found", 404)


def _accounts_view() -> list[dict]:
    pool = _pool_snapshot()
    items = accounts.get_all()
    logins = accounts.login_states()
    for it in items:
        it["login"] = logins.get(it["name"])
        it["logged_in"] = it["status"] == "ready"
        it["busy"] = it["name"] in pool["busy"]
        it["blocked"] = pool["blocked"].get(it["name"])
        it["has_password"] = credentials.has(it["name"])
    return items


@app.get("/api/accounts")
def list_accounts():
    """Account profiles under accounts/ with the status found by the last scan or run."""
    return jsonify({"accounts": _accounts_view(), "scanning": accounts.is_scanning()})


@app.post("/api/accounts/scan")
def scan_accounts():
    """Open every idle profile headless, check it is signed in to Gemini, record its email."""
    with _acc_lock:
        busy = set(_busy_accounts)
        # A fresh scan decides again whether logged-out / verify accounts are usable.
        for name in [n for n, i in _blocked.items() if i["reason"] in ("auth", "verify", "no_video")]:
            _blocked.pop(name, None)
    started = accounts.scan_all(skip=busy)
    return jsonify({"ok": True, "started": started, "skipped_busy": sorted(busy)})


@app.post("/api/accounts")
def add_account():
    """Create a profile (or update an existing one) and open a visible Chrome window on
    Google sign-in for it.

    With `email` + `password` (kept in the macOS Keychain) the sign-in form is filled
    automatically, now and whenever a scan finds the profile signed out; an optional `totp`
    (Google Authenticator setup key) also answers 2-Step Verification. Without them the
    user types the sign-in into Google's page.
    """
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    exists = name in accounts.profile_names()
    if exists and not password:
        return jsonify({"ok": False, "error": f"profile {name} already exists — use Sign in on its row"}), 409
    with _acc_lock:
        if name in _busy_accounts:
            return jsonify({"ok": False, "error": f"{name} is running a job; wait or stop it first"}), 409
    try:
        if password:
            accounts.save_credentials(name, email, password, (body.get("totp") or "").strip() or None)
        accounts.start_login(name)
    except (ValueError, RuntimeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    with _acc_lock:
        _blocked.pop(name, None)
    return jsonify({"ok": True, "name": name})


@app.delete("/api/accounts/<name>/password")
def forget_password(name: str):
    try:
        removed = accounts.forget_credentials(name)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "removed": removed})


@app.post("/api/accounts/<name>/login")
def login_account(name: str):
    with _acc_lock:
        if name in _busy_accounts:
            return jsonify({"ok": False, "error": f"{name} is running a job; wait or stop it first"}), 409
    try:
        accounts.start_login(name)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    with _acc_lock:
        _blocked.pop(name, None)
    return jsonify({"ok": True})


@app.post("/api/accounts/<name>/login/cancel")
def cancel_login(name: str):
    if not accounts.cancel_login(name):
        return jsonify({"ok": False, "error": "no login window open for this account"}), 404
    return jsonify({"ok": True})


@app.post("/api/accounts/<name>/scan")
def scan_one_account(name: str):
    with _acc_lock:
        if name in _busy_accounts:
            return jsonify({"ok": False, "error": f"{name} is running a job"}), 409
        _blocked.pop(name, None)
    if not accounts.scan_all(only=[name]):
        return jsonify({"ok": False, "error": "a scan is already running; try again shortly"}), 409
    return jsonify({"ok": True})


@app.delete("/api/accounts/<name>")
def delete_account(name: str):
    with _acc_lock:
        if name in _busy_accounts:
            return jsonify({"ok": False, "error": f"{name} is running a job; stop it first"}), 409
        _blocked.pop(name, None)
    try:
        accounts.delete_account(name)
    except (ValueError, OSError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@app.get("/api/processes")
def processes():
    """Everything in flight: running pairs (account, step, elapsed, last log), the account
    pool and whether Run All / an account scan is active."""
    now = time.time()
    with _run_lock:
        running = {pid: dict(r) for pid, r in _running.items()}
    jobs = []
    for pid, r in running.items():
        pair = store.get_pair(pid) or {}
        lines = store.get_log(pid)
        step = next((ln for ln in reversed(lines) if ln.startswith("[") and "/7]" in ln[:6]), None)
        jobs.append({
            "pair_id": pid,
            "image": Path(pair.get("image") or "").name,
            "account": r["account"],
            "email": next((a.get("email") for a in accounts.get_all() if a["name"] == r["account"]), None),
            "headless": r["headless"],
            "elapsed_s": int(now - r["started"]),
            "step": step,
            "last_log": lines[-1] if lines else None,
        })
    jobs.sort(key=lambda j: -j["elapsed_s"])
    with _dispatch_lock:
        t = _dispatch["thread"]
        dispatcher = {"active": bool(t and t.is_alive()), "batch_id": _dispatch["batch_id"],
                      "max_parallel": _dispatch["max_parallel"]}
    queued = sum(1 for p in store.list_pairs() if p["status"] == "queued" and not p.get("abandoned"))
    return jsonify({"jobs": jobs, "accounts": _accounts_view(), "scanning": accounts.is_scanning(),
                    "dispatcher": dispatcher, "queued": queued,
                    "settings": {"max_parallel": MAX_PARALLEL, "launch_delay_s": LAUNCH_DELAY_S,
                                 "headless_default": HEADLESS_DEFAULT}})


@app.post("/api/pairs/<pair_id>/stop")
def stop_pair(pair_id: str):
    """Cancel a running pair: its browser is closed and the pair is marked failed."""
    with _run_lock:
        r = _running.get(pair_id)
    if not r:
        return jsonify({"ok": False, "error": "pair is not running"}), 404
    r["loop"].call_soon_threadsafe(r["task"].cancel)
    return jsonify({"ok": True})


@app.post("/api/demo")
def demo():
    """Create a few sample pairs from existing files in the project, then Run All.

    Auto-discovers any .jpg/.jpeg/.png in the project root or demo_inputs/ as reference
    images, plus an optional demo_inputs/dance.mp4. Distributes pairs across the first
    two logged-in accounts so the demo actually shows parallel execution.
    """
    candidates_img: list[Path] = []
    for d in (store.PROJECT_ROOT / "demo_inputs", store.PROJECT_ROOT, store.PROJECT_ROOT / "input"):
        if d.exists():
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                for f in d.glob(ext):
                    if f.is_file() and f not in candidates_img:
                        candidates_img.append(f)
    if not candidates_img:
        return jsonify({"ok": False, "error":
                        "no reference images found. Put .jpg/.jpeg/.png in demo_inputs/ or project root"}), 400
    video: Path | None = None
    for d in (store.PROJECT_ROOT / "demo_inputs", store.PROJECT_ROOT):
        if d.exists():
            for ext in ("*.mp4", "*.mov", "*.webm"):
                v = next(iter(d.glob(ext)), None)
                if v:
                    video = v
                    break
            if video:
                break

    logged_in = [n for n in accounts.ready_names() if n != "__attach__"]
    if len(logged_in) < 1:
        return jsonify({"ok": False, "error":
                        "no ready account. Add or sign in an account in the Accounts tab, or run "
                        "`python -m app.tools.login_accounts <name>` first."}), 400

    use_accounts = logged_in[:2] if len(logged_in) >= 2 else logged_in
    # Clean old queued/failed pairs
    for p in list(store.list_pairs()):
        if p["status"] in ("queued", "failed"):
            store.delete_pair(p["id"])

    # Create 3 pairs spread across accounts
    created = []
    for i, img in enumerate(candidates_img[:3]):
        acc = use_accounts[i % len(use_accounts)]
        rec = store.add_pair(
            prompt="A woman dancing slowly, soft lighting, smiling",
            prompt_id="demo", prompt_name="Demo – nhảy", product_name=None,
            model_image=str(img), product_image=None,
            video=str(video) if video else None,
            account=acc,
            timeout=600,
        )
        created.append(rec)

    # Kick off Run All inline
    batch = _kickoff_run_all(headless=HEADLESS_DEFAULT, delay=LAUNCH_DELAY_S, max_parallel=MAX_PARALLEL)
    return jsonify({"ok": True, "created": created, "batch": batch})


_dispatch_lock = threading.Lock()
_dispatch: dict = {"thread": None, "batch_id": None, "max_parallel": 0}


def _kickoff_run_all(headless: bool, delay: float, max_parallel: int = 0) -> dict:
    """Start (or join) the pool dispatcher.

    The dispatcher keeps every free, non-blocked account busy with the next queued pair
    that fits it. When all accounts are busy it waits for one to finish, then hands it the
    next pair. Pairs added while it runs are picked up too. It stops when the queue is
    empty, or when pairs remain but every usable account is out of quota / logged out.
    max_parallel=0 means no cap (one pair per account).
    """
    with store._lock:  # type: ignore[attr-defined]
        n_queued = sum(1 for p in store._pairs  # type: ignore[attr-defined]
                       if p["status"] == "queued" and not p.get("abandoned"))
    with _dispatch_lock:
        cur = _dispatch["thread"]
        if cur is not None and cur.is_alive():
            _dispatch["max_parallel"] = max_parallel
            return {"ok": True, "batch_id": _dispatch["batch_id"], "count": n_queued,
                    "already_running": True, **_pool_snapshot()}
        if n_queued == 0:
            return {"ok": False, "error": "no queued pairs"}
        # A new Run All gives logged-out accounts another chance (user may have logged in).
        with _acc_lock:
            for name in [n for n, i in _blocked.items() if i["reason"] == "auth"]:
                _blocked.pop(name, None)
            busy = set(_busy_accounts)
        if not accounts.ready_names():
            accounts.scan_all(skip=busy)  # first run: find the signed-in profiles
        batch_id = "b_" + uuid.uuid4().hex[:8]
        _dispatch.update(batch_id=batch_id, max_parallel=max_parallel)
        t = threading.Thread(target=_dispatch_loop, args=(batch_id, headless, delay),
                             daemon=True, name=f"batch-{batch_id}")
        _dispatch["thread"] = t
        t.start()
    return {"ok": True, "batch_id": batch_id, "count": n_queued, "headless": headless,
            "accounts": _logged_in_accounts()}


def _dispatch_loop(batch_id: str, headless: bool, delay: float) -> None:
    jobs: dict[str, threading.Thread] = {}

    def emit(event: str, **extra) -> None:
        _broadcast_batch_status(batch_id, event, running={pid: (store.get_pair(pid) or {}).get("assigned_account")
                                                          for pid in jobs},
                                **_pool_snapshot(), **extra)

    if accounts.is_scanning():
        emit("scanning")
        accounts.wait_for_scan()
    emit("started", accounts=_logged_in_accounts())
    stop_reason = "queue empty"
    while True:
        for pid in [pid for pid, t in jobs.items() if not t.is_alive()]:
            jobs.pop(pid)
            emit("job_finished", pair_id=pid)

        queued = [p for p in store.list_pairs() if p["status"] == "queued" and not p.get("abandoned")]
        if not queued and not jobs:
            break

        logged_in = _logged_in_accounts()
        pool = list(logged_in)
        for p in queued:  # pinned accounts (and attach) even if the cookie check missed them
            slot = _slot_of(p)
            if slot != AUTO_ACCOUNT and slot not in pool:
                pool.append(slot)

        cap = _dispatch["max_parallel"] or len(pool)
        for account in pool:
            if len(jobs) >= cap:
                break
            fits = [p for p in queued
                    if _slot_of(p) == account or (_slot_of(p) == AUTO_ACCOUNT and account in logged_in)]
            # Pinned pairs first so they don't starve behind auto pairs.
            fits.sort(key=lambda p: _slot_of(p) == AUTO_ACCOUNT)
            if not fits or not _try_acquire(account):
                continue
            claimed = next((c for c in (store.claim_pair(p["id"], account) for p in fits) if c), None)
            if not claimed:
                _release(account)
                continue
            queued = [p for p in queued if p["id"] != claimed["id"]]
            jobs[claimed["id"]] = _spawn_run_thread(claimed, account, headless=headless, requeue=True)
            emit("job_started", pair_id=claimed["id"], account=account)
            if delay > 0:
                threading.Event().wait(delay)  # stagger Chrome launches

        if queued and not jobs:
            with _acc_lock:
                others_busy = bool(_busy_accounts)  # e.g. a single Run holding an account
            if not others_busy:
                stop_reason = "all accounts out of quota or not logged in"
                for p in queued:
                    store.append_log(p["id"], f"[scheduler] still queued: no usable account for "
                                              f"'{_slot_of(p)}' ({stop_reason})")
                break
        threading.Event().wait(2.0)

    counts: dict[str, int] = {}
    for p in store.list_pairs():
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    log.info("batch %s finished: %s %s", batch_id, stop_reason, counts)
    emit("finished", reason=stop_reason, counts=counts)


# ---------------------------------------------------------------------------
# TikTok manager: scan the user's Chrome over CDP and run an auto-comment bot
# on a tab they already have open and signed into TikTok.
# ---------------------------------------------------------------------------


@app.get("/api/tiktok/tabs")
def list_tiktok_tabs():
    """List every Chrome tab whose URL is on tiktok.com, with login + active flag and
    the current per-tab run state (counters from the in-memory registry)."""
    import concurrent.futures
    try:
        tabs_list = _run_async(tabs.scan_tiktok_tabs(), timeout=30.0)
    except concurrent.futures.TimeoutError:
        log.warning("scan_tiktok_tabs: CDP scan timed out after 30s")
        tabs_list = []
    except Exception as e:
        # Don't crash the UI on a transient CDP hiccup — return an empty list so
        # the user can at least see their existing runner state.
        log.warning("scan_tiktok_tabs failed: %r", e)
        tabs_list = []
    for t in tabs_list:
        state = tiktok_runner.get_state(t["uid"]) or {}
        t["state"] = {
            "is_running": state.get("is_running", False),
            "comments_sent": state.get("comments_sent", 0),
            "comments_failed": state.get("comments_failed", 0),
            "current_video": state.get("current_video"),
            "last_comment": state.get("last_comment"),
            "last_error": state.get("last_error"),
            "started_at": state.get("started_at"),
            "stopped_at": state.get("stopped_at"),
        }
    return jsonify({"ok": True, "tabs": tabs_list})


@app.post("/api/tiktok/scan")
def rescan_tiktok_tabs():
    """Force a CDP reconnect and a fresh tab scan. Used when the user opens a new tab
    while the UI is open."""
    try:
        tabs_list = _run_async(tabs.scan_tiktok_tabs(), timeout=15.0)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "count": len(tabs_list)})


@app.post("/api/tiktok/headless-login")
def headless_login():
    """Open a *visible* window using the headless profile so the user can sign in
    to TikTok once. The session is saved to accounts/tiktok_headless/ and every
    subsequent run with headless=true reuses it without showing a window."""
    import asyncio, threading
    result_holder = {}
    error_holder = {}

    def target():
        try:
            result_holder["data"] = asyncio.run(
                tiktok_runner.login_tiktok_headless())
        except Exception as e:
            error_holder["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=10)
    if error_holder:
        return jsonify({"ok": False, "error": str(error_holder["error"])}), 500
    data = result_holder.get("data", {})
    return jsonify({"ok": True, "message": data.get("message"),
                    "profile": data.get("profile"),
                    "page_url": data.get("page_url")})


@app.post("/api/tiktok/login-profile/<profile_name>")
def login_profile(profile_name: str):
    """Open a visible Chrome using a specific account profile so the user can
    sign in to TikTok. The session is saved to that profile's Cookies file."""
    import asyncio, threading
    result_holder = {}
    error_holder = {}

    def target():
        try:
            result_holder["data"] = asyncio.run(
                tiktok_runner.login_tiktok_profile(profile_name))
        except Exception as e:
            error_holder["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=10)
    if error_holder:
        return jsonify({"ok": False, "error": str(error_holder["error"])}), 500
    data = result_holder.get("data", {})
    return jsonify({"ok": True, "message": data.get("message"),
                    "profile": data.get("profile"),
                    "page_url": data.get("page_url")})


@app.get("/api/tiktok/profiles")
def list_tiktok_profiles():
    """List every account profile under accounts/ that has TikTok cookies,
    so the UI can show a 'login from another account' picker."""
    try:
        profiles = _run_async(tabs.scan_account_profiles(), timeout=5.0)
    except Exception:
        profiles = []
    return jsonify({"ok": True, "profiles": [
        {"name": p["profile_name"], "uid": p["uid"], "title": p["title"]}
        for p in profiles
    ]})


@app.post("/api/tiktok/tabs/<uid>/run")
def run_tiktok_tab(uid: str):
    """Start a bot on the tab. Body:

      video_url          optional single video URL; if empty the bot opens the For You
                         feed and scrolls through videos.
      templates          list of comment strings, cycled in order. Required, at least 1.
      dwell_seconds      seconds to let the video play before commenting. Default 3.
                         A longer dwell looks less like spam — TikTok flags accounts
                         that comment within the first second of watching.
      max_comments       stop after this many successful posts. Default 20.
      scroll_after_each  scroll to the next video after each post. Default true.
      cooldown_seconds   minimum pause between successive posts. Default 3.
                         The bot adds ±40 % jitter on top so the cadence is irregular.
      skip_first         skip the first `skip_first` videos (let them play through
                         before commenting). Default 0 — comment on every video.
      headless           run in an invisible, dedicated Chrome with its own
                         profile. Default false. Auto-enabled when the tab came
                         from an account profile (no live Chrome tab exists). The
                         user signs in once via the `/api/tiktok/login-profile`
                         helper; after that every run uses the saved session
                         without ever showing a window.
    """
    body = request.get_json(silent=True) or {}
    templates = body.get("templates") or []
    templates = [str(t).strip() for t in templates if str(t).strip()]
    if not templates:
        return jsonify({"ok": False, "error": "add at least one comment template"}), 400

    try:
        tabs_list = _run_async(tabs.scan_tiktok_tabs(), timeout=30.0)
    except Exception as e:
        return jsonify({"ok": False, "error": f"CDP scan failed: {e}"}), 500
    tab = next((t for t in tabs_list if t["uid"] == uid), None)
    if not tab:
        return jsonify({"ok": False, "error": "tab not found — refresh the page"}), 404
    if not tab.get("logged_in"):
        return jsonify({"ok": False, "error": "this tab is not logged in to TikTok"}), 409

    # Profile-source tabs require headless mode to use the saved cookies.
    headless_requested = bool(body.get("headless", False)) or tab.get("source") == "profile"

    state = tiktok_runner.start_run(
        tab=tab,
        video_url=(body.get("video_url") or "").strip() or None,
        templates=templates,
        dwell_s=float(body.get("dwell_seconds") or 3),
        max_comments=int(body.get("max_comments") or 20),
        scroll_after_each=bool(body.get("scroll_after_each", True)),
        cooldown_s=float(body.get("cooldown_seconds") or 3),
        skip_first=int(body.get("skip_first") or 0),
        headless=headless_requested,
    )
    return jsonify({"ok": True, "state": state})
    """Start a bot on the tab. Body:

      video_url          optional single video URL; if empty the bot opens the For You
                         feed and scrolls through videos.
      templates          list of comment strings, cycled in order. Required, at least 1.
      dwell_seconds      seconds to let the video play before commenting. Default 3.
                         A longer dwell looks less like spam — TikTok flags accounts
                         that comment within the first second of watching.
      max_comments       stop after this many successful posts. Default 20.
      scroll_after_each  scroll to the next video after each post. Default true.
      cooldown_seconds   minimum pause between successive posts. Default 3.
                         The bot adds ±40 % jitter on top so the cadence is irregular.
      skip_first         skip the first `skip_first` videos (let them play through
                         before commenting). Default 0 — comment on every video.
      headless           run in an invisible, dedicated Chrome with its own
                         profile. Default false. The user signs in once via the
                         `/api/tiktok/headless-login` helper; after that every
                         run uses the saved session without ever showing a window.
    """
    body = request.get_json(silent=True) or {}
    templates = body.get("templates") or []
    templates = [str(t).strip() for t in templates if str(t).strip()]
    if not templates:
        return jsonify({"ok": False, "error": "add at least one comment template"}), 400

    try:
        tabs_list = _run_async(tabs.scan_tiktok_tabs(), timeout=30.0)
    except Exception as e:
        return jsonify({"ok": False, "error": f"CDP scan failed: {e}"}), 500
    tab = next((t for t in tabs_list if t["uid"] == uid), None)
    if not tab:
        return jsonify({"ok": False, "error": "tab not found — refresh the page"}), 404
    if not tab.get("logged_in"):
        return jsonify({"ok": False, "error": "this tab is not logged in to TikTok"}), 409

    state = tiktok_runner.start_run(
        tab=tab,
        video_url=(body.get("video_url") or "").strip() or None,
        templates=templates,
        dwell_s=float(body.get("dwell_seconds") or 3),
        max_comments=int(body.get("max_comments") or 20),
        scroll_after_each=bool(body.get("scroll_after_each", True)),
        cooldown_s=float(body.get("cooldown_seconds") or 3),
        skip_first=int(body.get("skip_first") or 0),
        headless=bool(body.get("headless", False)),
    )
    return jsonify({"ok": True, "state": state})


@app.post("/api/tiktok/tabs/<uid>/stop")
def stop_tiktok_tab(uid: str):
    """Cancel the run for this tab. Returns the final state if it was running."""
    was_running = tiktok_runner.stop_run(uid)
    return jsonify({"ok": True, "was_running": was_running,
                    "state": tiktok_runner.get_state(uid) or {}})


@app.get("/api/tiktok/stream/<uid>")
def stream_tiktok_tab(uid: str):
    """SSE: per-tab run state changes + log lines. Replay existing buffer on connect."""
    q = tiktok_runner.subscribe(uid)

    def gen():
        for line in tiktok_runner.get_log(uid):
            import json
            yield f"event: log\ndata: {json.dumps({'line': line})}\n\n"
        state = tiktok_runner.get_state(uid)
        if state:
            import json
            yield f"event: state\ndata: {json.dumps(state)}\n\n"
        try:
            while True:
                try:
                    event, data = q.get(timeout=15.0)
                    yield f"event: {event}\ndata: {data}\n\n"
                except queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            tiktok_runner.unsubscribe(uid, q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    # Default to 5050 to avoid macOS AirPlay Receiver (which holds 5000).
    port = int(os.environ.get("PORT", "5050"))
    if not any(a["status"] != "unknown" for a in accounts.get_all()):
        accounts.scan_all()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)