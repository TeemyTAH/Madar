from __future__ import annotations

import csv
import io
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app.api.endpoints.reports import router as reports_router
from backend.app.core.security import create_access_token, install_api_auth_middleware
from backend.app.database.database_manager import DatabaseManager
from backend.app.services.reporting_service import ReportNotFoundError, ReportingService


SECRET = b"test-signing-secret-for-madar-reporting"


def _setup(tmp_path: Path):
    db_dir = tmp_path / "backend" / "app" / "database"
    db_dir.mkdir(parents=True)
    schema = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
    shutil.copy2(schema, db_dir / "schema.sql")
    manager = DatabaseManager(base_dir=tmp_path)
    manager.initialize_database()
    with manager.connection() as conn:
        conn.execute("INSERT INTO Users (Username, FullName, PasswordHash, RoleName) VALUES ('admin', 'Admin', 'unused', 'Admin')")
        admin_id = int(conn.execute("SELECT UserId FROM Users WHERE Username='admin'").fetchone()[0])
        conn.execute("INSERT INTO Users (Username, FullName, PasswordHash, RoleName) VALUES ('teacher', 'Teacher', 'unused', 'Teacher')")
        teacher_id = int(conn.execute("SELECT UserId FROM Users WHERE Username='teacher'").fetchone()[0])
        conn.execute("INSERT INTO Students (AcademicId, FullName) VALUES ('ST-001', 'A Student')")
        student_a = int(conn.execute("SELECT StudentId FROM Students WHERE AcademicId='ST-001'").fetchone()[0])
        conn.execute("INSERT INTO Students (AcademicId, FullName) VALUES ('ST-002', 'B Student')")
        student_b = int(conn.execute("SELECT StudentId FROM Students WHERE AcademicId='ST-002'").fetchone()[0])
        conn.execute("INSERT INTO Exams (CreatedByUserId, Title, SubjectName, ExamDate, TotalMarks) VALUES (?, 'Arabic Midterm', 'Arabic', '2026-11-27', 20)", (teacher_id,))
        exam_id = int(conn.execute("SELECT ExamId FROM Exams").fetchone()[0])
        for number, maximum in ((1, 5), (2, 5), (3, 10)):
            conn.execute(
                "INSERT INTO Questions (ExamId, QuestionNumber, QuestionType, QuestionText, ModelAnswer, MaxMarks) VALUES (?, ?, 'ESSAY', ?, 'model answer', ?)",
                (exam_id, number, f'Question {number}', maximum),
            )
        question_ids = [int(row[0]) for row in conn.execute("SELECT QuestionId FROM Questions ORDER BY QuestionNumber")]
        conn.execute("INSERT INTO ExamStudents (ExamId, StudentId) VALUES (?, ?)", (exam_id, student_a))
        exam_student_a = int(conn.execute("SELECT ExamStudentId FROM ExamStudents WHERE StudentId=?", (student_a,)).fetchone()[0])
        conn.execute("INSERT INTO ExamStudents (ExamId, StudentId) VALUES (?, ?)", (exam_id, student_b))
        exam_student_b = int(conn.execute("SELECT ExamStudentId FROM ExamStudents WHERE StudentId=?", (student_b,)).fetchone()[0])
        conn.execute("INSERT INTO AnswerSheets (ExamStudentId, ProcessingStatus) VALUES (?, 'FINALLY_APPROVED')", (exam_student_a,))
        sheet_a = int(conn.execute("SELECT AnswerSheetId FROM AnswerSheets WHERE ExamStudentId=?", (exam_student_a,)).fetchone()[0])
        conn.execute("INSERT INTO AnswerSheets (ExamStudentId, ProcessingStatus) VALUES (?, 'PENDING_REVIEW')", (exam_student_b,))
        sheet_b = int(conn.execute("SELECT AnswerSheetId FROM AnswerSheets WHERE ExamStudentId=?", (exam_student_b,)).fetchone()[0])
        for qid, score in zip(question_ids, (5, 3, 2)):
            conn.execute(
                """INSERT INTO QuestionAnswers (AnswerSheetId, QuestionId, ExtractedText, ApprovedScore, IsApproved, ApprovedByUserId, ApprovedAt)
                   VALUES (?, ?, 'approved response', ?, 1, ?, CURRENT_TIMESTAMP)""",
                (sheet_a, qid, score, admin_id),
            )
        # One approved zero score plus two unapproved provisional suggestions.
        conn.execute(
            """INSERT INTO QuestionAnswers (AnswerSheetId, QuestionId, ApprovedScore, IsApproved, ApprovedByUserId, ApprovedAt)
               VALUES (?, ?, 0, 1, ?, CURRENT_TIMESTAMP)""",
            (sheet_b, question_ids[0], admin_id),
        )
        conn.execute(
            """INSERT INTO QuestionAnswers (AnswerSheetId, QuestionId, SuggestedScore, NeedsGradingReview)
               VALUES (?, ?, 5, 1)""",
            (sheet_b, question_ids[1]),
        )
        conn.execute(
            """INSERT INTO QuestionAnswers (AnswerSheetId, QuestionId, SuggestedScore, NeedsOcrReview, IsEmptyAnswer)
               VALUES (?, ?, 10, 1, 1)""",
            (sheet_b, question_ids[2]),
        )
        conn.execute("INSERT INTO AnswerPages (AnswerSheetId, PageNumber, OriginalImagePath, ImageQualityStatus, ImageWidth, ImageHeight) VALUES (?, 1, 'page-a.png', 'VALID', 1200, 1600)", (sheet_a,))
        conn.execute("INSERT INTO AnswerPages (AnswerSheetId, PageNumber, OriginalImagePath, ImageQualityStatus, ImageWidth, ImageHeight) VALUES (?, 1, 'page-b.png', 'LOW_QUALITY', 900, 1200)", (sheet_b,))
        page_b = int(conn.execute("SELECT PageId FROM AnswerPages WHERE AnswerSheetId=?", (sheet_b,)).fetchone()[0])
        conn.execute("INSERT INTO AIProcessingRuns (AnswerSheetId, PageId, Stage, Status, ErrorMessage) VALUES (?, ?, 'HTR', 'FAILED', 'synthetic test failure')", (sheet_b, page_b))
        conn.execute("INSERT INTO AuditLogs (PerformedByUserId, EntityName, EntityId, ActionType, Details) VALUES (?, 'Exams', ?, 'EXAM_CREATED', 'test activity')", (teacher_id, str(exam_id)))
    return manager, {"admin_id": admin_id, "teacher_id": teacher_id, "exam_id": exam_id, "student_a": student_a, "student_b": student_b, "question_ids": question_ids}


def test_exam_analytics_only_counts_fully_approved_final_results(tmp_path):
    manager, ids = _setup(tmp_path)
    report = ReportingService(manager).get_exam_analytics(ids["exam_id"], pass_threshold_percent=50)
    summary = report["summary"]
    assert summary["enrolled_students"] == 2
    assert summary["answer_sheets"] == 2
    assert summary["final_results_count"] == 1
    assert summary["pending_results_count"] == 1
    assert summary["average_final_score"] == 10.0
    assert summary["average_final_percent"] == 50.0
    assert summary["passed_count"] == 1
    assert summary["failed_count"] == 0
    assert summary["pass_rate_percent"] == 100.0
    assert summary["low_quality_pages"] == 1
    assert summary["ocr_review_pending"] == 1
    assert summary["grading_review_pending"] == 1
    assert summary["failed_ai_runs"] == 1
    assert report["hardest_questions"][0]["question_number"] == 3
    assert report["hardest_questions"][0]["average_percent"] == 20.0


def test_student_report_never_exposes_provisional_scores(tmp_path):
    manager, ids = _setup(tmp_path)
    report = ReportingService(manager).get_student_report(ids["student_b"])
    assert report["summary"]["enrolled_exams"] == 1
    assert report["summary"]["final_results_count"] == 0
    assert report["summary"]["pending_results_count"] == 1
    exam = report["exams"][0]
    assert exam["final_score"] is None
    assert exam["percentage"] is None
    assert "provisional_score" not in exam


def test_gradebook_and_exports_exclude_unapproved_scores_and_log_export(tmp_path):
    manager, ids = _setup(tmp_path)
    service = ReportingService(manager)
    gradebook = service.get_exam_gradebook(ids["exam_id"])
    pending = next(item for item in gradebook["items"] if item["StudentId"] == ids["student_b"])
    assert pending["final_score"] is None
    assert pending["question_scores"][ids["question_ids"][1]] is None

    xlsx_bytes, xlsx_type, xlsx_name = service.export_gradebook(ids["exam_id"], export_format="xlsx", actor_user_id=ids["admin_id"])
    assert xlsx_type.startswith("application/vnd.openxmlformats-officedocument")
    assert xlsx_name.endswith(".xlsx")
    workbook = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    assert workbook.sheetnames == ["كشف الدرجات", "تحليل الأسئلة", "ملخص", "توزيع الدرجات"]
    sheet = workbook["كشف الدرجات"]
    assert sheet.sheet_view.rightToLeft is True
    # Data starts on row 7; A Student is row 7 and B Student is row 8.
    pending_row = next(row for row in range(7, 9) if sheet.cell(row, 2).value == "B Student")
    assert sheet.cell(pending_row, 6).value is None
    assert sheet.cell(pending_row, 9).value is None  # Question 2 approved score column.
    question_analysis = workbook["تحليل الأسئلة"]
    assert question_analysis.cell(4, 8).value == 20.0
    assert question_analysis.cell(4, 10).value == 0

    csv_bytes, csv_type, csv_name = service.export_gradebook(ids["exam_id"], export_format="csv", actor_user_id=ids["admin_id"])
    assert csv_type.startswith("text/csv")
    assert csv_name.endswith(".csv")
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
    assert rows[0][0] == "الرقم الأكاديمي"
    csv_pending = next(row for row in rows[1:] if row[1] == "B Student")
    assert csv_pending[5] == ""
    assert csv_pending[8] == ""

    with manager.connection() as conn:
        logs = conn.execute("SELECT ActionType, Details FROM AuditLogs WHERE ActionType='GRADEBOOK_EXPORTED'").fetchall()
    assert len(logs) == 2
    assert all('"approved_scores_only": true' in row["Details"] for row in logs)


def test_overview_metrics_and_empty_exam_are_safe(tmp_path):
    manager, ids = _setup(tmp_path)
    service = ReportingService(manager)
    overview = service.get_overview()
    assert overview["summary"]["Students"] == 2
    assert overview["summary"]["Exams"] == 1
    assert overview["summary"]["FailedAiRuns"] == 1
    with manager.connection() as conn:
        conn.execute("INSERT INTO Exams (Title, SubjectName, TotalMarks) VALUES ('Empty exam', 'Arabic', 10)")
        empty_id = int(conn.execute("SELECT ExamId FROM Exams WHERE Title='Empty exam'").fetchone()[0])
    empty = service.get_exam_analytics(empty_id)
    assert empty["summary"]["enrolled_students"] == 0
    assert empty["summary"]["average_final_score"] is None
    assert empty["summary"]["pass_rate_percent"] is None
    assert empty["hardest_questions"] == []


def test_report_validation_and_missing_records(tmp_path):
    manager, ids = _setup(tmp_path)
    service = ReportingService(manager)
    try:
        service.get_exam_analytics(99999)
    except ReportNotFoundError:
        pass
    else:
        raise AssertionError("missing exam should raise ReportNotFoundError")
    try:
        service.get_exam_analytics(ids["exam_id"], pass_threshold_percent=101)
    except Exception as exc:
        assert "between 0 and 100" in str(exc)
    else:
        raise AssertionError("invalid threshold should be rejected")
    try:
        service.export_gradebook(ids["exam_id"], export_format="pdf", actor_user_id=ids["admin_id"])
    except Exception as exc:
        assert "csv" in str(exc)
    else:
        raise AssertionError("unsupported export format should be rejected")


def test_reports_api_requires_auth_and_returns_analytics(tmp_path):
    from backend.app.core.security import install_api_auth_middleware

    manager, ids = _setup(tmp_path)
    api = FastAPI()
    api.state.db_manager = manager
    api.state.auth_secret = SECRET
    install_api_auth_middleware(api)
    api.include_router(reports_router, prefix="/api/v1")
    token = create_access_token(ids["admin_id"], SECRET)
    teacher_token = create_access_token(ids["teacher_id"], SECRET)
    with TestClient(api) as client:
        denied = client.get(f"/api/v1/reports/exams/{ids['exam_id']}/analytics")
        assert denied.status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get(f"/api/v1/reports/exams/{ids['exam_id']}/analytics", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["summary"]["final_results_count"] == 1
        export = client.get(f"/api/v1/reports/exams/{ids['exam_id']}/export?format=xlsx", headers=headers)
        assert export.status_code == 200
        assert export.headers["content-disposition"].endswith('.xlsx"')
        teacher_headers = {"Authorization": f"Bearer {teacher_token}"}
        own_report = client.get(f"/api/v1/reports/teachers/{ids['teacher_id']}", headers=teacher_headers)
        assert own_report.status_code == 200
        other_report = client.get(f"/api/v1/reports/teachers/{ids['teacher_id'] + 1}", headers=teacher_headers)
        assert other_report.status_code == 403


def test_exports_neutralize_spreadsheet_formula_injection(tmp_path):
    manager, ids = _setup(tmp_path)
    with manager.connection() as conn:
        conn.execute("UPDATE Students SET FullName='=HYPERLINK(\\\"https://example.invalid\\\",\\\"open\\\")' WHERE StudentId=?", (ids["student_a"],))
        conn.execute("UPDATE Exams SET SubjectName='=1+1' WHERE ExamId=?", (ids["exam_id"],))
        conn.execute("UPDATE Questions SET QuestionText='@SUM(A1:A2)' WHERE QuestionId=?", (ids["question_ids"][0],))
    service = ReportingService(manager)
    csv_bytes, _, _ = service.export_gradebook(ids["exam_id"], export_format="csv", actor_user_id=ids["admin_id"])
    csv_rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
    assert next(row for row in csv_rows[1:] if row[0] == "ST-001")[1].startswith("'=")

    xlsx_bytes, _, _ = service.export_gradebook(ids["exam_id"], export_format="xlsx", actor_user_id=ids["admin_id"])
    workbook = load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
    gradebook = workbook["كشف الدرجات"]
    student_row = next(row for row in range(7, 9) if gradebook.cell(row, 1).value == "ST-001")
    assert gradebook.cell(student_row, 2).value.startswith("'=")
    assert gradebook.cell(student_row, 2).data_type != "f"
    assert workbook["ملخص"]["B3"].value.startswith("'")
    assert workbook["تحليل الأسئلة"]["C2"].value.startswith("'")



def test_teacher_activity_report_aggregates_created_exam_and_review_work(tmp_path):
    manager, ids = _setup(tmp_path)
    report = ReportingService(manager).get_teacher_report(ids["teacher_id"])
    assert report["teacher"]["RoleName"] == "Teacher"
    assert report["summary"]["created_exams"] == 1
    assert report["summary"]["total_enrollments"] == 2
    assert report["summary"]["answer_sheets"] == 2
    assert report["summary"]["pending_grading_reviews"] == 1
    assert report["summary"]["finalized_student_results"] == 1
    assert report["summary"]["average_final_percent"] == 50.0
    assert report["activity_by_type"][0]["ActionType"] == "EXAM_CREATED"
