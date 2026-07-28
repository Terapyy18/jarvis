"""Uptime Kuma tool — monitor and control the user's self-hosted Uptime Kuma.

Uptime Kuma is a self-hostable monitoring tool; the user points Jarvis at
their own instance (``kuma_base_url`` + ``kuma_username`` +
``kuma_password``), so the whole path stays on infrastructure the user
owns. Kuma v1 exposes its control surface over socket.io, wrapped here by
the ``uptime-kuma-api`` client. See uptime_kuma.spec.md.
"""

from typing import Any, Dict, List, Optional

from ...debug import debug_log
from ..base import Tool, ToolContext
from ..types import ToolExecutionResult

try:
    from uptime_kuma_api import UptimeKumaApi
except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
    UptimeKumaApi = None


_ACTIONS = ("status", "pause", "resume")

# Actions that operate on a specific monitor.
_TARGET_ACTIONS = frozenset({"pause", "resume"})

_TIMEOUT_SEC = 15

# Kuma heartbeat status codes → human-readable state.
_BEAT_STATES = {0: "DOWN", 1: "UP", 2: "PENDING", 3: "MAINTENANCE"}


class UptimeKumaTool(Tool):
    """Talk to a self-hosted Uptime Kuma instance over its socket.io API."""

    @property
    def name(self) -> str:
        return "uptimeKuma"

    @property
    def description(self) -> str:
        return (
            "Check and control the user's own Uptime Kuma instance "
            "(self-hosted monitoring). Use for anything about whether the "
            "user's sites, services, or containers are up, down, or healthy: "
            "'is everything green?', 'is <site> up?', 'how stable is <x>?', "
            "'pause monitoring for <x>', 'resume monitoring for <x>'. "
            "Action 'status' reports every monitor with its state, uptime "
            "percentages, and latency. Never guess a monitor name — pass "
            "what the user said and the tool resolves it."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(_ACTIONS),
                    "description": (
                        "What to do. 'status' = state of all monitors "
                        "(default). 'pause'/'resume' act on one monitor and "
                        "require 'monitor'."
                    ),
                },
                "monitor": {
                    "type": "string",
                    "description": (
                        "Monitor to target, as the user named it (name, URL, "
                        "or id). Required for pause/resume; optional for "
                        "status to focus one monitor."
                    ),
                },
            },
            "required": [],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_monitor(query: str,
                         monitors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Match a user-spoken name against known monitors.

        Case-insensitive; exact id/name match wins, then substring match on
        name or URL. Kept deliberately simple and language-agnostic.
        """
        q = query.strip().lower()
        if not q:
            return None
        for m in monitors:
            if q in (str(m.get("id", "")).lower(), str(m.get("name", "")).lower()):
                return m
        for m in monitors:
            haystack = f"{m.get('name', '')} {m.get('url', '')}".lower()
            if q in haystack:
                return m
        return None

    @staticmethod
    def _last_beat_state(monitor: Dict[str, Any],
                         heartbeats: Dict[Any, Any]) -> Optional[str]:
        """State of the monitor's most recent heartbeat, if any."""
        mid = monitor.get("id")
        beats = heartbeats.get(mid) or heartbeats.get(str(mid)) or []
        if not beats:
            return None
        try:
            status = int(beats[-1].get("status"))
        except (TypeError, ValueError):
            return None
        return _BEAT_STATES.get(status, f"status={status}")

    @staticmethod
    def _uptime_bits(monitor: Dict[str, Any], uptimes: Dict[Any, Any]) -> str:
        # Kuma's uptimeList sends fractions of 1 (1 = 100% up).
        mid = monitor.get("id")
        entry = uptimes.get(mid) or uptimes.get(str(mid)) or {}
        bits = []
        for hours, label in ((24, "24h"), (720, "30d")):
            value = entry.get(hours)
            if value is None:
                value = entry.get(str(hours))
            if value is not None:
                bits.append(f"{label}={round(float(value) * 100, 2)}%")
        return " ".join(bits)

    def _summarise(self, monitors: List[Dict[str, Any]],
                   heartbeats: Dict[Any, Any],
                   uptimes: Dict[Any, Any]) -> str:
        lines = []
        for m in monitors:
            bits = [str(m.get("name", "?"))]
            if not m.get("active", True):
                bits.append("PAUSED")
            else:
                state = self._last_beat_state(m, heartbeats)
                bits.append(state or "no heartbeat yet")
                beats = heartbeats.get(m.get("id")) or heartbeats.get(str(m.get("id"))) or []
                if beats:
                    last = beats[-1]
                    ping = last.get("ping")
                    if ping is not None:
                        bits.append(f"ping {ping}ms")
                    msg = str(last.get("msg") or "").strip()
                    if msg and state == "DOWN":
                        bits.append(f"reason: {msg}")
            uptime = self._uptime_bits(m, uptimes)
            if uptime:
                bits.append(f"uptime {uptime}")
            url = m.get("url")
            if url:
                bits.append(str(url))
            lines.append("  - " + " | ".join(bits))
        return "\n".join(lines) if lines else "  (none)"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        cfg = context.cfg
        base = getattr(cfg, "kuma_base_url", "") or ""
        username = getattr(cfg, "kuma_username", "") or ""
        password = getattr(cfg, "kuma_password", "") or ""
        if not base.strip() or not username.strip() or not password.strip():
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    "Uptime Kuma is not configured. The user must set "
                    "'kuma_base_url' (their Uptime Kuma instance URL), "
                    "'kuma_username' and 'kuma_password' (an Uptime Kuma "
                    "account) in Jarvis settings. Tell the user how to "
                    "enable it; do not retry."
                ),
            )

        if UptimeKumaApi is None:
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    "The 'uptime-kuma-api' Python package is not installed, "
                    "so Jarvis cannot talk to Uptime Kuma. The user must "
                    "reinstall Jarvis dependencies (pip install -r "
                    "requirements.txt). Tell the user; do not retry."
                ),
            )

        action = str((args or {}).get("action") or "status").strip().lower()
        target_query = str((args or {}).get("monitor") or "").strip()

        if action not in _ACTIONS:
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    f"Unknown uptimeKuma action '{action}'. "
                    f"Valid actions: {', '.join(_ACTIONS)}."
                ),
            )

        if action in _TARGET_ACTIONS and not target_query:
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    f"Action '{action}' needs a 'monitor' argument naming "
                    "which monitor to act on."
                ),
            )

        context.user_print(f"📡 Uptime Kuma: {action}"
                           + (f" → {target_query}" if target_query else ""))
        debug_log(f"uptime kuma action={action} target='{target_query}'", "tools")

        api = None
        try:
            api = UptimeKumaApi(base.strip(), timeout=_TIMEOUT_SEC)
            api.login(username, password)

            monitors = api.get_monitors()
            monitors = [m for m in monitors if isinstance(m, dict)]

            if action == "status":
                if target_query:
                    target = self._resolve_monitor(target_query, monitors)
                    if target is None:
                        names = ", ".join(
                            str(m.get("name", "?")) for m in monitors) or "(none)"
                        return ToolExecutionResult(
                            success=False,
                            reply_text=(
                                f"No monitor matches '{target_query}'. "
                                f"Available: {names}."
                            ),
                        )
                    monitors = [target]

                # Fail-soft per data source: a broken heartbeat/uptime feed
                # must not hide the monitor list itself.
                heartbeats: Dict[Any, Any] = {}
                uptimes: Dict[Any, Any] = {}
                try:
                    heartbeats = api.get_heartbeats() or {}
                except Exception as e:
                    debug_log(f"uptime kuma heartbeats failed: {e}", "tools")
                try:
                    uptimes = api.uptime() or {}
                except Exception as e:
                    debug_log(f"uptime kuma uptime failed: {e}", "tools")

                text = ("Uptime Kuma monitors on the user's server:\n"
                        + self._summarise(monitors, heartbeats, uptimes))
                context.user_print(f"✅ {len(monitors)} monitor(s) reported")
                return ToolExecutionResult(success=True, reply_text=text)

            # Target actions: pause / resume
            target = self._resolve_monitor(target_query, monitors)
            if target is None:
                names = ", ".join(str(m.get("name", "?")) for m in monitors) or "(none)"
                return ToolExecutionResult(
                    success=False,
                    reply_text=(
                        f"No monitor matches '{target_query}'. "
                        f"Available: {names}."
                    ),
                )

            monitor_id = target.get("id")
            name = target.get("name", monitor_id)
            if action == "pause":
                result = api.pause_monitor(monitor_id)
            else:
                result = api.resume_monitor(monitor_id)

            message = str((result or {}).get("msg") or "").strip() \
                if isinstance(result, dict) else ""
            context.user_print(f"✅ {action} requested for {name}")
            debug_log(f"uptime kuma {action} ok for monitor {monitor_id}", "tools")
            return ToolExecutionResult(
                success=True,
                reply_text=(
                    f"Uptime Kuma accepted '{action}' for monitor "
                    f"'{name}'. {message}"
                ).strip(),
            )

        except Exception as e:
            debug_log(f"uptime kuma error: {type(e).__name__}: {e}", "tools")
            context.user_print("⚠️ Uptime Kuma request failed")
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    "Could not complete the Uptime Kuma request "
                    f"({type(e).__name__}). The instance may be down, "
                    "'kuma_base_url' may be wrong, or the credentials may "
                    "be invalid."
                ),
            )
        finally:
            if api is not None:
                try:
                    api.disconnect()
                except Exception:
                    pass
