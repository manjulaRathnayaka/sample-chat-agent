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


async def _run(cmd: list[str], timeout: float = 8.0, env: dict | None = None) -> dict:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode(errors="replace")[-1500:],
                "stderr": stderr.decode(errors="replace")[-1500:],
            }
        except asyncio.TimeoutError:
            # Capture whatever was buffered before we kill the child.
            partial_stdout = b""
            partial_stderr = b""
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=2.0)
                partial_stdout, partial_stderr = stdout, stderr
            except Exception:
                pass
            return {
                "ok": False,
                "error": f"timeout after {timeout}s",
                "partial_stdout": partial_stdout.decode(errors="replace")[-1500:],
                "partial_stderr": partial_stderr.decode(errors="replace")[-1500:],
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


async def _run_blocking(fn, *, timeout: float, **kwargs):
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: fn(**kwargs)),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timeout after {timeout}s"}


def _resolve_sync(host: str, family: int) -> dict:
    try:
        infos = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
        return {"ok": True, "addrs": sorted({ai[4][0] for ai in infos})}
    except socket.gaierror as e:
        return {"ok": False, "error": str(e)}


def _tcp_connect_sync(host: str, port: int, family: int, conn_timeout: float) -> dict:
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return {"ok": False, "error": f"resolve failed: {e}"}
    if not infos:
        return {"ok": False, "error": "no addresses"}
    addr = infos[0][4]
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(conn_timeout)
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
async def diag(cli_test: int = 0):
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

    results["dns_a_record"] = await _run_blocking(
        _resolve_sync, timeout=4.0, host="api.anthropic.com", family=socket.AF_INET
    )
    results["dns_aaaa_record"] = await _run_blocking(
        _resolve_sync, timeout=4.0, host="api.anthropic.com", family=socket.AF_INET6
    )
    results["tcp_connect_ipv4"] = await _run_blocking(
        _tcp_connect_sync, timeout=4.0,
        host="api.anthropic.com", port=443, family=socket.AF_INET, conn_timeout=3.0,
    )
    results["tcp_connect_ipv6"] = await _run_blocking(
        _tcp_connect_sync, timeout=4.0,
        host="api.anthropic.com", port=443, family=socket.AF_INET6, conn_timeout=3.0,
    )
    results["https_get_anthropic"] = await _http_get("https://api.anthropic.com/", timeout=5.0)

    results["pod_env"] = {
        "NODE_OPTIONS": os.environ.get("NODE_OPTIONS"),
        "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
        "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
        "NO_PROXY": os.environ.get("NO_PROXY"),
        "HOME": os.environ.get("HOME"),
        "USER": os.environ.get("USER"),
        "PWD": os.environ.get("PWD"),
    }

    home = os.environ.get("HOME") or "/tmp"
    try:
        Path(home).mkdir(parents=True, exist_ok=True)
        test_path = Path(home) / ".sample-chat-agent-writetest"
        test_path.write_text("x")
        test_path.unlink()
        results["home_writable"] = {"ok": True, "home": home}
    except Exception as e:
        results["home_writable"] = {"ok": False, "home": home, "error": f"{type(e).__name__}: {e}"}

    if claude_path:
        results["claude_version"] = await _run([claude_path, "--version"], timeout=5.0)
        results["claude_help"] = await _run([claude_path, "--help"], timeout=5.0)
        if cli_test:
            base_env = dict(os.environ)
            forced_env = {
                **base_env,
                "NODE_OPTIONS": "--dns-result-order=ipv4first",
                "DEBUG": "*",
                "ANTHROPIC_LOG": "debug",
            }
            results["claude_print_hello_stream"] = await _run(
                [claude_path, "-p", "say hi in one word",
                 "--output-format", "stream-json", "--verbose", "--debug"],
                timeout=22.0,
                env=forced_env,
            )
        else:
            results["claude_print_hello_stream"] = "skipped (pass ?cli_test=1 to run)"

    return JSONResponse(content=results)
