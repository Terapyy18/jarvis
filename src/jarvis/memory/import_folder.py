"""Import a folder of markdown notes into the knowledge graph.

Users who keep a personal notes folder (infrastructure docs, project
notes, profiles) can bootstrap the knowledge graph from it instead of
waiting for facts to surface in conversation. Each file is chunked on
markdown headings and fed through the standard graph pipeline
(``update_graph_from_dialogue``: extract → classify → place → merge), so
imported knowledge gets the same branch routing, dedupe, and consolidation
as conversational learning. See the "Import from Folder" section of
graph.spec.md.

Run as a CLI:

    python -m jarvis.memory.import_folder <folder> [--exclude NAME ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Collection, List, NamedTuple, Optional, Tuple

from ..debug import debug_log
from .graph import GraphMemoryStore
from .graph_ops import update_graph_from_dialogue

_DEFAULT_MAX_CHUNK_CHARS = 3000

# Per-chunk LLM budget. Extraction reads a few thousand chars and emits a
# short JSON list; 60s covers a cold small model without stalling the whole
# import on one wedged call.
_CHUNK_TIMEOUT_SEC = 60.0


class ImportResult(NamedTuple):
    """Aggregated outcome of a folder import."""

    files: int
    chunks: int
    stored: int
    skipped: int
    failures: int


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _split_oversized(block: str, max_chars: int) -> List[str]:
    """Split one oversized block on paragraph gaps, hard-splitting as a
    last resort so no single chunk can exceed ``max_chars``."""
    parts: List[str] = []
    current = ""
    for para in block.split("\n\n"):
        while len(para) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.append(para[:max_chars])
            para = para[max_chars:]
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > max_chars:
            parts.append(current)
            current = para
        else:
            current = candidate
    if current.strip():
        parts.append(current)
    return parts


def chunk_markdown(text: str, max_chars: int = _DEFAULT_MAX_CHUNK_CHARS) -> List[str]:
    """Split markdown into chunks of at most ``max_chars`` characters.

    Sections start at heading lines so a chunk keeps its local context;
    consecutive small sections are packed together, and a section larger
    than the cap is split on paragraphs.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sections: List[str] = []
    current_lines: List[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#") and current_lines:
            sections.append("\n".join(current_lines))
            current_lines = []
        current_lines.append(line)
    if current_lines:
        sections.append("\n".join(current_lines))

    chunks: List[str] = []
    current = ""
    for section in sections:
        if len(section) > max_chars:
            if current.strip():
                chunks.append(current)
                current = ""
            chunks.extend(_split_oversized(section, max_chars))
            continue
        candidate = f"{current}\n\n{section}" if current else section
        if len(candidate) > max_chars:
            chunks.append(current)
            current = section
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Folder walking
# ---------------------------------------------------------------------------

def iter_folder_documents(
    folder: Path,
    exclude_names: Collection[str] = (),
) -> List[Tuple[Path, str]]:
    """Top-level ``*.md`` files of ``folder`` with their text content.

    Non-recursive by design: subfolders of a notes directory typically hold
    attachments, archives, or tooling state rather than knowledge notes.
    ``exclude_names`` filters exact file names (case-insensitive).
    """
    excluded = {name.lower() for name in exclude_names}
    docs: List[Tuple[Path, str]] = []
    for path in sorted(Path(folder).glob("*.md")):
        if not path.is_file() or path.name.lower() in excluded:
            continue
        try:
            docs.append((path, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as e:
            debug_log(f"folder import: cannot read {path.name}: {e}", "memory")
    return docs


# ---------------------------------------------------------------------------
# Import orchestration
# ---------------------------------------------------------------------------

def import_folder_into_graph(
    store,
    folder: Path,
    cfg,
    *,
    chat_model: str,
    picker_model: Optional[str] = None,
    max_chunk_chars: int = _DEFAULT_MAX_CHUNK_CHARS,
    exclude_names: Collection[str] = (),
    progress: Optional[Callable[[str], None]] = None,
) -> ImportResult:
    """Feed every markdown note of ``folder`` through the graph pipeline.

    Fail-soft: a chunk whose extraction/placement raises is counted as a
    failure and the import moves on — one broken file must not abort the
    bootstrap of everything else.
    """
    say = progress or (lambda _msg: None)
    docs = iter_folder_documents(folder, exclude_names=exclude_names)

    files = chunks_total = stored_total = skipped_total = failures = 0
    for path, text in docs:
        files += 1
        chunks = chunk_markdown(text, max_chars=max_chunk_chars)
        say(f"  📄 {path.name} ({len(chunks)} chunk(s))")
        for index, chunk in enumerate(chunks, start=1):
            chunks_total += 1
            part = f" (part {index}/{len(chunks)})" if len(chunks) > 1 else ""
            summary = (
                "Notes the user keeps in their personal knowledge folder, "
                f"file '{path.name}'{part}:\n\n{chunk}"
            )
            try:
                result = update_graph_from_dialogue(
                    store,
                    summary,
                    cfg,
                    chat_model,
                    timeout_sec=_CHUNK_TIMEOUT_SEC,
                    thinking=False,
                    picker_model=picker_model,
                )
            except Exception as e:
                failures += 1
                debug_log(
                    f"folder import: chunk {index} of {path.name} failed: {e}",
                    "memory",
                )
                say(f"    ⚠️ chunk {index} failed: {e}")
                continue
            stored_total += len(result.stored)
            skipped_total += result.skipped
            if result.stored:
                say(f"    ✅ learned {len(result.stored)} fact(s)"
                    + (f" ({result.skipped} duplicate(s) skipped)"
                       if result.skipped else ""))
            else:
                say(f"    ➖ nothing new ({result.skipped} duplicate(s) skipped)")

    return ImportResult(
        files=files,
        chunks=chunks_total,
        stored=stored_total,
        skipped=skipped_total,
        failures=failures,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    from ..config import load_settings
    from ..llm.tiers import Tier, resolve_model

    parser = argparse.ArgumentParser(
        prog="python -m jarvis.memory.import_folder",
        description="Import a folder of markdown notes into the knowledge graph.",
    )
    parser.add_argument("folder", help="Folder containing *.md notes (top level only)")
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="NAME",
        help="File name to skip (repeatable), e.g. --exclude CLAUDE.md",
    )
    args = parser.parse_args(argv)

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"❌ Not a folder: {folder}")
        return 1

    cfg = load_settings()
    store = GraphMemoryStore(cfg.db_path)
    chat_model = resolve_model(cfg, Tier.CHAT)
    picker_model = resolve_model(cfg, Tier.FAST)

    print(f"📥 Importing knowledge from {folder}")
    print(f"  🧠 extraction model: {chat_model} | picker: {picker_model}")
    result = import_folder_into_graph(
        store,
        folder,
        cfg,
        chat_model=chat_model,
        picker_model=picker_model,
        exclude_names=args.exclude,
        progress=print,
    )
    print(
        f"🎉 Done: {result.files} file(s), {result.chunks} chunk(s), "
        f"{result.stored} fact(s) learned, {result.skipped} duplicate(s) "
        f"skipped, {result.failures} failure(s)"
    )
    return 0 if result.failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
