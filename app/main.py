"""FastAPI application entry point."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import checkin, feasibility, next_action, places, search, stream, trips


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="PathFinder v2", lifespan=lifespan)

app.include_router(trips.router)
app.include_router(places.router)
app.include_router(search.router)
app.include_router(feasibility.router)
app.include_router(next_action.router)
app.include_router(checkin.router)
app.include_router(stream.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
