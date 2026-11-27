from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.app.services.grading_service import (
    GradingConfigurationError,
    GradingConflictError,
    GradingNotFoundError,
    GradingService,
)

router = APIRouter(prefix="/grading", tags=["AI Grading"])


@router.post("/answers/{answer_id}/evaluate")
def evaluate_answer(answer_id: int, request: Request):
    """Create a deterministic or heuristic score suggestion; never final-approve it."""
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized")
    try:
        return GradingService(manager).evaluate(answer_id)
    except GradingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GradingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GradingConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Answer evaluation failed") from exc
