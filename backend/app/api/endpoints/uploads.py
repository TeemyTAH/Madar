from __future__ import annotations

import json
import mimetypes
import sqlite3
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from ai_engine.image_processing.processor import (
    ImageProcessor,
    ImageProcessingError,
)
from backend.app.core.security import require_roles
from backend.app.services.processing_runs import utc_now
from backend.app.services.academic_service import ensure_answer_rows


router = APIRouter(prefix="/uploads", tags=["Uploads"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("/pages/{page_id}/image")
def get_answer_page_image(
    page_id: int,
    request: Request,
    variant: str = Query(default="original", pattern="^(original|processed)$"),
    actor: dict = Depends(require_roles("Admin", "Teacher", "Reviewer")),
):
    """Serve an image already registered in AnswerPages, never an arbitrary path."""
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized")

    column = "OriginalImagePath" if variant == "original" else "PreprocessedImagePath"
    with manager.connection() as conn:
        row = conn.execute(
            f"SELECT {column} AS ImagePath FROM AnswerPages WHERE PageId=?",
            (page_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Answer page not found")
    if not row["ImagePath"]:
        raise HTTPException(status_code=404, detail=f"{variant.title()} image is not available")

    image_path = (manager.base_dir / str(row["ImagePath"])).resolve()
    allowed_root = (
        manager.original_images_dir if variant == "original" else manager.processed_images_dir
    ).resolve()
    try:
        image_path.relative_to(allowed_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Stored image path is outside the expected image directory") from exc

    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Stored answer image is missing")

    media_type, _ = mimetypes.guess_type(image_path.name)
    if not media_type or not media_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Stored file is not a supported image")

    return FileResponse(
        image_path,
        media_type=media_type,
        filename=image_path.name,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def remove_generated_files(base_dir: Path, paths: list[str]) -> None:
    """Remove generated images if database persistence fails."""
    for relative_path in paths:
        try:
            path = (base_dir / relative_path).resolve()
            path.relative_to(base_dir.resolve())
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


@router.post("/answer-page", status_code=201)
def upload_answer_page(
    request: Request,
    exam_student_id: int = Form(..., gt=0),
    page_number: int = Form(..., gt=0),
    file: UploadFile = File(...),
):
    manager = request.app.state.db_manager

    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix not in ImageProcessor.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image format.",
        )

    temp_dir = manager.storage_dir / "temp_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)

    temp_path = temp_dir / f"{uuid.uuid4().hex}{suffix}"
    generated_paths: list[str] = []

    try:
        total_bytes = 0

        with temp_path.open("wb") as destination:
            while True:
                chunk = file.file.read(1024 * 1024)

                if not chunk:
                    break

                total_bytes += len(chunk)

                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Image exceeds the 20 MB upload limit.",
                    )

                destination.write(chunk)

        if total_bytes == 0:
            raise HTTPException(
                status_code=400,
                detail="Uploaded image is empty.",
            )

        # Validate the student-exam relationship before image processing.
        with manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            exam_student = conn.execute(
                """
                SELECT ExamStudentId
                FROM ExamStudents
                WHERE ExamStudentId = ?
                """,
                (exam_student_id,),
            ).fetchone()

            if exam_student is None:
                raise HTTPException(
                    status_code=404,
                    detail="Student is not registered in this exam.",
                )

            sheets = conn.execute(
                """
                SELECT AnswerSheetId, ProcessingStatus
                FROM AnswerSheets
                WHERE ExamStudentId = ?
                ORDER BY AnswerSheetId
                """,
                (exam_student_id,),
            ).fetchall()

            if len(sheets) > 1:
                raise HTTPException(
                    status_code=409,
                    detail="Multiple answer sheets exist for this exam student.",
                )
            if sheets and sheets[0]["ProcessingStatus"] in {"REVIEWED", "FINALLY_APPROVED"}:
                raise HTTPException(
                    status_code=409,
                    detail="This answer sheet is already reviewed or finally approved.",
                )

            if sheets:
                existing_page = conn.execute(
                    """
                    SELECT PageId
                    FROM AnswerPages
                    WHERE AnswerSheetId = ? AND PageNumber = ?
                    """,
                    (sheets[0]["AnswerSheetId"], page_number),
                ).fetchone()

                if existing_page:
                    raise HTTPException(
                        status_code=409,
                        detail="This answer page already exists.",
                    )

        # Process the uploaded image and capture a durable processing record.
        processor = ImageProcessor(project_root=manager.base_dir)
        image_started_at = utc_now()
        image_started_counter = time.perf_counter()
        result = processor.process_image(temp_path)
        image_completed_at = utc_now()
        image_duration_ms = max(0, int(round((time.perf_counter() - image_started_counter) * 1000)))

        generated_paths = [
            result.original_path,
            result.processed_path,
        ]

        # Persist the answer sheet and page atomically.
        with manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            exam_student = conn.execute(
                """
                SELECT ExamStudentId
                FROM ExamStudents
                WHERE ExamStudentId = ?
                """,
                (exam_student_id,),
            ).fetchone()

            if exam_student is None:
                raise HTTPException(
                    status_code=404,
                    detail="Exam student no longer exists.",
                )

            sheets = conn.execute(
                """
                SELECT AnswerSheetId, ProcessingStatus
                FROM AnswerSheets
                WHERE ExamStudentId = ?
                ORDER BY AnswerSheetId
                """,
                (exam_student_id,),
            ).fetchall()

            if len(sheets) > 1:
                raise HTTPException(
                    status_code=409,
                    detail="Multiple answer sheets exist for this exam student.",
                )
            if sheets and sheets[0]["ProcessingStatus"] in {"REVIEWED", "FINALLY_APPROVED"}:
                raise HTTPException(
                    status_code=409,
                    detail="This answer sheet is already reviewed or finally approved.",
                )

            if sheets:
                answer_sheet_id = sheets[0]["AnswerSheetId"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO AnswerSheets (ExamStudentId)
                    VALUES (?)
                    """,
                    (exam_student_id,),
                )
                answer_sheet_id = cursor.lastrowid

            # Every sheet starts with one answer record per configured exam question.
            # This keeps the gradebook complete even when a sheet is created by upload.
            ensure_answer_rows(conn, int(answer_sheet_id))

            existing_page = conn.execute(
                """
                SELECT PageId
                FROM AnswerPages
                WHERE AnswerSheetId = ? AND PageNumber = ?
                """,
                (answer_sheet_id, page_number),
            ).fetchone()

            if existing_page:
                raise HTTPException(
                    status_code=409,
                    detail="This answer page already exists.",
                )

            cursor = conn.execute(
                """
                INSERT INTO AnswerPages (
                    AnswerSheetId,
                    PageNumber,
                    OriginalImagePath,
                    PreprocessedImagePath,
                    ImageQualityStatus,
                    ImageWidth,
                    ImageHeight
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    answer_sheet_id,
                    page_number,
                    result.original_path,
                    result.processed_path,
                    result.quality_status,
                    result.image_width,
                    result.image_height,
                ),
            )

            page_id = cursor.lastrowid

            processing_status = "REQUIRES_REVIEW" if result.quality_status != "VALID" else "SUCCEEDED"
            run_cursor = conn.execute(
                """
                INSERT INTO AIProcessingRuns (
                    AnswerSheetId, PageId, Stage, ModelName, ModelVersion, Status,
                    InputReference, OutputReference, OutputJson, StartedAt, CompletedAt, DurationMs
                ) VALUES (?, ?, 'IMAGE_PROCESSING', 'Madar-ImageProcessor', '1.0.0', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    answer_sheet_id,
                    page_id,
                    processing_status,
                    result.original_path,
                    result.processed_path,
                    json.dumps(result.to_dict(), ensure_ascii=False),
                    image_started_at,
                    image_completed_at,
                    image_duration_ms,
                ),
            )
            processing_run_id = int(run_cursor.lastrowid)
            if processing_status == "REQUIRES_REVIEW":
                conn.execute(
                    "UPDATE AnswerSheets SET ProcessingStatus='PENDING_REVIEW', UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerSheetId=? AND ProcessingStatus NOT IN ('REVIEWED','FINALLY_APPROVED')",
                    (answer_sheet_id,),
                )

        return {
            "status": "success",
            "message": "Answer page uploaded and processed successfully.",
            "answer_sheet_id": answer_sheet_id,
            "page_id": page_id,
            "exam_student_id": exam_student_id,
            "page_number": page_number,
            "processing_run_id": processing_run_id,
            "image": result.to_dict(),
        }

    except HTTPException:
        remove_generated_files(manager.base_dir, generated_paths)
        raise

    except ImageProcessingError as exc:
        remove_generated_files(manager.base_dir, generated_paths)
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except sqlite3.IntegrityError as exc:
        remove_generated_files(manager.base_dir, generated_paths)
        raise HTTPException(
            status_code=409,
            detail="Database integrity conflict while saving the answer page.",
        ) from exc

    except Exception as exc:
        remove_generated_files(manager.base_dir, generated_paths)
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while uploading the answer page.",
        ) from exc

    finally:
        temp_path.unlink(missing_ok=True)
        file.file.close()
