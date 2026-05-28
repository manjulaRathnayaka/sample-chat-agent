import asyncio
import os
import sys
from typing import Dict

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)


_DEFAULT_PROMPT = (
    "You are a helpful assistant. Follow the user's instructions and use the "
    "tools available to you when useful."
)


def _load_system_prompt() -> str:
    prompt = os.environ.get("AGENT_SYSTEM_PROMPT", "").strip()
    if prompt:
        return prompt
    print(
        "[agent] WARNING: AGENT_SYSTEM_PROMPT is not set; "
        "falling back to minimal default prompt.",
        file=sys.stderr,
    )
    return _DEFAULT_PROMPT


SYSTEM_PROMPT = _load_system_prompt()


_clients: Dict[str, ClaudeSDKClient] = {}
_clients_lock = asyncio.Lock()


def _build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=["Bash", "Read", "Grep", "Glob", "WebFetch"],
        permission_mode="bypassPermissions",
        cwd=os.getcwd(),
    )


async def _get_or_create_client(session_id: str) -> ClaudeSDKClient:
    async with _clients_lock:
        client = _clients.get(session_id)
        if client is not None:
            return client
        client = ClaudeSDKClient(options=_build_options())
        await client.connect()
        _clients[session_id] = client
        return client


async def run_agent(session_id: str, message: str) -> str:
    client = await _get_or_create_client(session_id)
    await client.query(message)

    parts: list[str] = []
    async for msg in client.receive_response():
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
        elif isinstance(msg, ResultMessage):
            break

    return "\n".join(p for p in parts if p).strip() or "(agent produced no text response)"


async def reset_session(session_id: str) -> bool:
    async with _clients_lock:
        client = _clients.pop(session_id, None)
    if client is None:
        return False
    await client.disconnect()
    return True
