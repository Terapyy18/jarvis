# Text Chat Spec

## Purpose

`python -m jarvis.text_chat` gives Jarvis a typed conversation loop for
machines without a microphone (headless servers, remote sessions), and for
anyone who wants to talk to the assistant without speaking.

## Key principles

- **Same pipeline as voice.** Each typed line goes through
  `run_reply_engine`, exactly like a dispatched voice query: planner, tool
  routing, memory enrichment, dialogue memory, agentic loop. There is no
  separate text-only reply path to keep in sync.
- **One session, one dialogue memory.** A single `DialogueMemory` instance
  spans the whole session, so follow-up questions work without repeating
  context, just as they do after a wake word.
- **Text conversations feed long-term memory.** On exit the diary is
  flushed with `source_app="stdin"` and the fast model as graph picker, so
  a typed session produces diary entries and knowledge-graph facts like a
  spoken one.
- **A failed reply never ends the session.** Engine exceptions are
  reported on the line that caused them; the loop continues.
- **No TTS.** The engine is called with `tts=None` — a typed conversation
  answers in text.

## Session control

| Input | Behaviour |
|-------|-----------|
| Blank line | Ignored, prompt redrawn. |
| `/quit` | Ends the session (diary flushed). |
| EOF (Ctrl+Z ⏎ on Windows, Ctrl+D elsewhere) | Ends the session (diary flushed). |
| Ctrl+C | Ends the session (diary flushed). |

## Relationship to the daemon

The daemon (`jarvis.daemon`) owns the voice path: wake word, Whisper,
listener, TTS, dictation, and periodic diary checks. It reads stdin only
as a shutdown signal, so it cannot answer typed questions. Text chat is a
separate entry point that shares the reply engine, database, and memory
but starts no audio components — which is why it runs on a machine with no
microphone at all.
