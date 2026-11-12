from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import Base, SessionLocal, UPLOADS_DIR, engine
from app.migrations import migrate_database
from app.routers import agent_query, cracks, detection, geolocation, media, nl_query, tasks
from app.seed import seed_reference_data

app = FastAPI(
    title="无人机道路裂缝智能巡检系统",
    description="用于比赛演示的道路裂缝巡检后端服务，包含任务管理、CrackMamba 检测、地图点位和工具驱动型智能查询 Agent。",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

app.include_router(tasks.router)
app.include_router(media.router)
app.include_router(detection.router)
app.include_router(cracks.router)
app.include_router(geolocation.router)
app.include_router(nl_query.router)
app.include_router(agent_query.router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_database(engine)
    with SessionLocal() as db:
        seed_reference_data(db)


@app.get("/", tags=["system"])
def read_root() -> dict[str, str]:
    return {
        "system": "无人机道路裂缝智能巡检系统",
        "status": "running",
        "docs": "/docs",
    }
