from fastapi import FastAPI

from app.integrations.routes import router as integrations_router
from app.services.routes import router as services_router
from app.workflows.routes import router as workflows_router

app = FastAPI(title="Feature Delivery Copilot API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(services_router, prefix="/api/v1")
app.include_router(workflows_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
