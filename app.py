import asyncio
import os
import shutil
import socket
import ssl
import urllib.request
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


def _resolve(host: str, family: int) -> dict:
    try:
        infos = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
        return {"ok": True, "addrs": sorted({ai[4][0] for ai in infos})}
    except socket.gaierror as e:
        return {"ok": False, "error": str(e)}


def _tcp_connect(host: str, port: int, family: int, timeout: float = 5.0) -> dict:
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return {"ok": False, "error": f"resolve failed: {e}"}
    if not infos:
        return {"ok": False, "error": "no addresses"}
    addr = infos[0][4]
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(addr)
        return {"ok": True, "connected_to": addr[0]}
    except (socket.timeout, OSError) as e:
        return {"ok": False, "connect_addr": addr[0], "error": f"{type(e).__name__}: {e}"}
    finally:
        s.close()


async def _http_get(url: str, timeout: float = 5.0) -> dict:
    def _do() -> dict:
        try:
            req = urllib.request.Request(url, method="GET")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return {"ok": True, "status": resp.status}
        except urllib.error.HTTPError as e:
            return {"ok": True, "status": e.code}  # got a response, that's what matters
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return await asyncio.get_running_loop().run_in_executor(None, _do)


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
        "dns_a_record":    _resolve("api.anthropic.com", socket.AF_INET),
        "dns_aaaa_record": _resolve("api.anthropic.com", socket.AF_INET6),
        "tcp_connect_ipv4": _tcp_connect("api.anthropic.com", 443, socket.AF_INET),
        "tcp_connect_ipv6": _tcp_connect("api.anthropic.com", 443, socket.AF_INET6),
        "https_get_anthropic": await _http_get("https://api.anthropic.com/"),
    }

    if claude_path:
        results["claude_version"] = await _run([claude_path, "--version"])
        results["claude_print_hello"] = await _run(
            [claude_path, "-p", "say hi in one word", "--output-format", "json"],
            timeout=45.0,
        )

    return JSONResponse(content=results)
