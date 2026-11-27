from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.app.core.security import require_roles
from backend.app.services.reporting_service import (
    ReportNotFoundError,
    ReportValidationError,
    ReportingService,
)

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])


def _service(request: Request) -> ReportingService:
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized")
    return ReportingService(manager)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ReportNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ReportValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="Report generation failed")


def _call(operation):
    try:
        return operation()
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/overview")
def reporting_overview(
    request: Request,
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    return _call(lambda: _service(request).get_overview())


@router.get("/exams/{exam_id}/analytics")
def exam_analytics(
    exam_id: int,
    request: Request,
    pass_threshold_percent: float = Query(default=50.0, ge=0, le=100),
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    return _call(lambda: _service(request).get_exam_analytics(exam_id, pass_threshold_percent=pass_threshold_percent))


@router.get("/exams/{exam_id}/gradebook")
def exam_gradebook(
    exam_id: int,
    request: Request,
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    return _call(lambda: _service(request).get_exam_gradebook(exam_id))


@router.get("/teachers/{teacher_id}")
def teacher_report(
    teacher_id: int,
    request: Request,
    actor: dict = Depends(require_roles("Admin", "Teacher")),
):
    if actor.get("RoleName") == "Teacher" and int(actor["UserId"]) != teacher_id:
        raise HTTPException(status_code=403, detail="Teachers may access only their own activity report")
    return _call(lambda: _service(request).get_teacher_report(teacher_id))


@router.get("/students/{student_id}")
def student_report(
    student_id: int,
    request: Request,
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    return _call(lambda: _service(request).get_student_report(student_id))


@router.get("/exams/{exam_id}/export")
def export_exam_gradebook(
    exam_id: int,
    request: Request,
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    result = _call(lambda: _service(request).export_gradebook(
        exam_id, export_format=format, actor_user_id=int(actor["UserId"])
    ))
    payload, media_type, filename = result
    return StreamingResponse(
        BytesIO(payload),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
