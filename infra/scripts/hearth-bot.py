#!/usr/bin/env python3
"""
Hearth Telegram bot — remote command interface for autonomous Claude Code sessions.

Reads config from environment (sourced from infra/local.env by the run script):
  HEARTH_BOT_TOKEN      Telegram bot API token (from BotFather)
  HEARTH_BOT_USER_ID    Your Telegram user ID (from @userinfobot) — only user accepted
  HEARTH_REPO_ROOT      Path to the repo (defaults to two levels up from this script)
  CLAUDE_BIN            Path to the claude CLI (defaults to auto-detected)

Commands:
  /run <task>   Start an autonomous agent session focused on <task>
  /status       Is an agent currently running?
  /stop         Stop the running agent
  /log          Last 10 git commits
  /progress     Tail of claude-progress.txt
  /features     Failing features from feature_list.json
  /help         Show command list

Plain messages (no /command prefix) are treated as /run.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode  # noqa: F401 (kept for reference)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Config ────────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ["HEARTH_BOT_TOKEN"]
AUTHORIZED_USER_ID = int(os.environ["HEARTH_BOT_USER_ID"])

_script_dir = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("HEARTH_REPO_ROOT", str(_script_dir / ".." / "..")))

# Find claude binary: explicit env var > PATH search > common install locations
def _find_claude() -> str:
    if "CLAUDE_BIN" in os.environ:
        return os.environ["CLAUDE_BIN"]
    found = shutil.which("claude")
    if found:
        return found
    candidates = [
        Path.home() / ".npm" / "bin" / "claude",
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "claude"  # fall back and let the OS error be descriptive

CLAUDE_BIN = _find_claude()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("hearth-bot")

# ── Agent process state ───────────────────────────────────────────────────────

_agent_proc: subprocess.Popen | None = None
_agent_lock = threading.Lock()


# ── Auth guard ────────────────────────────────────────────────────────────────

def authorized(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if uid != AUTHORIZED_USER_ID:
        log.warning("Rejected message from user %s", uid)
        return False
    return True


# ── Helpers ───────────────────────────────────────────────────────────────────

def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _html(text: str) -> str:
    """Escape text for Telegram HTML mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        "🏠 <b>Hearth bot</b>\n\n"
        "/run &lt;task&gt; — start agent session\n"
        "/status — is an agent running?\n"
        "/stop — kill running agent\n"
        "/log — last 10 git commits\n"
        "/progress — claude-progress.txt tail\n"
        "/features — failing features\n\n"
        "Plain message = /run",
        parse_mode="HTML",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    with _agent_lock:
        running = _agent_proc is not None and _agent_proc.poll() is None
    if running:
        await update.message.reply_text("🟢 Agent is running.")
    else:
        await update.message.reply_text("⚪ No agent running.")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _agent_proc
    if not authorized(update):
        return
    with _agent_lock:
        if _agent_proc is not None and _agent_proc.poll() is None:
            _agent_proc.terminate()
            await update.message.reply_text("🛑 Agent stopped.")
        else:
            await update.message.reply_text("No agent is running.")


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    commits = git("log", "--oneline", "-10")
    text = commits if commits else "No commits yet."
    await update.message.reply_text(
        f"<b>Recent commits:</b>\n<pre>{_html(text)}</pre>",
        parse_mode="HTML",
    )


async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    path = REPO_ROOT / "claude-progress.txt"
    if not path.exists():
        await update.message.reply_text("claude-progress.txt not found.")
        return
    lines = path.read_text().splitlines()
    tail = "\n".join(lines[-40:])
    await update.message.reply_text(
        f"<pre>{_html(tail)}</pre>",
        parse_mode="HTML",
    )


async def cmd_features(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    path = REPO_ROOT / "feature_list.json"
    if not path.exists():
        await update.message.reply_text("feature_list.json not found.")
        return
    data = json.loads(path.read_text())
    failing = [f for f in data.get("features", []) if not f.get("passes")]
    failing.sort(key=lambda f: f.get("priority", 99))
    if not failing:
        await update.message.reply_text("✅ All features passing!")
        return
    lines = [f"<b>{len(failing)} features pending:</b>\n"]
    for f in failing[:10]:
        p = f.get("priority", "?")
        lines.append(f"  <code>{_html(f['id'])}</code> [p{p}] {_html(f['title'])}")
    if len(failing) > 10:
        lines.append(f"\n…and {len(failing) - 10} more.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── Agent runner ──────────────────────────────────────────────────────────────

async def handle_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /run <task> or a plain message — kick off a Claude Code session."""
    global _agent_proc
    if not authorized(update):
        return

    text = (update.message.text or "").strip()
    if text.startswith("/run"):
        task = text[4:].strip()
    else:
        task = text

    if not task:
        await update.message.reply_text(
            "Tell me what to work on:\n/run implement budget CSV export"
        )
        return

    with _agent_lock:
        if _agent_proc is not None and _agent_proc.poll() is None:
            await update.message.reply_text(
                "⚠️ Agent already running. Use /stop first."
            )
            return

    coding_prompt_path = REPO_ROOT / "agent" / "coding.md"
    if not coding_prompt_path.exists():
        await update.message.reply_text("❌ agent/coding.md not found.")
        return

    coding_prompt = coding_prompt_path.read_text()
    full_prompt = (
        f"{coding_prompt}\n\n"
        "---\n\n"
        "## This session's focus\n\n"
        f"{task}\n\n"
        "Begin now. Start with `./init.sh`, then orient yourself with git log and "
        "claude-progress.txt before selecting a feature."
    )

    await update.message.reply_text(
        f"🚀 Starting agent session…\n\n<b>Task:</b> {_html(task)}",
        parse_mode="HTML",
    )

    chat_id = update.effective_chat.id
    bot = context.bot

    # Run in executor so the bot stays responsive during the long-running session
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _agent_thread, full_prompt, chat_id, bot, loop)


def _agent_thread(
    prompt: str,
    chat_id: int,
    bot,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Background thread: run claude, watch git commits, relay to Telegram."""
    global _agent_proc

    def send(text: str) -> None:
        asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id=chat_id, text=text),
            loop,
        )

    # Record starting commit so we can detect new ones
    start_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip() or "HEAD"

    # ── Launch claude ──────────────────────────────────────────────────────
    # claude -p runs a single non-interactive session; Claude uses its built-in
    # tools (Bash, Read, Write, Edit) to complete the task and exits when done.
    try:
        proc = subprocess.Popen(
            [CLAUDE_BIN, "-p", prompt, "--dangerously-skip-permissions"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        send(f"❌ claude binary not found at: {CLAUDE_BIN}\nSet CLAUDE_BIN in infra/local.env")
        return

    with _agent_lock:
        _agent_proc = proc

    log.info("Claude process started (PID %s)", proc.pid)

    # ── Commit watcher ─────────────────────────────────────────────────────
    stop_watcher = threading.Event()
    last_sha = start_sha

    def watch_commits() -> None:
        nonlocal last_sha
        while not stop_watcher.wait(timeout=15):
            new = subprocess.run(
                ["git", "log", "--oneline", f"{last_sha}..HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if new:
                for line in reversed(new.splitlines()):
                    send(f"✓ {line}")
                last_sha = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

    watcher = threading.Thread(target=watch_commits, daemon=True)
    watcher.start()

    # ── Wait for claude to finish ──────────────────────────────────────────
    proc.wait()
    stop_watcher.set()
    watcher.join(timeout=20)

    # Count commits made this session
    commits_made = subprocess.run(
        ["git", "log", "--oneline", f"{start_sha}..HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    n = len(commits_made.splitlines()) if commits_made else 0

    if proc.returncode == 0:
        send(f"✅ Session complete — {n} commit{'s' if n != 1 else ''} this session.")
    else:
        send(f"⚠️ Agent exited with code {proc.returncode}. Use /log and /progress to inspect.")

    log.info("Claude process finished (rc=%s, commits=%s)", proc.returncode, n)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Hearth bot starting (repo: %s)", REPO_ROOT)
    log.info("claude binary: %s", CLAUDE_BIN)
    log.info("Authorized user ID: %s", AUTHORIZED_USER_ID)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("progress", cmd_progress))
    app.add_handler(CommandHandler("features", cmd_features))
    app.add_handler(CommandHandler("run", handle_run))
    # Plain messages → treat as /run
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_run))

    log.info("Polling for messages…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
