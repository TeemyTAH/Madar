from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from statistics import median
from typing import Any

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from backend.app.database.database_manager import DatabaseManager


class ReportError(RuntimeError):
    pass


class ReportNotFoundError(ReportError):
    pass


class ReportValidationError(ReportError):
    pass


class ReportingService:
    """Read-only academic analytics and approved-grade export service.

    Final result fields are deliberately derived only from QuestionAnswers rows
    whose IsApproved flag is 1. Suggested and adjusted scores are never exposed
    in gradebook exports or student transcripts.
    """

    DISTRIBUTION_BANDS = (
        (0.0, 50.0, "0–49.99%"),
        (50.0, 60.0, "50–59.99%"),
        (60.0, 70.0, "60–69.99%"),
        (70.0, 80.0, "70–79.99%"),
        (80.0, 90.0, "80–89.99%"),
        (90.0, 100.0000001, "90–100%"),
    )

    def __init__(self, manager: DatabaseManager) -> None:
        self.manager = manager

    @staticmethod
    def _round(value: float | int | None, digits: int = 2) -> float | None:
        return round(float(value), digits) if value is not None else None

    @staticmethod
    def _final_score(question_count: int, approved_count: int, score_sum: float) -> float | None:
        if question_count <= 0 or approved_count != question_count:
            return None
        return float(score_sum)

    def _exam_row(self, conn: sqlite3.Connection, exam_id: int) -> dict[str, Any]:
        row = conn.execute(
            """SELECT E.ExamId, E.Title, E.SubjectName, E.ExamDate, E.TotalMarks,
                      E.CreatedAt, E.CreatedByUserId,
                      (SELECT COUNT(*) FROM Questions Q WHERE Q.ExamId=E.ExamId) AS QuestionCount,
                      (SELECT COALESCE(SUM(Q.MaxMarks), 0) FROM Questions Q WHERE Q.ExamId=E.ExamId) AS AllocatedQuestionMarks,
                      (SELECT COUNT(*) FROM ExamStudents ES WHERE ES.ExamId=E.ExamId) AS EnrolledCount
               FROM Exams E WHERE E.ExamId=?""",
            (exam_id,),
        ).fetchone()
        if row is None:
            raise ReportNotFoundError(f"Exam {exam_id} was not found")
        return dict(row)

    def _gradebook_rows(self, conn: sqlite3.Connection, exam_id: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        exam = self._exam_row(conn, exam_id)
        questions = [dict(row) for row in conn.execute(
            """SELECT QuestionId, QuestionNumber, QuestionType, QuestionText, MaxMarks
               FROM Questions WHERE ExamId=? ORDER BY QuestionNumber, QuestionId""",
            (exam_id,),
        ).fetchall()]
        rows = conn.execute(
            """SELECT ES.ExamStudentId, ST.StudentId, ST.AcademicId, ST.FullName,
                      S.AnswerSheetId, S.ProcessingStatus, S.IsBlankOrUnreadable,
                      (SELECT COUNT(*) FROM Questions Q WHERE Q.ExamId=ES.ExamId) AS QuestionCount,
                      (SELECT COUNT(*) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId) AS AnswerCount,
                      (SELECT COUNT(*) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId AND QA.IsApproved=1) AS ApprovedCount,
                      (SELECT COALESCE(SUM(QA.ApprovedScore),0) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId AND QA.IsApproved=1) AS ApprovedScoreSum
               FROM ExamStudents ES
               JOIN Students ST ON ST.StudentId=ES.StudentId
               LEFT JOIN AnswerSheets S ON S.ExamStudentId=ES.ExamStudentId
               WHERE ES.ExamId=?
               ORDER BY ST.FullName COLLATE NOCASE, ST.StudentId""",
            (exam_id,),
        ).fetchall()

        answer_rows = conn.execute(
            """SELECT S.ExamStudentId, QA.QuestionId, QA.ApprovedScore, QA.IsApproved
               FROM ExamStudents ES
               JOIN AnswerSheets S ON S.ExamStudentId=ES.ExamStudentId
               JOIN QuestionAnswers QA ON QA.AnswerSheetId=S.AnswerSheetId
               WHERE ES.ExamId=?""",
            (exam_id,),
        ).fetchall()
        scores_by_student: dict[int, dict[int, float | None]] = {}
        for answer in answer_rows:
            student_key = int(answer["ExamStudentId"])
            question_key = int(answer["QuestionId"])
            scores_by_student.setdefault(student_key, {})[question_key] = (
                float(answer["ApprovedScore"]) if int(answer["IsApproved"]) == 1 and answer["ApprovedScore"] is not None else None
            )

        items: list[dict[str, Any]] = []
        q_count = len(questions)
        total_marks = float(exam["TotalMarks"])
        for raw in rows:
            item = dict(raw)
            exam_student_id = int(item["ExamStudentId"])
            score_map = scores_by_student.get(exam_student_id, {})
            approved_count = int(item["ApprovedCount"] or 0)
            final_score = self._final_score(q_count, approved_count, float(item["ApprovedScoreSum"] or 0))
            item["question_count"] = q_count
            item["answer_count"] = int(item["AnswerCount"] or 0)
            item["approved_count"] = approved_count
            item["question_scores"] = score_map
            item["final_score"] = self._round(final_score)
            item["percentage"] = self._round((final_score / total_marks) * 100) if final_score is not None and total_marks > 0 else None
            item["completion_percent"] = self._round((approved_count / q_count) * 100) if q_count else 0.0
            if final_score is not None:
                item["result_status"] = "FINAL_APPROVED"
            elif item.get("AnswerSheetId") is None:
                item["result_status"] = "NO_ANSWER_SHEET"
            else:
                item["result_status"] = str(item.get("ProcessingStatus") or "PENDING_REVIEW")
            items.append(item)
        return exam, questions, items

    def get_exam_gradebook(self, exam_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN")
            exam, questions, items = self._gradebook_rows(conn, exam_id)
        return {
            "exam": exam,
            "questions": questions,
            "items": items,
            "enrolled_count": len(items),
            "finalized_count": sum(item["final_score"] is not None for item in items),
            "pending_count": sum(item["final_score"] is None for item in items),
            "score_policy": "Only fully approved question scores are included; provisional scores are excluded.",
        }

    def get_exam_analytics(self, exam_id: int, *, pass_threshold_percent: float = 50.0) -> dict[str, Any]:
        if not 0 <= float(pass_threshold_percent) <= 100:
            raise ReportValidationError("pass_threshold_percent must be between 0 and 100")
        with self.manager.connection() as conn:
            conn.execute("BEGIN")
            return self._exam_analytics_from_connection(conn, exam_id, pass_threshold_percent)

    def _exam_analytics_from_connection(
        self,
        conn: sqlite3.Connection,
        exam_id: int,
        pass_threshold_percent: float,
    ) -> dict[str, Any]:
        exam, questions, items = self._gradebook_rows(conn, exam_id)
        page_metrics = conn.execute(
            """SELECT COUNT(*) AS PageCount,
                      SUM(CASE WHEN P.ImageQualityStatus='LOW_QUALITY' THEN 1 ELSE 0 END) AS LowQualityPages,
                      SUM(CASE WHEN P.ImageQualityStatus='INVALID' THEN 1 ELSE 0 END) AS InvalidPages
               FROM AnswerPages P
               JOIN AnswerSheets S ON S.AnswerSheetId=P.AnswerSheetId
               JOIN ExamStudents ES ON ES.ExamStudentId=S.ExamStudentId
               WHERE ES.ExamId=?""",
            (exam_id,),
        ).fetchone()
        review_metrics = conn.execute(
            """SELECT COUNT(*) AS AnswerCount,
                      SUM(CASE WHEN QA.NeedsOcrReview=1 AND QA.IsApproved=0 THEN 1 ELSE 0 END) AS OcrReviewCount,
                      SUM(CASE WHEN QA.NeedsGradingReview=1 AND QA.IsApproved=0 THEN 1 ELSE 0 END) AS GradingReviewCount,
                      SUM(CASE WHEN QA.IsEmptyAnswer=1 THEN 1 ELSE 0 END) AS EmptyAnswerCount
               FROM QuestionAnswers QA
               JOIN AnswerSheets S ON S.AnswerSheetId=QA.AnswerSheetId
               JOIN ExamStudents ES ON ES.ExamStudentId=S.ExamStudentId
               WHERE ES.ExamId=?""",
            (exam_id,),
        ).fetchone()
        failed_ai_runs = int(conn.execute(
            """SELECT COUNT(*) FROM AIProcessingRuns R
               JOIN AnswerSheets S ON S.AnswerSheetId=R.AnswerSheetId
               JOIN ExamStudents ES ON ES.ExamStudentId=S.ExamStudentId
               WHERE ES.ExamId=? AND R.Status='FAILED'""",
            (exam_id,),
        ).fetchone()[0])
        question_rows = conn.execute(
            """SELECT Q.QuestionId, Q.QuestionNumber, Q.QuestionType, Q.QuestionText, Q.MaxMarks,
                      COUNT(QA.AnswerId) AS AnswerCount,
                      SUM(CASE WHEN QA.IsApproved=1 THEN 1 ELSE 0 END) AS ApprovedCount,
                      AVG(CASE WHEN QA.IsApproved=1 THEN QA.ApprovedScore END) AS AverageApprovedScore,
                      SUM(CASE WHEN QA.IsApproved=1 AND ABS(QA.ApprovedScore-Q.MaxMarks)<0.000001 THEN 1 ELSE 0 END) AS FullMarkCount,
                      SUM(CASE WHEN QA.IsApproved=1 AND ABS(QA.ApprovedScore)<0.000001 THEN 1 ELSE 0 END) AS ZeroMarkCount,
                      SUM(CASE WHEN QA.IsEmptyAnswer=1 THEN 1 ELSE 0 END) AS EmptyAnswerCount,
                      SUM(CASE WHEN QA.NeedsGradingReview=1 AND QA.IsApproved=0 THEN 1 ELSE 0 END) AS PendingReviewCount
               FROM Questions Q
               LEFT JOIN ExamStudents ES ON ES.ExamId=Q.ExamId
               LEFT JOIN AnswerSheets S ON S.ExamStudentId=ES.ExamStudentId
               LEFT JOIN QuestionAnswers QA ON QA.AnswerSheetId=S.AnswerSheetId AND QA.QuestionId=Q.QuestionId
               WHERE Q.ExamId=?
               GROUP BY Q.QuestionId
               ORDER BY Q.QuestionNumber, Q.QuestionId""",
            (exam_id,),
        ).fetchall()

        final_items = [item for item in items if item["final_score"] is not None]
        scores = [float(item["final_score"]) for item in final_items]
        percentages = [float(item["percentage"]) for item in final_items if item["percentage"] is not None]
        passed = sum(value >= float(pass_threshold_percent) for value in percentages)
        failed = len(percentages) - passed
        total_enrolled = len(items)
        q_analysis: list[dict[str, Any]] = []
        for raw in question_rows:
            item = dict(raw)
            approved_count = int(item["ApprovedCount"] or 0)
            average_score = float(item["AverageApprovedScore"]) if item["AverageApprovedScore"] is not None else None
            max_marks = float(item["MaxMarks"])
            average_percent = (average_score / max_marks) * 100 if average_score is not None and max_marks > 0 else None
            item.update({
                "question_id": int(item["QuestionId"]),
                "question_number": int(item["QuestionNumber"]),
                "question_type": str(item["QuestionType"]),
                "question_text": str(item["QuestionText"]),
                "max_marks": max_marks,
                "answer_count": int(item["AnswerCount"] or 0),
                "approved_count": approved_count,
                "pending_count": max(0, int(item["AnswerCount"] or 0) - approved_count),
                "average_approved_score": self._round(average_score),
                "average_percent": self._round(average_percent),
                "full_mark_count": int(item["FullMarkCount"] or 0),
                "zero_mark_count": int(item["ZeroMarkCount"] or 0),
                "empty_answer_count": int(item["EmptyAnswerCount"] or 0),
                "pending_review_count": int(item["PendingReviewCount"] or 0),
                "difficulty_status": "INSUFFICIENT_APPROVED_DATA" if average_percent is None else ("HIGH_DIFFICULTY" if average_percent < 40 else "MODERATE_DIFFICULTY" if average_percent < 70 else "LOW_DIFFICULTY"),
            })
            q_analysis.append(item)

        distribution = []
        for low, high, label in self.DISTRIBUTION_BANDS:
            count = sum(low <= value < high for value in percentages)
            distribution.append({"band": label, "count": count, "percent_of_final_results": self._round(count / len(percentages) * 100) if percentages else 0.0})

        ranked_questions = sorted(
            (q for q in q_analysis if q["average_percent"] is not None),
            key=lambda q: (q["average_percent"], -q["approved_count"], q["question_number"]),
        )
        page_data = dict(page_metrics) if page_metrics else {}
        review_data = dict(review_metrics) if review_metrics else {}
        final_count = len(final_items)
        return {
            "exam": exam,
            "summary": {
                "enrolled_students": total_enrolled,
                "answer_sheets": sum(item.get("AnswerSheetId") is not None for item in items),
                "students_without_answer_sheet": sum(item.get("AnswerSheetId") is None for item in items),
                "question_count": len(questions),
                "final_results_count": final_count,
                "pending_results_count": total_enrolled - final_count,
                "pass_threshold_percent": float(pass_threshold_percent),
                "passed_count": passed,
                "failed_count": failed,
                "pass_rate_percent": self._round(passed / final_count * 100) if final_count else None,
                "average_final_score": self._round(sum(scores) / len(scores)) if scores else None,
                "median_final_score": self._round(median(scores)) if scores else None,
                "highest_final_score": self._round(max(scores)) if scores else None,
                "lowest_final_score": self._round(min(scores)) if scores else None,
                "average_final_percent": self._round(sum(percentages) / len(percentages)) if percentages else None,
                "total_pages": int(page_data.get("PageCount") or 0),
                "low_quality_pages": int(page_data.get("LowQualityPages") or 0),
                "invalid_pages": int(page_data.get("InvalidPages") or 0),
                "answer_records": int(review_data.get("AnswerCount") or 0),
                "ocr_review_pending": int(review_data.get("OcrReviewCount") or 0),
                "grading_review_pending": int(review_data.get("GradingReviewCount") or 0),
                "empty_answers": int(review_data.get("EmptyAnswerCount") or 0),
                "failed_ai_runs": failed_ai_runs,
            },
            "score_distribution": distribution,
            "question_analysis": q_analysis,
            "hardest_questions": ranked_questions[:3],
            "score_policy": "Only students with an approved score for every configured question are included in final score statistics. Provisional scores are excluded.",
        }

    def get_student_report(self, student_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN")
            student_row = conn.execute(
                "SELECT StudentId, AcademicId, FullName, CreatedAt FROM Students WHERE StudentId=?",
                (student_id,),
            ).fetchone()
            if student_row is None:
                raise ReportNotFoundError(f"Student {student_id} was not found")
            rows = conn.execute(
                """SELECT E.ExamId, E.Title, E.SubjectName, E.ExamDate, E.TotalMarks,
                          ES.ExamStudentId, S.AnswerSheetId, S.ProcessingStatus,
                          (SELECT COUNT(*) FROM Questions Q WHERE Q.ExamId=E.ExamId) AS QuestionCount,
                          (SELECT COUNT(*) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId) AS AnswerCount,
                          (SELECT COUNT(*) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId AND QA.IsApproved=1) AS ApprovedCount,
                          (SELECT COALESCE(SUM(QA.ApprovedScore),0) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId AND QA.IsApproved=1) AS ApprovedScoreSum
                   FROM ExamStudents ES
                   JOIN Exams E ON E.ExamId=ES.ExamId
                   LEFT JOIN AnswerSheets S ON S.ExamStudentId=ES.ExamStudentId
                   WHERE ES.StudentId=?
                   ORDER BY COALESCE(E.ExamDate,E.CreatedAt) DESC, E.ExamId DESC""",
                (student_id,),
            ).fetchall()

        exams: list[dict[str, Any]] = []
        final_percentages: list[float] = []
        for raw in rows:
            item = dict(raw)
            question_count = int(item["QuestionCount"] or 0)
            approved_count = int(item["ApprovedCount"] or 0)
            final_score = self._final_score(question_count, approved_count, float(item["ApprovedScoreSum"] or 0))
            percentage = (final_score / float(item["TotalMarks"])) * 100 if final_score is not None else None
            if percentage is not None:
                final_percentages.append(percentage)
            item.update({
                "question_count": question_count,
                "answer_count": int(item["AnswerCount"] or 0),
                "approved_count": approved_count,
                "final_score": self._round(final_score),
                "percentage": self._round(percentage),
                "result_status": "FINAL_APPROVED" if final_score is not None else ("NO_ANSWER_SHEET" if item["AnswerSheetId"] is None else str(item["ProcessingStatus"] or "PENDING_REVIEW")),
            })
            exams.append(item)
        return {
            "student": dict(student_row),
            "summary": {
                "enrolled_exams": len(exams),
                "final_results_count": len(final_percentages),
                "pending_results_count": len(exams) - len(final_percentages),
                "average_final_percent": self._round(sum(final_percentages) / len(final_percentages)) if final_percentages else None,
                "highest_final_percent": self._round(max(final_percentages)) if final_percentages else None,
                "lowest_final_percent": self._round(min(final_percentages)) if final_percentages else None,
            },
            "exams": exams,
            "score_policy": "Only fully approved final scores are shown. Provisional scores are excluded.",
        }

    def get_teacher_report(self, teacher_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN")
            teacher_row = conn.execute(
                "SELECT UserId, Username, FullName, RoleName, IsActive, CreatedAt, LastLoginAt FROM Users WHERE UserId=? AND RoleName='Teacher'",
                (teacher_id,),
            ).fetchone()
            if teacher_row is None:
                raise ReportNotFoundError(f"Teacher {teacher_id} was not found")

            exam_rows = conn.execute(
                """SELECT E.ExamId, E.Title, E.SubjectName, E.ExamDate, E.TotalMarks,
                          (SELECT COUNT(*) FROM Questions Q WHERE Q.ExamId=E.ExamId) AS QuestionCount,
                          (SELECT COUNT(*) FROM ExamStudents ES WHERE ES.ExamId=E.ExamId) AS EnrolledCount,
                          (SELECT COUNT(*) FROM ExamStudents ES JOIN AnswerSheets S ON S.ExamStudentId=ES.ExamStudentId WHERE ES.ExamId=E.ExamId) AS AnswerSheetCount,
                          (SELECT COUNT(*) FROM QuestionAnswers QA
                             JOIN AnswerSheets S ON S.AnswerSheetId=QA.AnswerSheetId
                             JOIN ExamStudents ES ON ES.ExamStudentId=S.ExamStudentId
                             WHERE ES.ExamId=E.ExamId AND QA.NeedsGradingReview=1 AND QA.IsApproved=0) AS PendingReviewCount
                   FROM Exams E WHERE E.CreatedByUserId=?
                   ORDER BY COALESCE(E.ExamDate,E.CreatedAt) DESC, E.ExamId DESC""",
                (teacher_id,),
            ).fetchall()
            activity_rows = conn.execute(
                """SELECT ActionType, COUNT(*) AS EventCount, MAX(CreatedAt) AS LastActivityAt
                   FROM AuditLogs WHERE PerformedByUserId=?
                   GROUP BY ActionType ORDER BY EventCount DESC, ActionType""",
                (teacher_id,),
            ).fetchall()
            review_counts = conn.execute(
                """SELECT COUNT(*) AS ReviewedAnswers,
                          SUM(CASE WHEN AdjustedScore IS NOT NULL THEN 1 ELSE 0 END) AS AdjustedAnswers
                   FROM QuestionAnswers WHERE ReviewedByUserId=?""",
                (teacher_id,),
            ).fetchone()
            performance_rows = conn.execute(
                """SELECT ES.ExamStudentId, E.TotalMarks,
                          COUNT(DISTINCT Q.QuestionId) AS QuestionCount,
                          COUNT(DISTINCT CASE WHEN QA.IsApproved=1 THEN QA.QuestionId END) AS ApprovedCount,
                          SUM(CASE WHEN QA.IsApproved=1 THEN QA.ApprovedScore ELSE 0 END) AS ApprovedScore
                   FROM Exams E
                   JOIN ExamStudents ES ON ES.ExamId=E.ExamId
                   LEFT JOIN Questions Q ON Q.ExamId=E.ExamId
                   LEFT JOIN AnswerSheets S ON S.ExamStudentId=ES.ExamStudentId
                   LEFT JOIN QuestionAnswers QA ON QA.AnswerSheetId=S.AnswerSheetId AND QA.QuestionId=Q.QuestionId
                   WHERE E.CreatedByUserId=?
                   GROUP BY ES.ExamStudentId""",
                (teacher_id,),
            ).fetchall()

        finalized_percentages = [
            (float(row["ApprovedScore"] or 0) / float(row["TotalMarks"])) * 100
            for row in performance_rows
            if int(row["QuestionCount"] or 0) > 0 and int(row["ApprovedCount"] or 0) == int(row["QuestionCount"] or 0)
        ]
        exams = [dict(row) for row in exam_rows]
        activity = [dict(row) for row in activity_rows]
        return {
            "teacher": dict(teacher_row),
            "summary": {
                "created_exams": len(exams),
                "total_enrollments": sum(int(row["EnrolledCount"] or 0) for row in exams),
                "answer_sheets": sum(int(row["AnswerSheetCount"] or 0) for row in exams),
                "pending_grading_reviews": sum(int(row["PendingReviewCount"] or 0) for row in exams),
                "reviewed_answers": int(review_counts["ReviewedAnswers"] or 0),
                "adjusted_answers": int(review_counts["AdjustedAnswers"] or 0),
                "finalized_student_results": len(finalized_percentages),
                "average_final_percent": self._round(sum(finalized_percentages) / len(finalized_percentages)) if finalized_percentages else None,
            },
            "created_exams": exams,
            "activity_by_type": activity,
            "score_policy": "Performance percentages include only student results with every question finally approved. Provisional scores are excluded.",
        }

    def get_overview(self) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN")
            counts = conn.execute(
                """SELECT
                    (SELECT COUNT(*) FROM Students) AS Students,
                    (SELECT COUNT(*) FROM Exams) AS Exams,
                    (SELECT COUNT(*) FROM Users WHERE IsActive=1 AND RoleName='Teacher') AS ActiveTeachers,
                    (SELECT COUNT(*) FROM ExamStudents) AS Enrollments,
                    (SELECT COUNT(*) FROM AnswerSheets) AS AnswerSheets,
                    (SELECT COUNT(*) FROM AnswerPages) AS AnswerPages,
                    (SELECT COUNT(*) FROM QuestionAnswers) AS AnswerRecords,
                    (SELECT COUNT(*) FROM QuestionAnswers WHERE IsApproved=1) AS ApprovedAnswers,
                    (SELECT COUNT(*) FROM QuestionAnswers WHERE IsApproved=0 AND NeedsOcrReview=1) AS PendingOcrReview,
                    (SELECT COUNT(*) FROM QuestionAnswers WHERE IsApproved=0 AND NeedsGradingReview=1) AS PendingGradingReview,
                    (SELECT COUNT(*) FROM AnswerSheets S WHERE EXISTS (
                        SELECT 1 FROM ExamStudents ES JOIN Questions Q ON Q.ExamId=ES.ExamId
                        WHERE ES.ExamStudentId=S.ExamStudentId
                    ) AND NOT EXISTS (
                        SELECT 1 FROM ExamStudents ES JOIN Questions Q ON Q.ExamId=ES.ExamId
                        WHERE ES.ExamStudentId=S.ExamStudentId AND NOT EXISTS (
                            SELECT 1 FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId AND QA.QuestionId=Q.QuestionId AND QA.IsApproved=1
                        )
                    )) AS FullyApprovedSheets,
                    (SELECT COUNT(*) FROM AIProcessingRuns WHERE Status='FAILED') AS FailedAiRuns"""
            ).fetchone()
            recent = conn.execute(
                """SELECT E.ExamId, E.Title, E.SubjectName, E.ExamDate,
                          (SELECT COUNT(*) FROM ExamStudents ES WHERE ES.ExamId=E.ExamId) AS EnrolledCount,
                          (SELECT COUNT(*) FROM ExamStudents ES JOIN AnswerSheets S ON S.ExamStudentId=ES.ExamStudentId
                             WHERE ES.ExamId=E.ExamId) AS AnswerSheetCount
                   FROM Exams E ORDER BY COALESCE(E.ExamDate,E.CreatedAt) DESC, E.ExamId DESC LIMIT 5"""
            ).fetchall()
        return {"summary": dict(counts), "recent_exams": [dict(row) for row in recent]}

    @staticmethod
    def _safe_spreadsheet_text(value: Any) -> Any:
        """Prevent formula injection when untrusted text is opened in Excel/Calc."""
        if not isinstance(value, str):
            return value
        probe = value.lstrip(" \t\r\n")
        if probe.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    @staticmethod
    def _status_label(status: str) -> str:
        labels = {
            "FINAL_APPROVED": "معتمدة نهائياً",
            "NO_ANSWER_SHEET": "لا توجد ورقة إجابة",
            "NOT_PROCESSED": "لم تُعالج",
            "PROCESSED": "تمت المعالجة",
            "PENDING_REVIEW": "بانتظار المراجعة",
            "REVIEWED": "تمت المراجعة",
            "FINALLY_APPROVED": "معتمدة نهائياً",
        }
        return labels.get(status, status)

    def export_gradebook(self, exam_id: int, *, export_format: str, actor_user_id: int) -> tuple[bytes, str, str]:
        normalized_format = export_format.strip().lower()
        if normalized_format not in {"csv", "xlsx"}:
            raise ReportValidationError("format must be either 'csv' or 'xlsx'")
        with self.manager.connection() as conn:
            conn.execute("BEGIN")
            exam, questions, items = self._gradebook_rows(conn, exam_id)
            analytics = self._exam_analytics_from_connection(conn, exam_id, 50.0)

        base_filename = f"madar_exam_{exam_id}_gradebook"
        if normalized_format == "csv":
            payload = self._build_csv(exam, questions, items)
            media_type = "text/csv; charset=utf-8"
            filename = f"{base_filename}.csv"
        else:
            payload = self._build_xlsx(exam, questions, items, analytics)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename = f"{base_filename}.xlsx"

        details = json.dumps({"format": normalized_format, "filename": filename, "row_count": len(items), "approved_scores_only": True}, ensure_ascii=False)
        with self.manager.connection() as conn:
            conn.execute(
                """INSERT INTO AuditLogs (PerformedByUserId, EntityName, EntityId, ActionType, Details)
                   VALUES (?, 'Exams', ?, 'GRADEBOOK_EXPORTED', ?)""",
                (actor_user_id, str(exam_id), details),
            )
        return payload, media_type, filename

    @classmethod
    def _export_matrix(cls, questions: list[dict[str, Any]], items: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
        headers = ["الرقم الأكاديمي", "اسم الطالب", "حالة النتيجة", "الأسئلة المعتمدة", "إجمالي الأسئلة", "الدرجة النهائية المعتمدة", "النسبة المئوية"]
        headers.extend(f"سؤال {q['QuestionNumber']} ({q['MaxMarks']})" for q in questions)
        data: list[list[Any]] = []
        for item in items:
            final_score = item["final_score"]
            row: list[Any] = [
                cls._safe_spreadsheet_text(item["AcademicId"]),
                cls._safe_spreadsheet_text(item["FullName"]),
                cls._status_label(item["result_status"]),
                item["approved_count"], item["question_count"], final_score,
                item["percentage"],
            ]
            row.extend(item["question_scores"].get(int(q["QuestionId"])) for q in questions)
            data.append(row)
        return headers, data

    @classmethod
    def _build_csv(cls, exam: dict[str, Any], questions: list[dict[str, Any]], items: list[dict[str, Any]]) -> bytes:
        headers, data = cls._export_matrix(questions, items)
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, dialect="excel")
        writer.writerow(headers)
        writer.writerows(data)
        return ("\ufeff" + buffer.getvalue()).encode("utf-8")

    @classmethod
    def _build_xlsx(
        cls,
        exam: dict[str, Any],
        questions: list[dict[str, Any]],
        items: list[dict[str, Any]],
        analytics_report: dict[str, Any],
    ) -> bytes:
        workbook = Workbook()
        workbook.properties.creator = "Madar Smart Arabic Grader"
        workbook.properties.title = f"Gradebook - {str(exam['Title'])[:180]}"
        workbook.properties.subject = "Approved examination results"

        navy = "17365D"
        blue = "D9EAF7"
        pale = "F3F6FA"
        white = "FFFFFF"
        thin_gray = Side(style="thin", color="D9E1F2")

        grade_sheet = workbook.active
        grade_sheet.title = "كشف الدرجات"
        grade_sheet.sheet_view.rightToLeft = True
        grade_sheet.sheet_properties.pageSetUpPr.fitToPage = True
        grade_sheet.page_setup.orientation = "landscape"
        grade_sheet.page_setup.fitToWidth = 1
        grade_sheet.page_setup.fitToHeight = 0
        grade_sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(7, 7 + len(questions)))
        title_cell = grade_sheet.cell(1, 1, f"كشف درجات: {exam['Title']}")
        title_cell.font = Font(name="Arial", size=16, bold=True, color=white)
        title_cell.fill = PatternFill("solid", fgColor=navy)
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        grade_sheet.row_dimensions[1].height = 30
        grade_sheet.cell(2, 1, "المادة")
        grade_sheet.cell(2, 2, cls._safe_spreadsheet_text(exam["SubjectName"]))
        grade_sheet.cell(2, 4, "تاريخ الاختبار")
        grade_sheet.cell(2, 5, cls._safe_spreadsheet_text(exam.get("ExamDate") or "—"))
        grade_sheet.cell(3, 1, "الدرجة الكلية")
        grade_sheet.cell(3, 2, float(exam["TotalMarks"]))
        grade_sheet.cell(3, 4, "عدد الطلاب")
        grade_sheet.cell(3, 5, len(items))
        grade_sheet.cell(4, 1, "سياسة التصدير")
        grade_sheet.cell(4, 2, "الدرجات المعتمدة نهائياً فقط؛ الدرجات المقترحة أو المعدلة غير المعتمدة مستبعدة.")
        grade_sheet.merge_cells(start_row=4, start_column=2, end_row=4, end_column=max(7, 7 + len(questions)))
        for row in grade_sheet.iter_rows(min_row=2, max_row=4):
            for cell in row:
                cell.font = Font(name="Arial", size=10, bold=cell.column in (1, 4))
                cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
        grade_sheet.row_dimensions[4].height = 30

        headers, data = cls._export_matrix(questions, items)
        header_row = 6
        for col, value in enumerate(headers, start=1):
            cell = grade_sheet.cell(header_row, col, value)
            cell.font = Font(name="Arial", bold=True, color=white)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = Border(bottom=thin_gray)
        for row_index, row_data in enumerate(data, start=header_row + 1):
            for col_index, value in enumerate(row_data, start=1):
                cell = grade_sheet.cell(row_index, col_index, value)
                cell.font = Font(name="Arial", size=10)
                cell.alignment = Alignment(horizontal="right" if col_index <= 3 else "center", vertical="center")
                cell.fill = PatternFill("solid", fgColor=white if row_index % 2 else pale)
                cell.border = Border(bottom=thin_gray)
                if col_index in (6, *range(8, len(headers) + 1)) and value is not None:
                    cell.number_format = "0.00"
                if col_index == 7 and value is not None:
                    cell.number_format = '0.00"%"'
            grade_sheet.row_dimensions[row_index].height = 22
        if data:
            grade_sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{header_row + len(data)}"
        grade_sheet.freeze_panes = "C7"
        widths = {1: 18, 2: 30, 3: 22, 4: 16, 5: 15, 6: 22, 7: 16}
        for col, width in widths.items():
            grade_sheet.column_dimensions[get_column_letter(col)].width = width
        for col in range(8, len(headers) + 1):
            grade_sheet.column_dimensions[get_column_letter(col)].width = 15
        if data:
            grade_sheet.conditional_formatting.add(
                f"G{header_row + 1}:G{header_row + len(data)}",
                DataBarRule(start_type="num", start_value=0, end_type="num", end_value=100, color="5B9BD5", showValue=True),
            )

        analytics = workbook.create_sheet("تحليل الأسئلة")
        analytics.sheet_view.rightToLeft = True
        analysis_headers = ["رقم السؤال", "نوع السؤال", "نص السؤال", "الدرجة القصوى", "عدد الإجابات", "الإجابات المعتمدة", "متوسط الدرجة المعتمدة", "متوسط النسبة %", "إجابات فارغة", "بانتظار المراجعة"]
        for col, value in enumerate(analysis_headers, 1):
            cell = analytics.cell(1, col, value)
            cell.font = Font(name="Arial", bold=True, color=white)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
        question_stats = {int(item["question_id"]): item for item in analytics_report["question_analysis"]}
        for row_index, q in enumerate(questions, 2):
            stats = question_stats.get(int(q["QuestionId"]), {})
            analytics.append([
                q["QuestionNumber"], q["QuestionType"], cls._safe_spreadsheet_text(q["QuestionText"]), float(q["MaxMarks"]),
                stats.get("answer_count", 0), stats.get("approved_count", 0),
                stats.get("average_approved_score"), stats.get("average_percent"),
                stats.get("empty_answer_count", 0), stats.get("pending_review_count", 0),
            ])
            for cell in analytics[row_index]:
                cell.font = Font(name="Arial", size=10)
                cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
                cell.border = Border(bottom=thin_gray)
                if row_index % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor=pale)
        analytics.freeze_panes = "A2"
        analytics.auto_filter.ref = f"A1:J{max(1, len(questions) + 1)}"
        for col, width in enumerate([12, 20, 48, 15, 15, 17, 22, 18, 15, 18], 1):
            analytics.column_dimensions[get_column_letter(col)].width = width

        summary = workbook.create_sheet("ملخص")
        summary.sheet_view.rightToLeft = True
        summary.append(["المؤشر", "القيمة"])
        for cell in summary[1]:
            cell.font = Font(name="Arial", bold=True, color=white)
            cell.fill = PatternFill("solid", fgColor=navy)
        summary_metrics = analytics_report["summary"]
        summary_data = [
            ("الاختبار", exam["Title"]),
            ("المادة", exam["SubjectName"]),
            ("تاريخ الاختبار", exam.get("ExamDate") or "—"),
            ("الدرجة الكلية", float(exam["TotalMarks"])),
            ("عدد الطلاب المسجلين", summary_metrics["enrolled_students"]),
            ("النتائج المعتمدة نهائياً", summary_metrics["final_results_count"]),
            ("النتائج غير المكتملة", summary_metrics["pending_results_count"]),
            ("حد النجاح %", summary_metrics["pass_threshold_percent"]),
            ("عدد الناجحين", summary_metrics["passed_count"]),
            ("عدد غير الناجحين", summary_metrics["failed_count"]),
            ("نسبة النجاح بين النتائج المعتمدة %", summary_metrics["pass_rate_percent"]),
            ("متوسط الدرجة النهائية", summary_metrics["average_final_score"]),
            ("وسيط الدرجة النهائية", summary_metrics["median_final_score"]),
            ("أعلى درجة نهائية", summary_metrics["highest_final_score"]),
            ("أدنى درجة نهائية", summary_metrics["lowest_final_score"]),
            ("متوسط النسبة للنتائج المعتمدة %", summary_metrics["average_final_percent"]),
            ("صفحات منخفضة الجودة", summary_metrics["low_quality_pages"]),
            ("مراجعات OCR المعلقة", summary_metrics["ocr_review_pending"]),
            ("مراجعات التصحيح المعلقة", summary_metrics["grading_review_pending"]),
            ("عمليات ذكاء اصطناعي فاشلة", summary_metrics["failed_ai_runs"]),
            ("تاريخ إنشاء التقرير (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
            ("سياسة الدرجات", "الدرجات المعتمدة نهائياً فقط؛ لا تُصدّر الدرجات المقترحة أو المعدلة غير المعتمدة."),
        ]
        for pair in summary_data:
            summary.append([cls._safe_spreadsheet_text(value) for value in pair])
        for row in summary.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name="Arial", size=10, bold=cell.column == 1)
                cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
                cell.fill = PatternFill("solid", fgColor=blue if cell.row % 2 == 0 else pale)
                cell.border = Border(bottom=thin_gray)
        summary.column_dimensions["A"].width = 38
        summary.column_dimensions["B"].width = 70
        summary.freeze_panes = "A2"

        distribution = workbook.create_sheet("توزيع الدرجات")
        distribution.sheet_view.rightToLeft = True
        distribution_headers = ["نطاق النسبة", "عدد الطلاب", "النسبة من النتائج المعتمدة %"]
        for col, value in enumerate(distribution_headers, 1):
            cell = distribution.cell(1, col, value)
            cell.font = Font(name="Arial", bold=True, color=white)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
        for row_index, item in enumerate(analytics_report["score_distribution"], 2):
            distribution.append([item["band"], item["count"], item["percent_of_final_results"]])
            for cell in distribution[row_index]:
                cell.font = Font(name="Arial", size=10)
                cell.alignment = Alignment(horizontal="right", vertical="center")
                cell.border = Border(bottom=thin_gray)
                if row_index % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor=pale)
        distribution.column_dimensions["A"].width = 22
        distribution.column_dimensions["B"].width = 16
        distribution.column_dimensions["C"].width = 32
        distribution.freeze_panes = "A2"

        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()
