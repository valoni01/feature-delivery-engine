from fastapi import FastAPI

from app.services.routes import router as services_router

app = FastAPI(title="Feature Delivery Copilot API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(services_router, prefix="/api/v1")
