"""Behaviour tests for the coolify builtin tool.

The tool talks to a self-hosted Coolify instance over its REST API. All HTTP
is mocked — tests verify observable behaviour (reply text, success flag,
request targets), not internals.
"""

import json

import pytest

import jarvis.tools.builtin.coolify as coolify_mod
from jarvis.tools.builtin.coolify import CoolifyTool
from jarvis.tools.base import ToolContext


class DummyCfg:
    def __init__(self, base_url="https://coolify.example.com", token="tok-123"):
        self.coolify_base_url = base_url
        self.coolify_api_token = token
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


APPS = [
    {"uuid": "abc-1", "name": "teraprintportal", "status": "running:healthy",
     "fqdn": "https://app.example.com"},
    {"uuid": "abc-2", "name": "blog", "status": "exited",
     "fqdn": "https://blog.example.com"},
]

SERVICES = [
    {"uuid": "svc-1", "name": "umami", "status": "running"},
]


def _install_mock(monkeypatch, handler):
    calls = []

    def fake_request(method, url, headers=None, params=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers or {},
                      "params": params or {}})
        return handler(method, url, params or {})

    monkeypatch.setattr(coolify_mod.requests, "request", fake_request)
    return calls


@pytest.mark.unit
def test_unconfigured_returns_setup_guidance():
    tool = CoolifyTool()
    res = tool.run({"action": "status"}, _ctx(DummyCfg(base_url="", token="")))
    assert res.success is False
    assert "coolify_base_url" in (res.reply_text or "")
    assert "coolify_api_token" in (res.reply_text or "")


@pytest.mark.unit
def test_status_lists_applications_and_services(monkeypatch):
    def handler(method, url, params):
        if url.endswith("/applications"):
            return MockResponse(APPS)
        if url.endswith("/services"):
            return MockResponse(SERVICES)
        return MockResponse({}, 404)

    calls = _install_mock(monkeypatch, handler)
    res = CoolifyTool().run({"action": "status"}, _ctx(DummyCfg()))

    assert res.success is True
    assert "teraprintportal" in res.reply_text
    assert "running:healthy" in res.reply_text
    assert "umami" in res.reply_text
    # Bearer token must be sent on every request
    assert all(c["headers"].get("Authorization") == "Bearer tok-123" for c in calls)


@pytest.mark.unit
def test_app_name_resolves_to_uuid_for_deploy(monkeypatch):
    def handler(method, url, params):
        if url.endswith("/applications"):
            return MockResponse(APPS)
        if url.endswith("/deploy"):
            return MockResponse({"deployments": [{"message": "Deployment queued.",
                                                  "resource_uuid": "abc-1"}]})
        return MockResponse({}, 404)

    calls = _install_mock(monkeypatch, handler)
    res = CoolifyTool().run({"action": "deploy", "app": "portal"}, _ctx(DummyCfg()))

    assert res.success is True
    deploy_calls = [c for c in calls if c["url"].endswith("/deploy")]
    assert deploy_calls and deploy_calls[0]["params"].get("uuid") == "abc-1"


@pytest.mark.unit
def test_unknown_app_lists_available_names(monkeypatch):
    def handler(method, url, params):
        if url.endswith("/applications"):
            return MockResponse(APPS)
        if url.endswith("/services"):
            return MockResponse(SERVICES)
        return MockResponse({}, 404)

    _install_mock(monkeypatch, handler)
    res = CoolifyTool().run({"action": "restart", "app": "nonexistent"},
                            _ctx(DummyCfg()))

    assert res.success is False
    # Honest failure: name every known target so the model can retry sensibly
    assert "teraprintportal" in res.reply_text
    assert "blog" in res.reply_text


@pytest.mark.unit
def test_restart_hits_application_lifecycle_endpoint(monkeypatch):
    def handler(method, url, params):
        if url.endswith("/applications"):
            return MockResponse(APPS)
        if url.endswith("/applications/abc-2/restart"):
            return MockResponse({"message": "Restart request queued."})
        return MockResponse({}, 404)

    calls = _install_mock(monkeypatch, handler)
    res = CoolifyTool().run({"action": "restart", "app": "blog"}, _ctx(DummyCfg()))

    assert res.success is True
    assert any(c["url"].endswith("/applications/abc-2/restart") for c in calls)


@pytest.mark.unit
def test_service_resolves_for_lifecycle_actions(monkeypatch):
    def handler(method, url, params):
        if url.endswith("/applications"):
            return MockResponse(APPS)
        if url.endswith("/services"):
            return MockResponse(SERVICES)
        if url.endswith("/services/svc-1/restart"):
            return MockResponse({"message": "Service restart queued."})
        return MockResponse({}, 404)

    calls = _install_mock(monkeypatch, handler)
    res = CoolifyTool().run({"action": "restart", "app": "umami"}, _ctx(DummyCfg()))

    assert res.success is True
    assert any(c["url"].endswith("/services/svc-1/restart") for c in calls)


@pytest.mark.unit
def test_deploy_requires_a_target(monkeypatch):
    _install_mock(monkeypatch, lambda m, u, p: MockResponse(APPS))
    res = CoolifyTool().run({"action": "deploy"}, _ctx(DummyCfg()))
    assert res.success is False


@pytest.mark.unit
def test_http_failure_is_honest(monkeypatch):
    import requests

    def fake_request(method, url, headers=None, params=None, timeout=None):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(coolify_mod.requests, "request", fake_request)
    res = CoolifyTool().run({"action": "status"}, _ctx(DummyCfg()))
    assert res.success is False
    assert res.reply_text  # honest, human-readable failure


@pytest.mark.unit
def test_invalid_action_is_rejected():
    res = CoolifyTool().run({"action": "explode"}, _ctx(DummyCfg()))
    assert res.success is False
