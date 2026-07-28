"""Text chat REPL — talk to Jarvis by typing instead of speaking.

Drives the exact same reply pipeline as the voice path
(``run_reply_engine``: planner, tools, memory enrichment, dialogue
memory), so replies, tool access, and memory behave identically to a
spoken conversation. Built for machines without a microphone (headless
servers, remote sessions). See text_chat.spec.md.

Run as a CLI:

    python -m jarvis.text_chat
"""

from __future__ import annotations

import sys

from .config import load_settings
from .debug import debug_log
from .llm.tiers import Tier, resolve_model
from .memory.conversation import (
    Database,
    DialogueMemory,
    update_diary_from_dialogue_memory,
)
from .reply.engine import run_reply_engine

_QUIT_COMMAND = "/quit"


def run_text_chat(db, cfg, dialogue_memory) -> None:
    """Read lines from stdin, answer each through the reply engine.

    Blank lines are skipped. ``/quit`` or EOF (Ctrl+Z then Enter on
    Windows, Ctrl+D elsewhere) ends the session; the diary is flushed on
    the way out so text conversations feed long-term memory exactly like
    voice ones.
    """
    print("💬 Jarvis text chat — type a question, /quit to leave", flush=True)
    try:
        while True:
            try:
                print("🗣️  ", end="", flush=True)
                line = sys.stdin.readline()
            except KeyboardInterrupt:
                break
            if not line:  # EOF
                break
            text = line.strip()
            if not text:
                continue
            if text.lower() == _QUIT_COMMAND:
                break

            debug_log(f"text chat query: '{text[:80]}'", "jarvis")
            try:
                reply = run_reply_engine(db, cfg, None, text, dialogue_memory)
            except Exception as e:
                debug_log(f"text chat engine error: {e}", "jarvis")
                print(f"  ❌ Reply engine error: {e}", flush=True)
                continue
            print(f"🤖 {reply or '(no reply)'}", flush=True)
    finally:
        # Same shutdown contract as the daemon: unsaved dialogue becomes a
        # diary entry (and, downstream, graph knowledge).
        try:
            if dialogue_memory.has_recent_messages():
                print("📝 Saving this conversation to the diary...", flush=True)
            update_diary_from_dialogue_memory(
                db,
                dialogue_memory,
                cfg,
                source_app="stdin",
                timeout_sec=getattr(cfg, "llm_chat_timeout_sec", 30.0),
                force=True,
                graph_picker_model=resolve_model(cfg, Tier.FAST),
            )
        except Exception as e:
            debug_log(f"text chat diary flush failed: {e}", "jarvis")
        print("👋 Bye", flush=True)


def main() -> int:
    cfg = load_settings()
    db = Database(cfg.db_path, cfg.sqlite_vss_path)
    dialogue_memory = DialogueMemory(
        inactivity_timeout=cfg.dialogue_memory_timeout,
        max_interactions=20,
    )

    mcps = getattr(cfg, "mcps", {}) or {}
    if mcps:
        from .tools.registry import initialize_mcp_tools
        print(f"📡 Discovering MCP tools from {len(mcps)} server(s)...", flush=True)
        try:
            initialize_mcp_tools(mcps, verbose=False)
        except Exception as e:
            print(f"  ⚠️ MCP discovery failed: {e}", flush=True)

    print(f"🧠 Chat model: {cfg.llm_chat_model} | fast: {cfg.fast_model}", flush=True)
    run_text_chat(db, cfg, dialogue_memory)
    return 0


if __name__ == "__main__":
    sys.exit(main())
