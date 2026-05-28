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
