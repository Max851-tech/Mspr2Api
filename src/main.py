from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from src.config.settings import settings
from src.core.database import get_client, close_connection
from src.core.mariadb import init_pool, close_pool
from src.routers import food_analysis, recommendations, health
from src.routers.users import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Démarrage
    get_client()           # MongoDB
    await init_pool()      # MariaDB (best-effort, non bloquant si indispo)
    yield
    # Arrêt
    await close_connection()
    await close_pool()

# --- App ---
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    lifespan=lifespan,
    title="HealthAI Coach – AI Service",
    description=(
        "Microservice IA pour l'analyse nutritionnelle par photo de repas "
        "et la génération de recommandations personnalisées (nutrition & sport)."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# --- Rate limiting ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
app.include_router(health.router, tags=["Health"])
app.include_router(food_analysis.router, prefix="/api/v1", tags=["Food Analysis"])
app.include_router(recommendations.router, prefix="/api/v1", tags=["Recommendations"])
app.include_router(users_router)


# --- Global error handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Erreur interne du serveur", "type": type(exc).__name__},
    )
