from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import schemas
from app.agent.agent_loop import get_agent_session_detail, run_agent_query, run_agent_query_stream
from app.database import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/query", response_model=schemas.AgentQueryResponse)
def query_agent(payload: schemas.AgentQueryRequest, db: Session = Depends(get_db)) -> schemas.AgentQueryResponse:
    result = run_agent_query(db, payload.query)
    return schemas.AgentQueryResponse(**result)


@router.post("/query/stream")
def query_agent_stream(payload: schemas.AgentQueryRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    def event_iter():
        try:
            for event in run_agent_query_stream(db, payload.query):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:
            error_event = {"type": "error", "content": str(exc)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/session/{session_id}", response_model=schemas.AgentSessionDetail)
def get_agent_session(session_id: int, db: Session = Depends(get_db)) -> schemas.AgentSessionDetail:
    result = get_agent_session_detail(db, session_id)
    return schemas.AgentSessionDetail(**result)
