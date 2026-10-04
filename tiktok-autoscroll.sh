#!/usr/bin/env bash
# tiktok-autoscroll.sh
#
# Auto-scrolls TikTok's For You feed and optionally follows each video's
# author + captures top-5 comments. Requires you to be ALREADY logged into
# TikTok in a real Chrome window before running this script.
#
# Usage:
#   1. Open Google Chrome (real, not Chrome for Testing). Make sure you are
#        logged into TikTok (For You feed shows your avatar in the sidebar).
#   2. Run:  ./tiktok-autoscroll.sh --comments -m 50
#
# Flags:
#   --comments           Capture top-5 comments per video to JSONL.
#   --follow             Try to follow each video's author (default: ON).
#   --no-follow          Skip follow attempts.
#   -i, --interval N     Seconds between scrolls. Default: 8
#   -m, --max-scrolls N  Stop after N scrolls (0 = forever). Default: 0
#   -d, --max-duration T Stop after T seconds (e.g. 30m, 2h). Default: 0
#   -o, --output PATH    Output JSONL (only with --comments).
#   -h, --help
#
# Requirements: agent-browser (npm i -g agent-browser && agent-browser install)
#               jq        (brew install jq) — only needed for --comments
#               Google Chrome (real, not Chrome for Testing)
#
# Why "real Chrome": TikTok's comments/follow, and Google's OAuth, both
# detect Chrome for Testing (automation browser) via fingerprint and either
# reject login or block comment reads. Real Chrome + your existing login
# session works around that.

set -euo pipefail

START_URL="https://www.tiktok.com/foryou"
STATE_DIR="$HOME/.agent-browser-states"
TIKTOK_STATE="$STATE_DIR/tiktok.json"
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

CAPTURE_COMMENTS=0
DO_FOLLOW=1
INTERVAL=8
MAX_SCROLLS=0
MAX_DURATION=0
OUTPUT_PATH=""

positional=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --comments)            CAPTURE_COMMENTS=1; shift ;;
    --follow)              DO_FOLLOW=1; shift ;;
    --no-follow)           DO_FOLLOW=0; shift ;;
    -i|--interval)         INTERVAL="$2"; shift 2 ;;
    -m|--max-scrolls)      MAX_SCROLLS="$2"; shift 2 ;;
    -d|--max-duration)     MAX_DURATION="$2"; shift 2 ;;
    -o|--output)           OUTPUT_PATH="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,34p' "$0"; exit 0 ;;
    -*)
      echo "Unknown flag: $1" >&2; exit 1 ;;
    *)
      positional+=("$1"); shift ;;
  esac
done

if [[ ${#positional[@]} -gt 0 ]]; then INTERVAL="${positional[0]:-$INTERVAL}"; fi
if [[ ${#positional[@]} -gt 1 ]]; then MAX_SCROLLS="${positional[1]:-$MAX_SCROLLS}"; fi
if [[ ${#positional[@]} -gt 2 ]]; then START_URL="${positional[2]:-$START_URL}"; fi

if [[ "$MAX_DURATION" =~ ^[0-9]+[smh]$ ]]; then
  n="${MAX_DURATION%?}"; unit="${MAX_DURATION: -1}"
  case "$unit" in
    s) MAX_DURATION="$n" ;;
    m) MAX_DURATION=$((n * 60)) ;;
    h) MAX_DURATION=$((n * 3600)) ;;
  esac
fi

mkdir -p "$STATE_DIR"

# ---------------------------------------------------------------------------
# Deps
# ---------------------------------------------------------------------------
if ! command -v agent-browser >/dev/null 2>&1; then
  echo "agent-browser not found. Install with: npm i -g agent-browser && agent-browser install" >&2
  exit 1
fi
if [[ "$CAPTURE_COMMENTS" -eq 1 ]] && ! command -v jq >/dev/null 2>&1; then
  echo "jq not found. Install with: brew install jq" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
is_logged_in() {
  agent-browser eval \
    "!!document.querySelector('[data-e2e=nav-profile] img')" \
    2>/dev/null | grep -q true
}

try_follow_author() {
  agent-browser click "[data-e2e='feed-follow']" >/dev/null 2>&1 \
    || agent-browser click "[data-e2e='follow-button']" >/dev/null 2>&1 \
    || agent-browser click "[aria-label='Follow']" >/dev/null 2>&1 \
    || agent-browser find role button click --name "Follow" >/dev/null 2>&1 \
    || true
}

open_comments_panel() {
  agent-browser click "[data-e2e='comment-icon']" >/dev/null 2>&1 \
    || return 1
  for _ in $(seq 1 20); do
    if agent-browser eval \
        "!!document.querySelector('[data-e2e=\"comment-level-1\"]') || \
         !!document.querySelector('[class*=\"CommentItemContainer\"], [class*=\"DivCommentItemContainer\"]')" \
        2>/dev/null | grep -q true; then
      return 0
    fi
    sleep 0.5
  done
  # Fallback: try to find any comment text node regardless of selector
  if agent-browser eval \
      "Array.from(document.querySelectorAll('p, span, div')).some(e => /^.{3,}$/.test(e.textContent.trim()) && e.closest('[class*=Comment]'))" \
      2>/dev/null | grep -q true; then
    return 0
  fi
  return 1
}

read_comments() {
  # Selector-tolerant: try data-e2e first, fall back to class patterns.
  agent-browser eval '
    JSON.stringify(
      Array.from(
        document.querySelectorAll(
          "[data-e2e=comment-item], [class*=DivCommentItemContainer], [class*=CommentItemContainer]"
        )
      )
        .slice(0, 5)
        .map((it, i) => {
          const u = it.querySelector("[data-e2e=comment-username-1] p, a[class*=UserLinkName] p, [class*=SpanUserName]");
          const b = it.querySelector("[data-e2e=comment-level-1], [class*=SpanComment], p[class*=Comment]");
          const l = it.querySelector("[data-e2e=comment-like-count], [class*=LikeCount]");
          const t = it.querySelector("[data-e2e=comment-time] span, time, [class*=CommentTime]");
          return {
            rank: i + 1,
            username: (u?.textContent || "").trim(),
            body: (b?.textContent || "").trim(),
            like_count: (l?.textContent || "").trim(),
            time: ((t?.textContent || t?.getAttribute("title") || "").toString()).trim()
          };
        })
    )
  ' 2>/dev/null | tail -1
}

close_comments_panel() {
  agent-browser click "[aria-label='exit']" >/dev/null 2>&1 \
    || agent-browser click "[aria-label='Close']" >/dev/null 2>&1 \
    || agent-browser press Escape >/dev/null 2>&1 \
    || true
  return 0
}

append_record() {
  local vidx="$1" comments_json="$2"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  jq -nc \
    --argjson vidx "$vidx" \
    --arg ts "$ts" \
    --argjson comments "${comments_json:-[]}" \
    '{video_index:$vidx, scrolled_at:$ts, comments:$comments}' \
    >> "$OUTFILE"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  TikTok auto-scroll (--comments=$CAPTURE_COMMENTS, follow=$DO_FOLLOW)"
echo "============================================================"
echo ">> Connecting to running Chrome via CDP..."

if ! AGENT_BROWSER_AUTO_CONNECT=1 agent-browser get url >/dev/null 2>&1; then
  echo ">> ERROR: cannot connect to Chrome via CDP."
  echo ">> Make sure Google Chrome is running, then re-run."
  echo ">> To launch Chrome with CDP enabled, run this in another terminal:"
  echo ">>   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\"
  echo ">>     --remote-debugging-port=9222"
  exit 1
fi

echo ">> Navigating to TikTok For You..."
AGENT_BROWSER_AUTO_CONNECT=1 agent-browser open --headed "$START_URL" >/dev/null
AGENT_BROWSER_AUTO_CONNECT=1 agent-browser wait --load networkidle >/dev/null

if ! is_logged_in; then
  echo ">> ERROR: TikTok is not showing you as logged in."
  echo ">> Open the Chrome window, log in to TikTok (via Continue with Google),"
  echo ">> then re-run this script."
  exit 1
fi

echo ">> Logged in as:"
AGENT_BROWSER_AUTO_CONNECT=1 agent-browser eval \
  "JSON.stringify({profile: document.querySelector('[data-e2e=nav-profile]')?.textContent?.trim()?.slice(0,40)})" \
  2>/dev/null | tail -1 | head -c 200
echo
echo ">> Interval: ${INTERVAL}s   Max scrolls: ${MAX_SCROLLS}   Max duration: ${MAX_DURATION}s"
echo ">> Press Ctrl-C to stop."
echo

OUTFILE=""
if [[ "$CAPTURE_COMMENTS" -eq 1 ]]; then
  if [[ -z "$OUTPUT_PATH" ]]; then
    OUTPUT_PATH="$PROJECT_ROOT/output/tiktok-comments-$(date +%Y%m%d-%H%M%S).jsonl"
  fi
  mkdir -p "$(dirname "$OUTPUT_PATH")"
  : > "$OUTPUT_PATH"
  OUTFILE="$OUTPUT_PATH"
  echo ">> Writing top-5 comments per video to: $OUTFILE"
  echo
fi

# Optional: save state so future runs can use headless agent-browser if Chrome
# is closed at startup.
AGENT_BROWSER_AUTO_CONNECT=1 agent-browser state save "$TIKTOK_STATE" >/dev/null 2>&1 || true

scroll() {
  AGENT_BROWSER_AUTO_CONNECT=1 agent-browser press ArrowDown >/dev/null
}

count=0
start_ts=$(date +%s)

cleanup() {
  if [[ -n "$OUTFILE" && "$CAPTURE_COMMENTS" -eq 1 ]]; then
    echo
    echo ">> Wrote $count records to $OUTFILE"
  fi
}
trap cleanup EXIT

while true; do
  count=$((count + 1))
  if [[ "$MAX_SCROLLS" -gt 0 && "$count" -gt "$MAX_SCROLLS" ]]; then
    echo ">> Reached max scrolls ($MAX_SCROLLS). Stopping."
    break
  fi
  if [[ "$MAX_DURATION" -gt 0 ]] && (( $(date +%s) - start_ts >= MAX_DURATION )); then
    echo ">> Reached max duration (${MAX_DURATION}s). Stopping."
    break
  fi

  scroll

  if [[ "$DO_FOLLOW" -eq 1 ]]; then
    try_follow_author || true
  fi

  if [[ "$CAPTURE_COMMENTS" -eq 1 ]]; then
    if open_comments_panel; then
      comments_json=$(read_comments || echo "[]")
      append_record "$count" "${comments_json:-[]}"
      close_comments_panel || true
    else
      append_record "$count" "[]"
    fi
  fi

  echo "Scroll $count  ($(date +%H:%M:%S))"

  sleep "$INTERVAL"
done

echo ">> Done."