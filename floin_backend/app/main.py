from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import datasets, health, layers, simulations, validation
from app.core.config import get_settings
from app.core.errors import FloinError
from app.core.logging import configure_logging, get_logger
from app.simulation import MODEL_VERSION

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger("api")

app = FastAPI(
    title=settings.app_name,
    version=MODEL_VERSION,
    description=(
        "Event-based flood screening for Chennai: SCS-CN runoff from land cover and soil, D8 routing on a "
        "depression-filled DEM, and depression fill-and-spill storage for flood depth. Not a hydraulic model."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"],  # dev only; set the production origin explicitly
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
for module in (health, datasets, layers, simulations, validation):
    app.include_router(module.router, prefix="/api/v1")


@app.exception_handler(FloinError)
async def floin_error(_: Request, exc: FloinError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message, **exc.details})


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"error": "internal_error", "message": f"{type(exc).__name__}: {exc}"})


@app.get("/", include_in_schema=False)
def root():
    return {"name": settings.app_name, "version": MODEL_VERSION, "docs": "/docs", "health": "/api/v1/health"}
