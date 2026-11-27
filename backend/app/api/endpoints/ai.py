from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.app.services.htr_service import (
    HTRConflictError,
    HTRInputError,
    HTRNotFoundError,
    HTRService,
)

router = APIRouter(prefix="/ai", tags=["AI Processing"])


def _service(request: Request) -> HTRService:
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized")
    engine = getattr(request.app.state, "htr_engine", None)
    if engine is None:
        try:
            from ai_engine.htr.engine import ArabicHTREngine
            engine = ArabicHTREngine()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Arabic HTR engine is unavailable: {type(exc).__name__}: {exc}",
            ) from exc
        request.app.state.htr_engine = engine
    return HTRService(manager, engine=engine)


@router.post("/pages/{page_id}/recognize")
def recognize_page(page_id: int, request: Request):
    """Detect and transcribe every handwriting line on an answer page."""
    try:
        return _service(request).recognize_page(page_id)
    except HTRNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTRInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTRConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="HTR page recognition failed") from exc


@router.post("/answers/{answer_id}/recognize")
def recognize_answer(answer_id: int, request: Request):
    """Recognize only the page regions explicitly linked to one question answer."""
    try:
        return _service(request).recognize_answer(answer_id)
    except HTRNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTRInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTRConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="HTR answer recognition failed") from exc
