"""End-to-end demo: create 3 pairs across 2 accounts, run them in parallel, show progress.

Prerequisites:
    1. python -m app.tools.login_accounts acc_hosyminh acc_syminh
       (Chrome opens → log into Gmail manually → Enter → next account)
    2. Put 2 reference images and 1 reference video in demo_inputs/ :
       demo_inputs/person1.jpg
       demo_inputs/person2.jpg
       demo_inputs/dance.mp4  (optional, ≤ 10s or auto-trimmed)

Usage:
    # 1. Start the UI in another terminal: python -m app.web
    # 2. python -m app.tools.demo
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
API = "http://127.0.0.1:5050/api"

DEMO_INPUTS = ROOT / "demo_inputs"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}") as r:
        return json.loads(r.read())


def find_input(name: str) -> Path | None:
    """Look for an input file in a few common places."""
    candidates = [
        DEMO_INPUTS / name,
        ROOT / name,
        ROOT / "input" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c
    # Loose match (case-insensitive)
    for d in (DEMO_INPUTS, ROOT, ROOT / "input"):
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file() and f.name.lower() == name.lower():
                return f
    return None


def main() -> None:
    print("== Gemini Video Tool — Demo ==")
    print()

    # Health check
    try:
        get("/pairs")
    except Exception as e:
        print(f"ERROR: UI not reachable at {API}. Start it with `python -m app.web` first.")
        return

    # Find inputs
    images = []
    for n in ("person1.jpg", "person1.jpeg", "person1.png"):
        p = find_input(n)
        if p:
            images.append(p)
            break
    if not images:
        # fallback: pick any jpeg in root
        for f in ROOT.glob("*.jpeg"):
            images.append(f)
            break
    for n in ("person2.jpg", "person2.jpeg", "person2.png"):
        p = find_input(n)
        if p and p not in images:
            images.append(p)
            break
    if not images:
        print("ERROR: no reference images found. Put person1.jpg + person2.jpg in demo_inputs/")
        return
    print(f"Images: {[str(p) for p in images]}")

    video = find_input("dance.mp4") or find_input("dance.mov")
    print(f"Video:  {video}")
    print()

    # Clean old queued pairs so the demo is repeatable
    pairs = get("/pairs")["pairs"]
    for p in pairs:
        if p["status"] in ("queued", "failed"):
            urllib.request.urlopen(urllib.request.Request(f"{API}/pairs/{p['id']}", method="DELETE"))

    # Create 3 pairs: 2 on acc_hosyminh, 1 on acc_syminh
    plan = [
        {"account": "acc_hosyminh", "image": images[0]},
        {"account": "acc_syminh", "image": images[1] if len(images) > 1 else images[0]},
        {"account": "acc_hosyminh", "image": images[1] if len(images) > 1 else images[0]},
    ]
    created = []
    for item in plan:
        body = {
            "image": str(item["image"]),
            "video": str(video) if video else None,
            "prompt": "A woman dancing slowly, smiling, soft lighting",
            "use_default_prompt": False,
            "mode": "account",
            "account": item["account"],
            "timeout": 600,
        }
        r = post("/pairs", body)
        created.append(r["pair"])
        print(f"  + queued pair {r['pair']['id']} → account={item['account']}")
    print()

    # Run all in parallel
    print("== Run All (parallel) ==")
    r = post("/run-all", {"headless": True, "delay": 0.5, "max_parallel": 3})
    print(f"batch_id={r['batch_id']} count={r['count']} max_parallel={r['max_parallel']}")
    print()

    # Poll until done
    print("Polling...")
    last_status = None
    while True:
        pairs = get("/pairs")["pairs"]
        counts = {"queued": 0, "running": 0, "done": 0, "failed": 0}
        for p in pairs:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        if (counts["running"], counts["queued"]) != last_status:
            print(f"  counts={counts}")
            last_status = (counts["running"], counts["queued"])
        if counts["running"] == 0 and counts["queued"] == 0:
            break
        time.sleep(2)

    print()
    print("== Result ==")
    for p in get("/pairs")["pairs"]:
        marker = "✓" if p["status"] == "done" else "✗"
        print(f"  {marker} {p['id']}  status={p['status']:<7} account={p.get('account',''):<14} output={p.get('output') or '-'}")
    print()
    print("Open http://127.0.0.1:5050 to see UI.")


if __name__ == "__main__":
    main()