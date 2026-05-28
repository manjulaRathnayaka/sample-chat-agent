# Sample Chat Agent

A minimal FastAPI service that exposes a Claude-powered chat agent backed by
the [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/). Behavior
is fully determined by the `AGENT_SYSTEM_PROMPT` env var, so the same code
can be deployed for any use case.

## Configuration

| Env var                | Required | Purpose                                  |
| ---------------------- | -------- | ---------------------------------------- |
| `ANTHROPIC_API_KEY`    | yes      | Claude API key.                          |
| `AGENT_SYSTEM_PROMPT`  | no       | System prompt defining agent behavior. Falls back to a generic default if unset. |

## Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export AGENT_SYSTEM_PROMPT="$(cat /path/to/your/prompt.txt)"
python main.py
```

Smoke test:

```bash
curl -s localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"session_id":"s1","message":"hello"}'
```

## API

- `POST /chat` — body `{ "session_id": "...", "message": "..." }` → `{ "response": "..." }`. State is kept per `session_id`.
- `POST /sessions/{session_id}/reset` — drop a session's state.
- `GET /healthz` — liveness.

See [`openapi.yaml`](./openapi.yaml) for the full spec.
