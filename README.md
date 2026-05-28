# Sample Chat Agent - Deployment Guide

## Overview

A generic chat agent powered by the [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/),
exposed over HTTP as `POST /chat`. The agent's behavior is fully determined
by the system prompt you inject via the `AGENT_SYSTEM_PROMPT` environment
variable — the same code can run as a security probe, a support bot, a DevOps
helper, etc.

The agent has access to these built-in tools at runtime: `Bash`, `Read`,
`Grep`, `Glob`, `WebFetch`. What it actually does with them is entirely up to
your prompt.

**Built with**: FastAPI + `claude-agent-sdk` (Python).

## How it works

```
   POST /chat                    ┌──────────────────────────┐
{ session_id, message }  ───▶    │  FastAPI (app.py)        │
                                 │   └─ run_agent()         │
                                 │       └─ ClaudeSDKClient │
                                 │           ├─ Bash        │
                                 │           ├─ Read        │
                                 │           ├─ Grep        │
                                 │           ├─ Glob        │
                                 │           └─ WebFetch    │
                                 └──────────────────────────┘
                                              │
                                              ▼
                                    { response: "..." }
```

One `ClaudeSDKClient` is kept per `session_id`, so follow-up messages on the
same session see prior turns.

## Prerequisites

### Required API Key

- **Anthropic API Key** — the SDK reads `ANTHROPIC_API_KEY` from the environment.

### Runtime

- Python 3.11+
- The `claude-agent-sdk` package launches the bundled `claude` CLI as a
  subprocess. In standard buildpacks this works out of the box; on minimal
  base images make sure the CLI's runtime is available.

## Deployment Instructions

### Step 1: Access Agent Manager

1. Navigate to the **Default** project
2. Click **"Add Agent"**
3. Select **Platform-Hosted Agent** Card

### Step 2: Configure Agent Details

Fill in the agent creation form. Display name / description should reflect
what *you* are deploying the agent as — the values below are just an example
for a security-testing deployment:

| Field                 | Value                                       |
| --------------------- | ------------------------------------------- |
| **Display Name**      | e.g. `My Agent`                             |
| **Description**       | Describe what your agent does               |
| **GitHub Repository** | `<your fork / repo containing this folder>` |
| **Branch**            | `main`                                      |
| **App Path**          | `.` (or the subpath where this folder lives) |
| **Language**          | `Python`                                    |
| **Language Version**  | `3.11`                                      |
| **Start Command**     | `python main.py`                            |
| **Port**              | `8000`                                      |

### Step 3: Select Agent Interface

- Choose **"Chat Agent"** as the agent interface type.

### Step 4: Configure Environment Variables

```env
ANTHROPIC_API_KEY=<your-anthropic-api-key>
AGENT_SYSTEM_PROMPT=<the system prompt that defines this agent's behavior>
```

See **[Configuring the system prompt](#configuring-the-system-prompt)** below.

### Step 5: Deploy the Agent

1. Review all configuration details
2. Click **"Deploy"**
3. Wait for the build to complete

## Configuring the system prompt

The system prompt is what turns this generic code into your specific agent.
It's injected at runtime via `AGENT_SYSTEM_PROMPT` so the source can stay
public without disclosing your prompt content.

If `AGENT_SYSTEM_PROMPT` is unset, the service still starts with a minimal
generic prompt ("You are a helpful assistant…") and logs a warning to stderr.

### Kubernetes (recommended)

Keep the prompt in a Secret and surface it as an env var with `secretKeyRef`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: agent-prompt
type: Opaque
stringData:
  prompt: |
    <your full system prompt here>
---
# in the Deployment spec:
env:
  - name: ANTHROPIC_API_KEY
    valueFrom: { secretKeyRef: { name: anthropic, key: api-key } }
  - name: AGENT_SYSTEM_PROMPT
    valueFrom: { secretKeyRef: { name: agent-prompt, key: prompt } }
```

### Local development

```bash
export AGENT_SYSTEM_PROMPT="$(cat /path/to/your/prompt.txt)"
python main.py
```

## API

### `POST /chat`

Request:

```json
{
  "session_id": "sess-001",
  "message": "..."
}
```

Response:

```json
{
  "response": "..."
}
```

State is keyed by `session_id`. Reuse it for follow-ups; switch to a new id
for a fresh conversation.

### `POST /sessions/{session_id}/reset`

Drops the in-memory client for that session.

### `GET /healthz`

Liveness check.

See [`openapi.yaml`](./openapi.yaml) for the full spec.

## Local development

```bash
cd sample-chat-agent
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export AGENT_SYSTEM_PROMPT="$(cat /path/to/your/prompt.txt)"
python main.py
```

Smoke test:

```bash
curl -s localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"session_id":"local-1","message":"What network interfaces and routes do you see on this machine?"}' \
  | jq -r .response
```

## Safety notes

- The agent runs with `permission_mode="bypassPermissions"` so it can execute
  `Bash` without interactive prompts — that is appropriate for a server, but
  it means the **system prompt is your main behavioural guardrail**.
- The set of tools the agent is allowed to use is defined in
  `agent/agent.py` (`allowed_tools=["Bash", "Read", "Grep", "Glob", "WebFetch"]`).
  Tighten this if your use case doesn't need all of them.
- Only deploy this where the actions implied by your system prompt are
  authorized.
