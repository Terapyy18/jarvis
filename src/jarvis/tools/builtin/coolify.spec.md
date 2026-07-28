# Coolify Tool Spec

## Purpose

The `coolify` tool lets Jarvis monitor and control the user's own Coolify
server (a self-hostable deployment platform) by voice: "is my server ok?",
"restart the blog", "deploy the portal".

## Key principles

- **Self-hosted only.** The tool talks to the instance the user points it at
  via `coolify_base_url`. Nothing leaves infrastructure the user owns, which
  is what makes this integration acceptable under the offline-first policy.
- **Raw data out.** The tool returns trimmed raw facts (names, statuses,
  domains); the daemon's LLM loop handles phrasing.
- **Voice-friendly targeting.** Users say app names, not uuids. The tool
  resolves the spoken name case-insensitively: exact uuid/name match first,
  then substring match against name and domain, across both applications and
  services. No language-specific patterns.
- **Honest failure.** An unresolvable name replies with the full list of
  known targets so the model can correct itself. Connection errors, timeouts
  and HTTP rejections each produce a distinct, human-readable explanation.

## Configuration

| Key | Meaning |
|-----|---------|
| `coolify_base_url` | Base URL of the Coolify instance. Empty = not configured. |
| `coolify_api_token` | Bearer token (Coolify → Keys & Tokens → API tokens). |

When either value is empty the tool does not call out at all; it replies
with setup guidance naming both config keys and tells the model not to
retry.

## Actions

| Action | Behaviour |
|--------|-----------|
| `status` (default) | Lists every application and service with status and domain. |
| `list_apps` / `list_services` | Same listing, filtered to one kind. |
| `list_servers` / `list_databases` | Lists servers / databases (name, status, IP, description). |
| `deployments` | Lists deployments currently in progress. |
| `deploy` | Applications only; services are refused with an explanation. Requires `app`. |
| `restart` / `start` / `stop` | Works on applications and services. Requires `app`. |

All requests go to `{base}/api/v1/...` with the Bearer token. Target
actions resolve the name first (one listing round-trip), then hit the
lifecycle endpoint for the resolved resource kind. A listing endpoint that
fails (e.g. an instance with no services) is skipped rather than failing
the whole call.

## Limits

- 20-second HTTP timeout per request.
- No LLM calls inside the tool.
