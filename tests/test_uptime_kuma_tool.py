"""Behaviour tests for the uptimeKuma builtin tool.

The tool talks to a self-hosted Uptime Kuma instance through the
`uptime-kuma-api` socket.io client. The client class is faked — tests
verify observable behaviour (reply text, success flag, which monitor an
action landed on), not internals.
"""

import pytest

import jarvis.tools.builtin.uptime_kuma as kuma_mod
from jarvis.tools.builtin.uptime_kuma import UptimeKumaTool
from jarvis.tools.base import ToolContext


class DummyCfg:
    def __init__(self, base_url="http://kuma.example.com:3002",
                 username="admin", password="s3cret!"):
        self.kuma_base_url = base_url
        self.kuma_username = username
        self.kuma_password = password
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


MONITORS = [
    {"id": 1, "name": "VoltPack", "active": True, "type": "http",
     "url": "https://voltpack.fr"},
    {"id": 2, "name": "Portfolio", "active": True, "type": "http",
     "url": "https://theodumontet.fr"},
    {"id": 3, "name": "Navidrome", "active": False, "type": "http",
     "url": "https://navidrome.example.com"},
]

HEARTBEATS = {
    1: [{"status": 0, "ping": None, "msg": "old"},
        {"status": 1, "ping": 12, "msg": ""}],
    2: [{"status": 0, "ping": None, "msg": "timeout of 48000ms exceeded"}],
}

# Kuma's uptimeList sends fractions of 1 (1 = 100% up), not percentages.
UPTIME = {1: {24: 1, 720: 0.999}, 2: {24: 0, 720: 0.875}}


class FakeKumaApi:
    """Stands in for uptime_kuma_api.UptimeKumaApi."""

    instances = []

    def __init__(self, url, timeout=None, **kwargs):
        self.url = url
        self.login_args = None
        self.actions = []
        self.disconnected = False
        FakeKumaApi.instances.append(self)

    def login(self, username, password):
        self.login_args = (username, password)
        return {"token": "tok"}

    def get_monitors(self):
        return [dict(m) for m in MONITORS]

    def get_heartbeats(self):
        return {k: [dict(b) for b in v] for k, v in HEARTBEATS.items()}

    def uptime(self):
        return {k: dict(v) for k, v in UPTIME.items()}

    def pause_monitor(self, monitor_id):
        self.actions.append(("pause", monitor_id))
        return {"msg": "Paused Successfully."}

    def resume_monitor(self, monitor_id):
        self.actions.append(("resume", monitor_id))
        return {"msg": "Resumed Successfully."}

    def disconnect(self):
        self.disconnected = True


@pytest.fixture(autouse=True)
def _fresh_fake(monkeypatch):
    FakeKumaApi.instances = []
    monkeypatch.setattr(kuma_mod, "UptimeKumaApi", FakeKumaApi)
    yield


@pytest.mark.unit
def test_unconfigured_returns_setup_guidance():
    res = UptimeKumaTool().run(
        {"action": "status"},
        _ctx(DummyCfg(base_url="", username="", password="")),
    )
    assert res.success is False
    assert "kuma_base_url" in (res.reply_text or "")
    assert "kuma_username" in (res.reply_text or "")
    assert "kuma_password" in (res.reply_text or "")


@pytest.mark.unit
def test_missing_client_library_is_honest(monkeypatch):
    monkeypatch.setattr(kuma_mod, "UptimeKumaApi", None)
    res = UptimeKumaTool().run({"action": "status"}, _ctx(DummyCfg()))
    assert res.success is False
    assert "uptime-kuma-api" in (res.reply_text or "")


@pytest.mark.unit
def test_status_reports_up_down_and_paused_states():
    res = UptimeKumaTool().run({"action": "status"}, _ctx(DummyCfg()))

    assert res.success is True
    text = res.reply_text or ""
    # Every monitor is present with an unambiguous state
    assert "VoltPack" in text and "UP" in text
    assert "Portfolio" in text and "DOWN" in text
    assert "Navidrome" in text and "PAUSED" in text
    # Uptime fractions surface as human percentages so the model can
    # answer "how stable is X?" (0.999 → 99.9%, 1 → 100%)
    assert "99.9%" in text
    assert "100" in text and "1.0%" not in text
    # The session logged in with the configured credentials and closed cleanly
    api = FakeKumaApi.instances[0]
    assert api.login_args == ("admin", "s3cret!")
    assert api.disconnected is True


@pytest.mark.unit
def test_status_can_focus_a_single_monitor():
    res = UptimeKumaTool().run(
        {"action": "status", "monitor": "portfolio"}, _ctx(DummyCfg()))

    assert res.success is True
    text = res.reply_text or ""
    assert "Portfolio" in text
    assert "VoltPack" not in text


@pytest.mark.unit
def test_pause_resolves_spoken_name_to_monitor_id():
    res = UptimeKumaTool().run(
        {"action": "pause", "monitor": "voltpack"}, _ctx(DummyCfg()))

    assert res.success is True
    api = FakeKumaApi.instances[0]
    assert ("pause", 1) in api.actions


@pytest.mark.unit
def test_resume_resolves_spoken_name_to_monitor_id():
    res = UptimeKumaTool().run(
        {"action": "resume", "monitor": "Navidrome"}, _ctx(DummyCfg()))

    assert res.success is True
    api = FakeKumaApi.instances[0]
    assert ("resume", 3) in api.actions


@pytest.mark.unit
def test_unknown_monitor_lists_available_names():
    res = UptimeKumaTool().run(
        {"action": "pause", "monitor": "nonexistent"}, _ctx(DummyCfg()))

    assert res.success is False
    # Honest failure: name every known monitor so the model can retry sensibly
    for name in ("VoltPack", "Portfolio", "Navidrome"):
        assert name in (res.reply_text or "")


@pytest.mark.unit
def test_pause_requires_a_monitor():
    res = UptimeKumaTool().run({"action": "pause"}, _ctx(DummyCfg()))
    assert res.success is False


@pytest.mark.unit
def test_connection_failure_is_honest_and_never_leaks_password(monkeypatch):
    class ExplodingApi(FakeKumaApi):
        def login(self, username, password):
            raise ConnectionError("Connection refused")

    monkeypatch.setattr(kuma_mod, "UptimeKumaApi", ExplodingApi)
    cfg = DummyCfg()
    res = UptimeKumaTool().run({"action": "status"}, _ctx(cfg))

    assert res.success is False
    assert res.reply_text  # honest, human-readable failure
    assert cfg.kuma_password not in (res.reply_text or "")


@pytest.mark.unit
def test_invalid_action_is_rejected():
    res = UptimeKumaTool().run({"action": "explode"}, _ctx(DummyCfg()))
    assert res.success is False
