# Gemini Video Tool (PoC)

Small Playwright CLI: **Gemini Web → attach image (+ optional reference video) → prompt → generate
video → download MP4**, in your own running Chrome (`--attach`) or a dedicated profile (`--account`).

No passwords, cookies or tokens are stored by this tool.

## Ad Studio (web)

Web tool for ad videos: pick a prompt (clothes, cosmetics, bag, dance…), type the product name,
upload the images, queue it, run across your Gemini accounts.

```bash
pip install -r requirements.txt         # once
cd web && npm install && npm run build  # once, and after every frontend change
cd .. && python -m app.web              # http://127.0.0.1:5050
```

- **Prompt library** (`data/prompts.json`, seeded with 6 prompts on first run): each prompt is
  self-contained and declares which files it needs (model image, product image, reference video).
  `{{product_name}}` in a prompt is the only variable — the create form asks for it only then.
  Files are pasted into Gemini in the order model → product → video.
- A queued job stores the final prompt text, so editing or deleting a prompt later does not change it.
- Frontend: `web/` (React + Vite + shadcn/ui). `npm run dev` serves it on :5173 with the API
  proxied to the Flask server.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Default browser is your installed Google Chrome (--channel chrome).
# To use Playwright's bundled Chromium instead:
#   python -m playwright install chromium   and pass --channel chromium
```

## Using your running Chrome (`--attach`)

Google refuses sign-in inside browsers launched by automation, so the simplest setup is to let the
tool work in the Chrome you already use, signed in to Gemini:

1. In Chrome, open `chrome://inspect/#remote-debugging` and enable
   **Allow remote debugging for this browser instance**.
2. Run the tool with `--attach`. Chrome asks you to approve the connection the first time.

```bash
# Image (the person) + reference video (the dance), default prompt, output/<image>-<time>.mp4
python -m app.cli generate --attach --email you@gmail.com --image ./photo.jpeg --video ./dance.mp4

# Custom prompt / prompt file / output path
python -m app.cli generate --attach --image ./photo.jpeg --prompt "..." --output ./output/a.mp4
python -m app.cli generate --attach --image ./photo.jpeg --prompt-file ./prompts/other.txt

python -m app.cli batch --attach --jobs ./jobs.example.json
```

Without `--prompt`/`--prompt-file` the prompt in `prompts/default.txt` is used (edit that file to
change the default). Image and video are pasted into Gemini's prompt box, the "Create video" tool
is selected, and the finished video is saved from its source URL (fallback: "Download video").
In `jobs.json`, each job needs `image`; `video`, `prompt`, `prompt_file` and `output` are optional.

The tool opens its own tab, works only there and closes only that tab; your other tabs are left
alone. `--email` is a safety check: the run stops if Gemini in that window is signed in as someone
else. Turn remote debugging off again when you are done.

## Usage with a dedicated profile (`--account`)

```bash
# First time per account: log in manually in the opened window, then press Enter.
python -m app.cli login --account account_01

# One video
python -m app.cli generate --account account_01 \
  --image ./input/sample.png \
  --prompt "A woman performing a natural modern dance, realistic movement, cinematic camera movement" \
  --output ./output/dance.mp4 \
  --timeout 600

# Several videos, sequentially (see jobs.example.json; "output" is optional)
python -m app.cli batch --account account_01 --jobs ./jobs.example.json --output-dir ./output
```

Options: `--channel chrome|chromium|msedge`, `--keep-open-on-error`, `-v` (debug logs).

## Layout

| Path | Purpose |
| --- | --- |
| `app/cli.py` | argparse CLI (`login`, `generate`, `batch`) |
| `app/browser.py` | persistent-context launcher (`--account`) and running-Chrome connector (`--attach`) |
| `app/gemini.py` | `GeminiAutomation` + **all Gemini selectors** |
| `app/models.py` | validation (image, video, account name, jobs.json) and default prompt |
| `prompts/default.txt` | prompt used when none is given |
| `accounts/<name>/` | browser profile (session) — git-ignored |
| `output/` | videos — git-ignored |
| `screenshots/<name>/` | `error-*.png/.html/.controls.txt` on failure — git-ignored |

## When Gemini's UI changes

Every failure writes `screenshots/<account>/error-<time>.controls.txt` listing all visible
buttons/menu items with their accessible labels. Compare it with the selector constants at the
top of `app/gemini.py` (marked `VERIFIED` / `CANDIDATE`) and update the matching regex.

## Limits

- Requires a Gemini plan with video generation (Veo); daily quotas apply.
- No CAPTCHA or verification automation: complete those yourself in the window.
- Jobs run sequentially by design.
