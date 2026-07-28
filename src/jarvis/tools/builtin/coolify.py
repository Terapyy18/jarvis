"""Coolify tool — monitor and control the user's self-hosted Coolify server.

Coolify is a self-hostable deployment platform; the user points Jarvis at
their own instance (``coolify_base_url`` + ``coolify_api_token``), so the
whole path stays on infrastructure the user owns. See coolify.spec.md.
"""

import requests
from typing import Any, Dict, List, Optional, Tuple

from ...debug import debug_log
from ..base import Tool, ToolContext
from ..types import ToolExecutionResult


_ACTIONS = (
    "status", "list_apps", "list_services", "list_servers", "list_databases",
    "deployments", "deploy", "restart", "start", "stop",
)

# Actions that operate on a specific application or service.
_TARGET_ACTIONS = frozenset({"deploy", "restart", "start", "stop"})

_TIMEOUT_SEC = 20


class CoolifyTool(Tool):
    """Talk to a self-hosted Coolify instance over its REST API."""

    @property
    def name(self) -> str:
        return "coolify"

    @property
    def description(self) -> str:
        return (
            "Monitor and control the user's own Coolify server (self-hosted "
            "deployment platform). Use for anything about the user's server, "
            "deployments, or hosted apps/sites: 'is my server ok?', 'is "
            "<app> running?', 'deploy <app>', 'restart <app>'. Action "
            "'status' gives an overview of every application and service "
            "with its state. Never guess an app name — pass what the user "
            "said and the tool resolves it."
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
                        "What to do. 'status' = overview of all apps and "
                        "services (default). 'deployments' = currently "
                        "running deployments. 'deploy'/'restart'/'start'/"
                        "'stop' act on one app or service and require 'app'."
                    ),
                },
                "app": {
                    "type": "string",
                    "description": (
                        "Application or service to target, as the user "
                        "named it (name, domain, or uuid). Required for "
                        "deploy/restart/start/stop."
                    ),
                },
            },
            "required": [],
        }

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _request(self, cfg, method: str, path: str,
                 params: Optional[Dict[str, Any]] = None) -> Any:
        base = getattr(cfg, "coolify_base_url", "").rstrip("/")
        token = getattr(cfg, "coolify_api_token", "")
        url = f"{base}/api/v1{path}"
        resp = requests.request(
            method, url,
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/json"},
            params=params or {},
            timeout=_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {}

    def _fetch_targets(self, cfg) -> List[Dict[str, Any]]:
        """All applications and services, tagged with their resource kind."""
        targets: List[Dict[str, Any]] = []
        for kind, path in (("application", "/applications"),
                           ("service", "/services")):
            # Fail-soft per listing: one broken endpoint (e.g. no services
            # on this instance) must not hide the other resources.
            try:
                items = self._request(cfg, "GET", path)
            except requests.exceptions.HTTPError as e:
                debug_log(f"coolify listing {path} failed: {e}", "tools")
                continue
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        item = dict(item)
                        item["_kind"] = kind
                        targets.append(item)
        return targets

    @staticmethod
    def _resolve_target(query: str,
                        targets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Match a user-spoken name against known apps/services.

        Case-insensitive; exact uuid/name match wins, then substring match
        on name or domain. Kept deliberately simple and language-agnostic.
        """
        q = query.strip().lower()
        if not q:
            return None
        for t in targets:
            if q in (str(t.get("uuid", "")).lower(), str(t.get("name", "")).lower()):
                return t
        for t in targets:
            haystack = f"{t.get('name', '')} {t.get('fqdn', '')}".lower()
            if q in haystack:
                return t
        return None

    @staticmethod
    def _summarise(targets: List[Dict[str, Any]]) -> str:
        lines = []
        for t in targets:
            bits = [str(t.get("name", "?"))]
            status = t.get("status")
            if status:
                bits.append(f"status={status}")
            fqdn = t.get("fqdn")
            if fqdn:
                bits.append(str(fqdn))
            bits.append(f"[{t.get('_kind', 'resource')}]")
            lines.append("  - " + " | ".join(bits))
        return "\n".join(lines) if lines else "  (none)"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        cfg = context.cfg
        base = getattr(cfg, "coolify_base_url", "") or ""
        token = getattr(cfg, "coolify_api_token", "") or ""
        if not base.strip() or not token.strip():
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    "Coolify is not configured. The user must set "
                    "'coolify_base_url' (their Coolify instance URL) and "
                    "'coolify_api_token' (an API token from Coolify → Keys & "
                    "Tokens → API tokens) in Jarvis settings. Tell the user "
                    "how to enable it; do not retry."
                ),
            )

        action = str((args or {}).get("action") or "status").strip().lower()
        target_query = str((args or {}).get("app") or "").strip()

        if action not in _ACTIONS:
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    f"Unknown coolify action '{action}'. "
                    f"Valid actions: {', '.join(_ACTIONS)}."
                ),
            )

        context.user_print(f"🚀 Coolify: {action}"
                           + (f" → {target_query}" if target_query else ""))
        debug_log(f"coolify action={action} target='{target_query}'", "tools")

        try:
            if action in ("status", "list_apps", "list_services"):
                targets = self._fetch_targets(cfg)
                if action == "list_apps":
                    targets = [t for t in targets if t["_kind"] == "application"]
                elif action == "list_services":
                    targets = [t for t in targets if t["_kind"] == "service"]
                text = ("Coolify resources on the user's server:\n"
                        + self._summarise(targets))
                context.user_print(f"✅ {len(targets)} resource(s) found")
                return ToolExecutionResult(success=True, reply_text=text)

            if action in ("list_servers", "list_databases"):
                path = "/servers" if action == "list_servers" else "/databases"
                items = self._request(cfg, "GET", path)
                lines = []
                for item in items if isinstance(items, list) else []:
                    name = item.get("name", "?")
                    desc = item.get("description") or ""
                    status = item.get("status") or ""
                    ip = item.get("ip") or ""
                    lines.append("  - " + " | ".join(
                        b for b in (str(name), str(status), str(ip), str(desc)) if b))
                label = "Servers" if action == "list_servers" else "Databases"
                return ToolExecutionResult(
                    success=True,
                    reply_text=f"{label}:\n" + ("\n".join(lines) or "  (none)"),
                )

            if action == "deployments":
                items = self._request(cfg, "GET", "/deployments")
                lines = []
                for item in items if isinstance(items, list) else []:
                    lines.append(
                        f"  - {item.get('application_name', item.get('deployment_uuid', '?'))}"
                        f" | status={item.get('status', '?')}"
                    )
                return ToolExecutionResult(
                    success=True,
                    reply_text="Deployments in progress:\n"
                               + ("\n".join(lines) or "  (none running)"),
                )

            # Target actions: deploy / restart / start / stop
            if not target_query:
                return ToolExecutionResult(
                    success=False,
                    reply_text=(
                        f"Action '{action}' needs an 'app' argument naming "
                        "which application or service to act on."
                    ),
                )

            targets = self._fetch_targets(cfg)
            target = self._resolve_target(target_query, targets)
            if target is None:
                names = ", ".join(str(t.get("name", "?")) for t in targets) or "(none)"
                return ToolExecutionResult(
                    success=False,
                    reply_text=(
                        f"No application or service matches '{target_query}'. "
                        f"Available: {names}."
                    ),
                )

            uuid = target.get("uuid")
            kind = target.get("_kind", "application")
            name = target.get("name", uuid)

            if action == "deploy":
                if kind != "application":
                    return ToolExecutionResult(
                        success=False,
                        reply_text=(
                            f"'{name}' is a service — services cannot be "
                            "deployed, only restarted/started/stopped."
                        ),
                    )
                result = self._request(cfg, "GET", "/deploy", params={"uuid": uuid})
            else:
                prefix = "/applications" if kind == "application" else "/services"
                result = self._request(cfg, "GET", f"{prefix}/{uuid}/{action}")

            message = ""
            if isinstance(result, dict):
                message = str(result.get("message") or result.get("deployments") or "")
            context.user_print(f"✅ {action} requested for {name}")
            debug_log(f"coolify {action} ok for {kind} {uuid}", "tools")
            return ToolExecutionResult(
                success=True,
                reply_text=f"Coolify accepted '{action}' for {kind} '{name}'. {message}".strip(),
            )

        except requests.exceptions.Timeout:
            context.user_print("⚠️ Coolify timed out")
            return ToolExecutionResult(
                success=False,
                reply_text="The Coolify server did not respond in time.",
            )
        except requests.exceptions.HTTPError as e:
            debug_log(f"coolify HTTP error: {e}", "tools")
            context.user_print("⚠️ Coolify request failed")
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    f"Coolify rejected the request ({e}). The API token may "
                    "be invalid or lack permissions."
                ),
            )
        except requests.exceptions.RequestException as e:
            debug_log(f"coolify unreachable: {e}", "tools")
            context.user_print("⚠️ Coolify unreachable")
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    "Could not reach the Coolify server. It may be down, or "
                    "'coolify_base_url' may be wrong."
                ),
            )
        except Exception as e:
            debug_log(f"coolify error: {e}", "tools")
            return ToolExecutionResult(
                success=False,
                reply_text=f"Coolify tool error: {e}",
            )
