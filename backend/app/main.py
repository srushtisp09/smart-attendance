from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import attendance, auth, classes, face, sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fine for Day 1. Swap for Alembic migrations before deploying.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Smart Schedule & Attendance API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)  # tighten allow_origins before deploying

app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(sessions.router)
app.include_router(attendance.router)
app.include_router(face.router)


@app.get("/health")
def health():
    return {"status": "ok"}