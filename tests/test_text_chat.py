"""Behaviour tests for the text chat REPL.

The REPL drives the standard reply engine over typed lines instead of
voice. The engine, database, and diary flush are mocked — tests verify the
loop's observable behaviour: lines reach the engine, replies are printed,
dialogue memory is shared across turns, errors don't kill the session, and
the diary is flushed on exit.
"""

import io

import pytest

import jarvis.text_chat as chat_mod
from jarvis.text_chat import run_text_chat


class DummyCfg:
    db_path = ":memory:"
    sqlite_vss_path = None
    dialogue_memory_timeout = 300.0
    llm_chat_timeout_sec = 30.0
    fast_model = "fast"
    mcps = {}


class DummyMemory:
    def __init__(self):
        self.messages = []

    def has_recent_messages(self):
        return bool(self.messages)


def _run(monkeypatch, lines, engine=None, flush=None):
    """Run the REPL over ``lines`` with a mocked engine; return stdout."""
    replies = engine or (lambda db, cfg, tts, text, memory, language=None: f"echo: {text}")
    calls = []

    def fake_engine(db, cfg, tts, text, memory, language=None):
        calls.append({"text": text, "memory": memory})
        return replies(db, cfg, tts, text, memory, language)

    monkeypatch.setattr(chat_mod, "run_reply_engine", fake_engine)
    monkeypatch.setattr(chat_mod, "update_diary_from_dialogue_memory",
                        flush or (lambda *a, **k: None))
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))

    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    run_text_chat(db=object(), cfg=DummyCfg(), dialogue_memory=DummyMemory())
    return calls, out.getvalue()


@pytest.mark.unit
def test_each_line_reaches_the_engine_and_reply_is_printed(monkeypatch):
    calls, out = _run(monkeypatch, ["bonjour", "quelle heure est-il ?"])
    assert [c["text"] for c in calls] == ["bonjour", "quelle heure est-il ?"]
    assert "echo: bonjour" in out
    assert "echo: quelle heure est-il ?" in out


@pytest.mark.unit
def test_dialogue_memory_is_shared_across_turns(monkeypatch):
    calls, _ = _run(monkeypatch, ["un", "deux"])
    assert calls[0]["memory"] is calls[1]["memory"]


@pytest.mark.unit
def test_blank_lines_are_ignored(monkeypatch):
    calls, _ = _run(monkeypatch, ["", "   ", "vraie question"])
    assert [c["text"] for c in calls] == ["vraie question"]


@pytest.mark.unit
def test_engine_error_does_not_kill_the_session(monkeypatch):
    def engine(db, cfg, tts, text, memory, language=None):
        if text == "boom":
            raise RuntimeError("engine exploded")
        return "ok"

    calls, out = _run(monkeypatch, ["boom", "encore la ?"], engine=engine)
    # The session survived the failure and processed the next line
    assert [c["text"] for c in calls] == ["boom", "encore la ?"]
    assert "ok" in out


@pytest.mark.unit
def test_quit_command_ends_the_session_and_flushes_diary(monkeypatch):
    flushed = []
    calls, _ = _run(monkeypatch, ["salut", "/quit", "jamais vu"],
                    flush=lambda *a, **k: flushed.append(True) or None)
    assert [c["text"] for c in calls] == ["salut"]
    assert flushed  # diary flushed on exit so text chats feed memory


@pytest.mark.unit
def test_eof_flushes_diary_too(monkeypatch):
    flushed = []
    _run(monkeypatch, ["une question"],
         flush=lambda *a, **k: flushed.append(True) or None)
    assert flushed
