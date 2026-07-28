# TeraPrintPortal Tool Spec

## Purpose

The `teraPrintPortal` tool gives Jarvis read access to the user's
self-hosted TeraPrintPortal (freelance client portal): clients, projects,
quotes, invoices, payments, appointments, sales, subscriptions, and a
dashboard summary.

## Key principles

- **Self-hosted only.** The tool talks to the portal instance the user
  points it at via `teraprint_base_url`. The data is the user's own business
  data on the user's own deployment.
- **Read-only.** The tool never creates, updates, or deletes anything.
  Mutations stay in the portal UI where they carry auth, validation, and
  side effects (emails, notifications).
- **Single bridge endpoint.** The portal's API routes authenticate through
  Clerk sessions, which a headless assistant cannot hold. The portal
  therefore exposes one key-protected read endpoint, `GET /api/jarvis`,
  taking a `resource` query parameter and an `x-api-key` header that must
  match the portal's `JARVIS_API_KEY` environment variable. The
  ready-to-install route lives in `examples/teraprintportal/` in this
  repository.
- **Raw data out.** The tool passes the portal's JSON through as text,
  capped at 6,000 characters so large tables cannot blow a small model's
  context window.
- **Honest failure.** 401/403 explains the key mismatch; 404 explains that
  the bridge route is not installed on the portal; network errors name the
  likely cause. Unconfigured (either config key empty) replies with setup
  guidance and no outbound call.

## Configuration

| Key | Meaning |
|-----|---------|
| `teraprint_base_url` | Base URL of the portal deployment. Empty = not configured. |
| `teraprint_api_key` | Shared secret; must equal the portal's `JARVIS_API_KEY`. |

## Resources

`dashboard` (compact business summary — preferred for broad questions),
`clients`, `projects`, `quotes`, `invoices`, `payments`, `appointments`,
`sales`, `subscriptions`.

## Limits

- 15-second HTTP timeout.
- 6,000-character reply cap.
- No LLM calls inside the tool.
