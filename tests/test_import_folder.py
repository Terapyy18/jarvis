"""Behaviour tests for the knowledge folder importer.

The importer feeds a folder of markdown notes through the standard graph
pipeline (extract → place → merge). The pipeline itself is mocked — tests
verify chunking behaviour, document provenance framing, aggregation, and
fail-soft handling, not LLM output.
"""

import pytest

import jarvis.memory.import_folder as imp_mod
from jarvis.memory.import_folder import (
    chunk_markdown,
    iter_folder_documents,
    import_folder_into_graph,
)
from jarvis.memory.graph_ops import GraphUpdateResult


# ---------------------------------------------------------------------------
# chunk_markdown
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_small_document_is_a_single_chunk():
    text = "# Title\n\nSome short content."
    assert chunk_markdown(text, max_chars=3000) == [text]


@pytest.mark.unit
def test_chunks_respect_the_size_cap():
    sections = [f"## Section {i}\n\n" + ("x" * 400) for i in range(10)]
    text = "\n\n".join(sections)
    chunks = chunk_markdown(text, max_chars=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)


@pytest.mark.unit
def test_no_content_is_lost_by_chunking():
    sections = [f"## Section {i}\n\nfact number {i}" for i in range(20)]
    text = "\n\n".join(sections)
    chunks = chunk_markdown(text, max_chars=500)
    joined = "\n".join(chunks)
    for i in range(20):
        assert f"fact number {i}" in joined


@pytest.mark.unit
def test_oversized_single_section_is_still_split():
    text = "## Big\n\n" + "\n\n".join("paragraph " + str(i) + " " + "y" * 200
                                      for i in range(10))
    chunks = chunk_markdown(text, max_chars=600)
    assert len(chunks) > 1
    assert all(len(c) <= 600 for c in chunks)


# ---------------------------------------------------------------------------
# iter_folder_documents
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_folder_listing_takes_top_level_markdown_only(tmp_path):
    (tmp_path / "serveurs.md").write_text("# Serveurs", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.md").write_text("# Nested", encoding="utf-8")

    docs = iter_folder_documents(tmp_path)
    names = [p.name for p, _ in docs]
    assert names == ["serveurs.md"]


@pytest.mark.unit
def test_folder_listing_honours_excluded_names(tmp_path):
    (tmp_path / "serveurs.md").write_text("# Serveurs", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Instructions", encoding="utf-8")

    docs = iter_folder_documents(tmp_path, exclude_names=("CLAUDE.md",))
    names = [p.name for p, _ in docs]
    assert names == ["serveurs.md"]


# ---------------------------------------------------------------------------
# import_folder_into_graph
# ---------------------------------------------------------------------------

class DummyCfg:
    pass


def _install_pipeline_mock(monkeypatch, results=None, failures=()):
    """Replace the graph pipeline with a recorder."""
    calls = []

    def fake_update(store, summary, cfg, chat_model, timeout_sec=30.0,
                    thinking=False, date_utc=None, picker_model=None):
        calls.append({"summary": summary, "chat_model": chat_model,
                      "picker_model": picker_model})
        for marker in failures:
            if marker in summary:
                raise RuntimeError("extraction exploded")
        return results or GraphUpdateResult(
            stored=[("a fact", "User")], skipped=1)

    monkeypatch.setattr(imp_mod, "update_graph_from_dialogue", fake_update)
    return calls


@pytest.mark.unit
def test_each_chunk_is_framed_with_its_source_file(monkeypatch, tmp_path):
    (tmp_path / "serveurs.md").write_text(
        "# Serveurs\n\nLe serveur principal est un HP ProLiant.",
        encoding="utf-8")
    calls = _install_pipeline_mock(monkeypatch)

    result = import_folder_into_graph(
        store=object(), folder=tmp_path, cfg=DummyCfg(),
        chat_model="chat-model", picker_model="fast-model")

    assert len(calls) == 1
    # Provenance framing: the pipeline sees which notes file the text is from
    assert "serveurs.md" in calls[0]["summary"]
    assert "HP ProLiant" in calls[0]["summary"]
    assert calls[0]["picker_model"] == "fast-model"
    assert result.files == 1
    assert result.stored == 1
    assert result.skipped == 1


@pytest.mark.unit
def test_import_aggregates_across_files_and_chunks(monkeypatch, tmp_path):
    (tmp_path / "a.md").write_text("# A\n\n" + "x" * 4000, encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\ncontent", encoding="utf-8")
    calls = _install_pipeline_mock(monkeypatch)

    result = import_folder_into_graph(
        store=object(), folder=tmp_path, cfg=DummyCfg(),
        chat_model="chat-model", max_chunk_chars=3000)

    assert result.files == 2
    assert result.chunks == len(calls)
    assert result.chunks >= 3  # a.md split into at least 2 + b.md
    assert result.stored == result.chunks  # one stored fact per mocked call


@pytest.mark.unit
def test_one_broken_file_does_not_abort_the_import(monkeypatch, tmp_path):
    (tmp_path / "bad.md").write_text("# Bad\n\nboom-marker", encoding="utf-8")
    (tmp_path / "good.md").write_text("# Good\n\nfine", encoding="utf-8")
    calls = _install_pipeline_mock(monkeypatch, failures=("boom-marker",))

    result = import_folder_into_graph(
        store=object(), folder=tmp_path, cfg=DummyCfg(),
        chat_model="chat-model")

    # Both files were attempted; the failure is counted, not fatal
    assert result.files == 2
    assert result.failures == 1
    assert any("good.md" in c["summary"] for c in calls)
