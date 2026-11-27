from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from backend.app.api.endpoints.academic import router as academic_router
from backend.app.api.endpoints.ai import router as ai_router
from backend.app.api.endpoints.answers import router as answers_router
from backend.app.api.endpoints.auth import router as auth_router
from backend.app.api.endpoints.grading import router as grading_router
from backend.app.api.endpoints.reports import router as reports_router
from backend.app.api.endpoints.uploads import router as uploads_router
from backend.app.core.security import install_api_auth_middleware, load_or_create_signing_secret
from backend.app.database.database_manager import DatabaseManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the local database and persistent API signing key."""
    manager = DatabaseManager()
    try:
        db_path = manager.initialize_database()
        app.state.db_manager = manager
        app.state.database_path = str(db_path)
        app.state.auth_secret = load_or_create_signing_secret(manager.storage_dir)
        print(f"Madar database initialized: {db_path}")
    except Exception as exc:
        raise RuntimeError(f"Madar startup initialization failed: {exc}") from exc
    yield
    print("Madar API shutting down.")


app = FastAPI(
    title="Madar - Smart Arabic Grader",
    description="Local AI-powered Arabic examination grading system.",
    version="1.3.0",
    lifespan=lifespan,
)

install_api_auth_middleware(app)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(academic_router, prefix="/api/v1")
app.include_router(uploads_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(grading_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(answers_router, prefix="/api/v1")


@app.get("/", tags=["System"])
async def root():
    return {
        "project": "Madar",
        "service": "Smart Arabic Grader API",
        "status": "running",
        "version": "1.3.0",
    }


@app.get("/health", tags=["System"])
def health_check():
    manager = getattr(app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized.")
    try:
        with manager.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {
            "status": "healthy",
            "api": "running",
            "database": "connected",
            "database_path": app.state.database_path,
            "authentication": "enabled",
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database connection failed.") from exc
