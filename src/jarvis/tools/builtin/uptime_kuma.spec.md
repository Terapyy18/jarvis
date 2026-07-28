# Uptime Kuma Tool Spec

## Purpose

The `uptimeKuma` tool lets Jarvis check and control the user's self-hosted
Uptime Kuma monitoring instance: the state of every monitor (up, down,
pending, maintenance, paused), uptime percentages, latency, and the reason
a monitor is down, plus pausing and resuming individual monitors.

## Key principles

- **Self-hosted only.** The tool talks to the Kuma instance the user points
  it at via `kuma_base_url`. Monitoring data never leaves infrastructure
  the user owns.
- **socket.io session per call.** Kuma v1 has no general REST API; its
  control surface is socket.io. Each tool invocation opens a session via
  the `uptime-kuma-api` client, logs in, does its work, and disconnects in
  a `finally` block. No long-lived connection to keep healthy.
- **Voice-friendly name resolution.** Monitor arguments are matched
  case-insensitively: exact id/name first, then substring on name or URL.
  The model is told to pass what the user said, never to guess.
- **Raw data out.** Monitor states are summarised as plain lines (name,
  state, ping, down reason, uptime 24h/30d, URL) with no LLM processing.
- **Honest failure.** Unconfigured (any of the three keys empty) replies
  with setup guidance and no outbound call. A missing `uptime-kuma-api`
  package is named explicitly. Connection/auth failures name the likely
  causes without ever echoing the password. An unknown monitor name lists
  every available monitor so the model can retry sensibly.
- **Fail-soft data sources.** A broken heartbeat or uptime feed degrades
  the status report (states/percentages omitted) instead of hiding the
  monitor list.

## Configuration

| Key | Meaning |
|-----|---------|
| `kuma_base_url` | Base URL of the Kuma instance. Empty = not configured. |
| `kuma_username` | Uptime Kuma account username. |
| `kuma_password` | Uptime Kuma account password. |

## Actions

| Action | Behaviour |
|--------|-----------|
| `status` (default) | Every monitor with state, ping, down reason, uptime 24h/30d. Optional `monitor` argument focuses one monitor. |
| `pause` | Pause the monitor named by `monitor` (required). |
| `resume` | Resume the monitor named by `monitor` (required). |

## Limits

- 15-second socket.io timeout.
- No LLM calls inside the tool.
