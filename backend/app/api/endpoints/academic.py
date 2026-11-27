from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.app.core.security import require_roles
from backend.app.schemas.academic import (
    AnswerResponseUpdate,
    AnswerSheetCreate,
    EnrollmentBatch,
    ExamCreate,
    ExamUpdate,
    GradeAdjustment,
    QuestionCreate,
    QuestionUpdate,
    ScoreApproval,
    StudentCreate,
    StudentUpdate,
)
from backend.app.services.academic_service import (
    AcademicConflictError,
    AcademicNotFoundError,
    AcademicService,
    AcademicValidationError,
)

router = APIRouter(prefix="/academic", tags=["Academic Management"])


def _service(request: Request) -> AcademicService:
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized")
    return AcademicService(manager)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AcademicNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AcademicConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AcademicValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, sqlite3.IntegrityError):
        return HTTPException(status_code=409, detail=f"Database constraint conflict: {exc}")
    return HTTPException(status_code=500, detail="Academic operation failed")


def _call(operation):
    try:
        return operation()
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/students")
def list_students(
    request: Request,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    return _call(lambda: _service(request).list_students(search=search, limit=limit, offset=offset))


@router.post("/students", status_code=status.HTTP_201_CREATED)
def create_student(payload: StudentCreate, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).create_student(payload.model_dump(), int(actor["UserId"])))


@router.get("/students/{student_id}")
def get_student(student_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).get_student(student_id))


@router.patch("/students/{student_id}")
def update_student(student_id: int, payload: StudentUpdate, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).update_student(student_id, payload.model_dump(exclude_unset=True), int(actor["UserId"])))


@router.delete("/students/{student_id}")
def delete_student(student_id: int, request: Request, actor: dict = Depends(require_roles("Admin"))):
    return _call(lambda: _service(request).delete_student(student_id, int(actor["UserId"])))


@router.get("/exams")
def list_exams(
    request: Request,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    return _call(lambda: _service(request).list_exams(search=search, limit=limit, offset=offset))


@router.post("/exams", status_code=status.HTTP_201_CREATED)
def create_exam(payload: ExamCreate, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).create_exam(payload.model_dump(), int(actor["UserId"])))


@router.get("/exams/{exam_id}")
def get_exam(exam_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).get_exam(exam_id))


@router.patch("/exams/{exam_id}")
def update_exam(exam_id: int, payload: ExamUpdate, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).update_exam(exam_id, payload.model_dump(exclude_unset=True), int(actor["UserId"])))


@router.delete("/exams/{exam_id}")
def delete_exam(exam_id: int, request: Request, actor: dict = Depends(require_roles("Admin"))):
    return _call(lambda: _service(request).delete_exam(exam_id, int(actor["UserId"])))


@router.post("/exams/{exam_id}/enrollments")
def enroll_students(exam_id: int, payload: EnrollmentBatch, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).enroll_students(exam_id, payload.student_ids, int(actor["UserId"])))


@router.get("/exams/{exam_id}/enrollments")
def list_enrollments(exam_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).list_enrollments(exam_id))


@router.delete("/exams/{exam_id}/enrollments/{student_id}")
def remove_enrollment(exam_id: int, student_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).remove_enrollment(exam_id, student_id, int(actor["UserId"])))


@router.post("/exams/{exam_id}/questions", status_code=status.HTTP_201_CREATED)
def create_question(exam_id: int, payload: QuestionCreate, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).create_question(exam_id, payload.model_dump(), int(actor["UserId"])))


@router.get("/exams/{exam_id}/questions")
def list_questions(exam_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).list_questions(exam_id))


@router.get("/questions/{question_id}")
def get_question(question_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).get_question(question_id))


@router.patch("/questions/{question_id}")
def update_question(question_id: int, payload: QuestionUpdate, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).update_question(question_id, payload.model_dump(exclude_unset=True), int(actor["UserId"])))


@router.delete("/questions/{question_id}")
def delete_question(question_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).delete_question(question_id, int(actor["UserId"])))


@router.post("/exams/{exam_id}/answer-sheets", status_code=status.HTTP_201_CREATED)
def create_answer_sheet(exam_id: int, payload: AnswerSheetCreate, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).create_answer_sheet(exam_id, payload.exam_student_id, int(actor["UserId"])))


@router.get("/exams/{exam_id}/answer-sheets")
def list_answer_sheets(exam_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).list_answer_sheets(exam_id))


@router.get("/answer-sheets/{answer_sheet_id}")
def get_answer_sheet(answer_sheet_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).get_answer_sheet(answer_sheet_id))


@router.get("/answer-sheets/{answer_sheet_id}/answers")
def list_sheet_answers(answer_sheet_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).list_sheet_answers(answer_sheet_id))


@router.get("/answer-sheets/{answer_sheet_id}/pages")
def list_sheet_pages(
    answer_sheet_id: int,
    request: Request,
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    """List uploaded pages for a sheet without exposing filesystem paths."""
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized")
    with manager.connection() as conn:
        sheet = conn.execute(
            "SELECT AnswerSheetId FROM AnswerSheets WHERE AnswerSheetId=?",
            (answer_sheet_id,),
        ).fetchone()
        if sheet is None:
            raise HTTPException(status_code=404, detail="Answer sheet not found")
        rows = conn.execute(
            """
            SELECT PageId, AnswerSheetId, PageNumber, ImageQualityStatus,
                   ImageWidth, ImageHeight, CreatedAt,
                   CASE WHEN OriginalImagePath IS NOT NULL THEN 1 ELSE 0 END AS HasOriginalImage,
                   CASE WHEN PreprocessedImagePath IS NOT NULL THEN 1 ELSE 0 END AS HasProcessedImage
            FROM AnswerPages
            WHERE AnswerSheetId=?
            ORDER BY PageNumber, PageId
            """,
            (answer_sheet_id,),
        ).fetchall()
    return {
        "answer_sheet_id": answer_sheet_id,
        "items": [dict(row) for row in rows],
        "total": len(rows),
    }


@router.patch("/answers/{answer_id}/response")
def update_answer_response(answer_id: int, payload: AnswerResponseUpdate, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher"))):
    return _call(lambda: _service(request).update_answer_response(answer_id, payload.model_dump(exclude_unset=True), int(actor["UserId"])))


@router.patch("/answers/{answer_id}/grade")
def adjust_grade(answer_id: int, payload: GradeAdjustment, request: Request, actor: dict = Depends(require_roles("Teacher"))):
    return _call(lambda: _service(request).adjust_grade(
        answer_id, score=payload.adjusted_score,
        justification=payload.teacher_justification, notes=payload.teacher_notes,
        teacher_user_id=int(actor["UserId"]),
    ))


@router.post("/answers/{answer_id}/approve")
def approve_grade(answer_id: int, payload: ScoreApproval, request: Request, actor: dict = Depends(require_roles("Admin"))):
    return _call(lambda: _service(request).approve_grade(
        answer_id, score=payload.approved_score, note=payload.approval_note,
        admin_user_id=int(actor["UserId"]),
    ))


@router.get("/exams/{exam_id}/results")
def exam_results(exam_id: int, request: Request, actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer"))):
    return _call(lambda: _service(request).exam_results(exam_id))
