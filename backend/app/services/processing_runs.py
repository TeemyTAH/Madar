from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from backend.app.database.database_manager import DatabaseManager


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ProcessingRunTracker:
    """Persist the PENDING -> RUNNING -> terminal lifecycle in AIProcessingRuns."""

    def __init__(self, manager: DatabaseManager) -> None:
        self.manager = manager

    def create(
        self,
        *,
        answer_sheet_id: int,
        stage: str,
        page_id: int | None = None,
        answer_id: int | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        input_reference: str | None = None,
    ) -> int:
        with self.manager.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO AIProcessingRuns (
                    AnswerSheetId, PageId, AnswerId, Stage, ModelName,
                    ModelVersion, Status, InputReference
                ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    answer_sheet_id, page_id, answer_id, stage,
                    model_name, model_version, input_reference,
                ),
            )
            return int(cursor.lastrowid)

    def start(self, run_id: int) -> float:
        started = time.perf_counter()
        with self.manager.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE AIProcessingRuns
                SET Status='RUNNING', StartedAt=?
                WHERE ProcessingRunId=? AND Status='PENDING'
                """,
                (utc_now(), run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Processing run {run_id} cannot transition to RUNNING")
        return started

    def finish(
        self,
        run_id: int,
        started_counter: float,
        *,
        status: str,
        output: dict[str, Any] | list[Any] | None = None,
        output_reference: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if status not in {"SUCCEEDED", "FAILED", "REQUIRES_REVIEW"}:
            raise ValueError(f"Invalid terminal processing status: {status}")
        completed_at = utc_now()
        duration_ms = max(0, int(round((time.perf_counter() - started_counter) * 1000)))
        output_json = json.dumps(output, ensure_ascii=False, separators=(",", ":")) if output is not None else None
        with self.manager.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE AIProcessingRuns
                SET Status=?, CompletedAt=?, DurationMs=?, OutputJson=?,
                    OutputReference=?, ErrorMessage=?
                WHERE ProcessingRunId=? AND Status='RUNNING'
                """,
                (
                    status, completed_at, duration_ms, output_json,
                    output_reference, error_message, run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Processing run {run_id} is not RUNNING")

    def fail_if_running(self, run_id: int, started_counter: float, exc: Exception) -> None:
        try:
            self.finish(
                run_id,
                started_counter,
                status="FAILED",
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
            )
        except (sqlite3.Error, RuntimeError):
            # Preserve the original processing error if the status write also fails.
            pass


def refresh_answer_sheet_status(manager: DatabaseManager, answer_sheet_id: int) -> str:
    """Recalculate sheet processing status without downgrading reviewed/final sheets."""
    with manager.connection() as conn:
        sheet = conn.execute(
            "SELECT ProcessingStatus, ExamStudentId FROM AnswerSheets WHERE AnswerSheetId=?",
            (answer_sheet_id,),
        ).fetchone()
        if sheet is None:
            raise ValueError(f"Answer sheet {answer_sheet_id} does not exist")
        current = str(sheet["ProcessingStatus"])
        if current in {"REVIEWED", "FINALLY_APPROVED"}:
            return current

        needs_review = conn.execute(
            """
            SELECT COUNT(*)
            FROM QuestionAnswers
            WHERE AnswerSheetId=? AND (NeedsOcrReview=1 OR NeedsGradingReview=1)
            """,
            (answer_sheet_id,),
        ).fetchone()[0]
        total_questions = conn.execute(
            """
            SELECT COUNT(*)
            FROM ExamStudents ES
            JOIN Questions Q ON Q.ExamId=ES.ExamId
            WHERE ES.ExamStudentId=?
            """,
            (sheet["ExamStudentId"],),
        ).fetchone()[0]
        completed_answers = conn.execute(
            """
            SELECT COUNT(*)
            FROM QuestionAnswers QA
            JOIN Questions Q ON Q.QuestionId=QA.QuestionId
            WHERE QA.AnswerSheetId=?
              AND (
                    QA.IsEmptyAnswer=1
                    OR (Q.QuestionType IN ('MULTIPLE_CHOICE','TRUE_FALSE') AND QA.SelectedChoiceId IS NOT NULL)
                    OR (Q.QuestionType NOT IN ('MULTIPLE_CHOICE','TRUE_FALSE')
                        AND (QA.EditedText IS NOT NULL OR QA.ExtractedText IS NOT NULL))
              )
            """,
            (answer_sheet_id,),
        ).fetchone()[0]

        if needs_review:
            new_status = "PENDING_REVIEW"
        elif total_questions > 0 and completed_answers >= total_questions:
            new_status = "PROCESSED"
        else:
            new_status = "NOT_PROCESSED"

        if new_status != current:
            conn.execute(
                "UPDATE AnswerSheets SET ProcessingStatus=?, UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerSheetId=?",
                (new_status, answer_sheet_id),
            )
        return new_status
