"""TeraPrintPortal tool — read business data from the user's own client portal.

TeraPrintPortal is the user's self-hosted freelance client portal. Jarvis
reads it through a single key-protected endpoint (``GET /api/jarvis``) that
the portal exposes for this purpose; the key lives in Jarvis config
(``teraprint_base_url`` + ``teraprint_api_key``). Read-only by design — see
teraprint_portal.spec.md.
"""

import json
import requests
from typing import Any, Dict, Optional

from ...debug import debug_log
from ..base import Tool, ToolContext
from ..types import ToolExecutionResult


_RESOURCES = (
    "dashboard", "clients", "projects", "quotes", "invoices", "payments",
    "appointments", "sales", "subscriptions",
)

# Cap on the JSON payload passed back to the LLM so a large table can never
# blow the context window of a small model.
_MAX_REPLY_CHARS = 6000

_TIMEOUT_SEC = 15


class TeraPrintPortalTool(Tool):
    """Read-only bridge to the user's TeraPrintPortal instance."""

    @property
    def name(self) -> str:
        return "teraPrintPortal"

    @property
    def description(self) -> str:
        return (
            "Read live business data from the user's own TeraPrintPortal "
            "(their freelance client portal): clients, projects, quotes, "
            "invoices, payments, appointments, sales, subscriptions, and a "
            "dashboard summary (revenue, active projects, pending items). "
            "Use for any question about the user's business, clients, money "
            "coming in, upcoming appointments, or project state. Read-only."
        )

    @property
    def inputSchema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "enum": list(_RESOURCES),
                    "description": (
                        "Which data to fetch. 'dashboard' is the compact "
                        "business summary — prefer it for broad questions."
                    ),
                },
            },
            "required": ["resource"],
        }

    def run(self, args: Optional[Dict[str, Any]], context: ToolContext) -> ToolExecutionResult:
        cfg = context.cfg
        base = (getattr(cfg, "teraprint_base_url", "") or "").rstrip("/")
        key = getattr(cfg, "teraprint_api_key", "") or ""
        if not base.strip() or not key.strip():
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    "TeraPrintPortal is not configured. The user must set "
                    "'teraprint_base_url' (the portal URL) and "
                    "'teraprint_api_key' (matching the portal's "
                    "JARVIS_API_KEY) in Jarvis settings. Tell the user how "
                    "to enable it; do not retry."
                ),
            )

        resource = str((args or {}).get("resource") or "").strip().lower()
        if resource not in _RESOURCES:
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    f"Unknown portal resource '{resource}'. "
                    f"Valid resources: {', '.join(_RESOURCES)}."
                ),
            )

        context.user_print(f"🗂️ Portal: fetching {resource}...")
        debug_log(f"teraPrintPortal fetch resource={resource}", "tools")

        try:
            resp = requests.get(
                f"{base}/api/jarvis",
                headers={"x-api-key": key, "Accept": "application/json"},
                params={"resource": resource},
                timeout=_TIMEOUT_SEC,
            )
            if resp.status_code in (401, 403):
                return ToolExecutionResult(
                    success=False,
                    reply_text=(
                        "The portal refused the request (bad or missing API "
                        "key). 'teraprint_api_key' must match the portal's "
                        "JARVIS_API_KEY environment variable."
                    ),
                )
            if resp.status_code == 404:
                return ToolExecutionResult(
                    success=False,
                    reply_text=(
                        "The portal has no /api/jarvis endpoint. The "
                        "TeraPrintPortal deployment needs the Jarvis bridge "
                        "route installed (see examples/teraprintportal in "
                        "the Jarvis repository)."
                    ),
                )
            resp.raise_for_status()
            data = resp.json()

            text = json.dumps(data, ensure_ascii=False, default=str)
            if len(text) > _MAX_REPLY_CHARS:
                text = text[:_MAX_REPLY_CHARS] + "… [truncated]"

            context.user_print(f"✅ Portal {resource} retrieved")
            return ToolExecutionResult(
                success=True,
                reply_text=f"TeraPrintPortal {resource} data:\n{text}",
            )

        except requests.exceptions.Timeout:
            context.user_print("⚠️ Portal timed out")
            return ToolExecutionResult(
                success=False,
                reply_text="TeraPrintPortal did not respond in time.",
            )
        except requests.exceptions.RequestException as e:
            debug_log(f"teraPrintPortal unreachable: {e}", "tools")
            context.user_print("⚠️ Portal unreachable")
            return ToolExecutionResult(
                success=False,
                reply_text=(
                    "Could not reach TeraPrintPortal. It may be down, or "
                    "'teraprint_base_url' may be wrong."
                ),
            )
        except Exception as e:
            debug_log(f"teraPrintPortal error: {e}", "tools")
            return ToolExecutionResult(
                success=False,
                reply_text=f"TeraPrintPortal tool error: {e}",
            )
