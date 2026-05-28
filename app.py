import asyncio
import os
import shutil
from pathlib import Path

import dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from agent.agent import reset_session, run_agent


app = FastAPI(title="Claude Agent")
dotenv.load_dotenv()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/chat")
async def chat(payload: dict):
    session_id = payload.get("session_id")
    message = payload.get("message")
    if not session_id or not message:
        raise HTTPException(
            status_code=400,
            detail="Request body must include 'session_id' and 'message'.",
        )

    response = await run_agent(str(session_id), str(message))
    return JSONResponse(content={"response": response})


@app.post("/sessions/{session_id}/reset")
async def reset(session_id: str):
    cleared = await reset_session(session_id)
    return {"session_id": session_id, "cleared": cleared}


async def _run(cmd: list[str], timeout: float = 8.0) -> dict:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ok": False, "error": f"timeout after {timeout}s"}
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace")[:500],
            "stderr": stderr.decode(errors="replace")[:500],
        }
    except FileNotFoundError as e:
        return {"ok": False, "error": f"binary not found: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _find_bundled_claude() -> str | None:
    try:
        import claude_agent_sdk
        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
        if bundled.exists():
            return str(bundled)
    except Exception:
        pass
    return shutil.which("claude")


@app.get("/diag")
async def diag():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    claude_path = _find_bundled_claude()
    node_path = shutil.which("node")

    results: dict = {
        "anthropic_api_key": {
            "present": bool(key),
            "length": len(key),
            "prefix": key[:12] if key else None,
            "has_trailing_whitespace": key != key.rstrip() if key else False,
        },
        "claude_binary": {"path": claude_path, "exists": bool(claude_path)},
        "node_binary": {"path": node_path, "exists": bool(node_path)},
    }

    # Egress check: can we reach api.anthropic.com?
    results["egress_anthropic_api"] = await _run(
        ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code} time=%{time_total}",
         "--max-time", "5", "https://api.anthropic.com/v1/messages"]
    )

    # DNS check
    results["dns_anthropic_api"] = await _run(
        ["getent", "hosts", "api.anthropic.com"], timeout=5.0
    )

    # Node version
    if node_path:
        results["node_version"] = await _run([node_path, "--version"])

    # Claude CLI version
    if claude_path:
        results["claude_version"] = await _run([claude_path, "--version"])

    return JSONResponse(content=results)
