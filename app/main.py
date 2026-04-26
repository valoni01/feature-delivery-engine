import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.llm import lifespan
from app.core.logging import setup_logging
from app.core.telemetry import init_telemetry, instrument_app, instrument_db_engine
from app.integrations.github_routes import router as github_router
from app.integrations.routes import router as integrations_router
from app.services.routes import router as services_router
from app.workflows.routes import router as workflows_router

setup_logging()
init_telemetry()

app = FastAPI(title="Feature Delivery Copilot API", lifespan=lifespan)

allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:4200").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

instrument_app(app)

from app.core.db import engine  # noqa: E402
instrument_db_engine(engine)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(services_router, prefix="/api/v1")
app.include_router(workflows_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
app.include_router(github_router, prefix="/api/v1")
