"""ReportAgent Microservice — port 8013."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="ReportAgent", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

class A2ARequest(BaseModel):
    jsonrpc: str = "2.0"; method: str; params: dict = {}; id: str = "1"

@app.get("/health")
async def health():
    return {"status": "ok", "agent": "ReportAgent", "port": 8013}

@app.post("/a2a")
async def a2a_endpoint(req: A2ARequest):
    try:
        from app.agent.sub_agents import ReportAgent
        agent = ReportAgent()
        method = getattr(agent, req.method, None)
        if method is None:
            return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {req.method}"}, "id": req.id}
        result = await method(req.params) if asyncio.iscoroutinefunction(method) else method(req.params)
        return {"jsonrpc": "2.0", "result": result, "id": req.id}
    except Exception as e:
        return {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": req.id}

if __name__ == "__main__":
    import uvicorn; uvicorn.run(app, host="0.0.0.0", port=8013)
