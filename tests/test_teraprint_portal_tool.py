"""Behaviour tests for the teraPrintPortal builtin tool.

The tool reads business data from a self-hosted TeraPrintPortal instance via
its key-protected `/api/jarvis` endpoint. All HTTP is mocked.
"""

import json

import pytest

import jarvis.tools.builtin.teraprint_portal as portal_mod
from jarvis.tools.builtin.teraprint_portal import TeraPrintPortalTool
from jarvis.tools.base import ToolContext


class DummyCfg:
    def __init__(self, base_url="https://app.example.com", key="key-123"):
        self.teraprint_base_url = base_url
        self.teraprint_api_key = key
        self.voice_debug = False


def _ctx(cfg):
    return ToolContext(
        db=None,
        cfg=cfg,
        system_prompt="",
        original_prompt="",
        redacted_text="",
        max_retries=0,
        user_print=lambda m: None,
    )


class MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


def _install_mock(monkeypatch, payload, status_code=200):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        return MockResponse(payload, status_code)

    monkeypatch.setattr(portal_mod.requests, "get", fake_get)
    return calls


@pytest.mark.unit
def test_unconfigured_returns_setup_guidance():
    tool = TeraPrintPortalTool()
    res = tool.run({"resource": "dashboard"}, _ctx(DummyCfg(base_url="", key="")))
    assert res.success is False
    assert "teraprint_base_url" in (res.reply_text or "")
    assert "teraprint_api_key" in (res.reply_text or "")


@pytest.mark.unit
def test_dashboard_hits_jarvis_endpoint_with_key(monkeypatch):
    calls = _install_mock(monkeypatch, {"revenue": 1200, "activeProjects": 3})
    res = TeraPrintPortalTool().run({"resource": "dashboard"}, _ctx(DummyCfg()))

    assert res.success is True
    assert "1200" in res.reply_text
    assert calls[0]["url"] == "https://app.example.com/api/jarvis"
    assert calls[0]["params"].get("resource") == "dashboard"
    assert calls[0]["headers"].get("x-api-key") == "key-123"


@pytest.mark.unit
def test_invalid_resource_lists_valid_ones():
    res = TeraPrintPortalTool().run({"resource": "bitcoin"}, _ctx(DummyCfg()))
    assert res.success is False
    assert "dashboard" in res.reply_text
    assert "invoices" in res.reply_text


@pytest.mark.unit
def test_forbidden_explains_key_problem(monkeypatch):
    _install_mock(monkeypatch, {"error": "Forbidden"}, status_code=403)
    res = TeraPrintPortalTool().run({"resource": "clients"}, _ctx(DummyCfg()))
    assert res.success is False
    assert "key" in res.reply_text.lower() or "403" in res.reply_text


@pytest.mark.unit
def test_missing_endpoint_explains_portal_setup(monkeypatch):
    _install_mock(monkeypatch, {"error": "Not found"}, status_code=404)
    res = TeraPrintPortalTool().run({"resource": "clients"}, _ctx(DummyCfg()))
    assert res.success is False
    assert "/api/jarvis" in res.reply_text


@pytest.mark.unit
def test_large_response_is_truncated(monkeypatch):
    _install_mock(monkeypatch, [{"name": f"client-{i}", "note": "x" * 100}
                                for i in range(500)])
    res = TeraPrintPortalTool().run({"resource": "clients"}, _ctx(DummyCfg()))
    assert res.success is True
    assert len(res.reply_text) < 10000


@pytest.mark.unit
def test_network_failure_is_honest(monkeypatch):
    import requests

    def fake_get(url, headers=None, params=None, timeout=None):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(portal_mod.requests, "get", fake_get)
    res = TeraPrintPortalTool().run({"resource": "dashboard"}, _ctx(DummyCfg()))
    assert res.success is False
    assert res.reply_text
