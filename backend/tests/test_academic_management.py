from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.endpoints.academic import router as academic_router
from backend.app.api.endpoints.ai import router as ai_router
from backend.app.api.endpoints.answers import router as answers_router
from backend.app.api.endpoints.auth import router as auth_router
from backend.app.api.endpoints.grading import router as grading_router
from backend.app.api.endpoints.reports import router as reports_router
from backend.app.api.endpoints.uploads import router as uploads_router
from backend.app.core.security import install_api_auth_middleware
from backend.app.database.database_manager import DatabaseManager


def _test_app():
    temp_root = Path(tempfile.mkdtemp(prefix="madar_phase5_"))
    db_dir = temp_root / "backend" / "app" / "database"
    db_dir.mkdir(parents=True)
    schema = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
    shutil.copy2(schema, db_dir / "schema.sql")
    manager = DatabaseManager(base_dir=temp_root)
    manager.initialize_database()
    api = FastAPI()
    api.state.db_manager = manager
    api.state.auth_secret = b"test-signing-secret-for-madar-phase5"
    install_api_auth_middleware(api)
    api.include_router(auth_router, prefix="/api/v1")
    api.include_router(academic_router, prefix="/api/v1")
    api.include_router(uploads_router, prefix="/api/v1")
    api.include_router(ai_router, prefix="/api/v1")
    api.include_router(grading_router, prefix="/api/v1")
    api.include_router(reports_router, prefix="/api/v1")
    api.include_router(answers_router, prefix="/api/v1")
    return temp_root, manager, api


def _bootstrap(client: TestClient) -> tuple[str, int]:
    response = client.post("/api/v1/auth/bootstrap-admin", json={
        "username": "rootadmin",
        "full_name": "System Administrator",
        "password": "StrongAdminPassword#2026",
    })
    assert response.status_code == 201, response.text
    data = response.json()
    return data["access_token"], data["user"]["user_id"]


def _create_teacher(client: TestClient, admin_token: str) -> tuple[str, int]:
    headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post("/api/v1/auth/users", headers=headers, json={
        "username": "teacher1",
        "full_name": "Arabic Teacher",
        "password": "StrongTeacherPassword#2026",
        "role_name": "Teacher",
    })
    assert created.status_code == 201, created.text
    login = client.post("/api/v1/auth/login", json={
        "username": "teacher1", "password": "StrongTeacherPassword#2026"
    })
    assert login.status_code == 200, login.text
    return login.json()["access_token"], created.json()["user_id"]


def test_auth_bootstrap_login_role_enforcement_and_token_validation():
    root, manager, api = _test_app()
    try:
        with TestClient(api) as client:
            denied = client.get("/api/v1/academic/students")
            assert denied.status_code == 401
            denied_ai = client.post("/api/v1/ai/pages/1/recognize")
            assert denied_ai.status_code == 401
            denied_upload = client.post("/api/v1/uploads/answer-page")
            assert denied_upload.status_code == 401
            denied_grading = client.post("/api/v1/grading/answers/1/evaluate")
            assert denied_grading.status_code == 401

            admin_token, admin_id = _bootstrap(client)
            second_bootstrap = client.post("/api/v1/auth/bootstrap-admin", json={
                "username": "otheradmin", "full_name": "Other Admin", "password": "AnotherStrongPassword#2026"
            })
            assert second_bootstrap.status_code == 409

            me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
            assert me.status_code == 200
            assert me.json()["role_name"] == "Admin"

            teacher_token, teacher_id = _create_teacher(client, admin_token)
            assert teacher_id > 0

            admin_cannot_adjust = client.patch(
                "/api/v1/academic/answers/1/grade",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"adjusted_score": 1, "teacher_justification": "Manual review"},
            )
            assert admin_cannot_adjust.status_code == 403

            teacher_cannot_create_users = client.post(
                "/api/v1/auth/users",
                headers={"Authorization": f"Bearer {teacher_token}"},
                json={"username": "reviewer1", "full_name": "Reviewer", "password": "StrongReviewerPassword#2026", "role_name": "Reviewer"},
            )
            assert teacher_cannot_create_users.status_code == 403

            reviewer_created = client.post(
                "/api/v1/auth/users",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"username": "reviewer1", "full_name": "Read Only Reviewer", "password": "StrongReviewerPassword#2026", "role_name": "Reviewer"},
            )
            assert reviewer_created.status_code == 201, reviewer_created.text
            reviewer_login = client.post("/api/v1/auth/login", json={"username": "reviewer1", "password": "StrongReviewerPassword#2026"})
            reviewer_token = reviewer_login.json()["access_token"]
            reviewer_headers = {"Authorization": f"Bearer {reviewer_token}"}
            assert client.get("/api/v1/academic/students", headers=reviewer_headers).status_code == 200
            assert client.post("/api/v1/grading/answers/1/evaluate", headers=reviewer_headers).status_code == 403
            assert client.post("/api/v1/ai/pages/1/recognize", headers=reviewer_headers).status_code == 403

            tampered = client.get("/api/v1/academic/students", headers={"Authorization": f"Bearer {admin_token}x"})
            assert tampered.status_code == 401

            with manager.connection() as conn:
                rows = conn.execute("SELECT UserId, RoleName FROM Users ORDER BY UserId").fetchall()
            assert [(row["UserId"], row["RoleName"]) for row in rows] == [(admin_id, "Admin"), (teacher_id, "Teacher"), (reviewer_created.json()["user_id"], "Reviewer")]
    finally:
        shutil.rmtree(root, ignore_errors=True)



def test_bootstrap_admin_preserves_legacy_non_admin_accounts():
    root, manager, api = _test_app()
    try:
        with manager.connection() as conn:
            conn.execute(
                "INSERT INTO Users (Username, FullName, PasswordHash, RoleName) VALUES ('demo_teacher', 'Legacy Demo Teacher', 'legacy-placeholder-hash', 'Teacher')"
            )
        with TestClient(api) as client:
            admin_token, admin_id = _bootstrap(client)
            assert admin_id > 1
            with manager.connection() as conn:
                users = conn.execute("SELECT Username, RoleName FROM Users ORDER BY UserId").fetchall()
            assert [(row["Username"], row["RoleName"]) for row in users] == [
                ("demo_teacher", "Teacher"),
                ("rootadmin", "Admin"),
            ]
            me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
            assert me.status_code == 200
    finally:
        shutil.rmtree(root, ignore_errors=True)

def test_academic_lifecycle_question_configuration_answer_sheet_and_gradebook():
    root, manager, api = _test_app()
    try:
        with TestClient(api) as client:
            admin_token, admin_id = _bootstrap(client)
            teacher_token, teacher_id = _create_teacher(client, admin_token)
            admin_headers = {"Authorization": f"Bearer {admin_token}"}
            teacher_headers = {"Authorization": f"Bearer {teacher_token}"}

            student = client.post("/api/v1/academic/students", headers=teacher_headers, json={
                "academic_id": "ST-0001", "full_name": "طالب تجريبي"
            })
            assert student.status_code == 201, student.text
            student_id = student.json()["StudentId"]

            duplicate_student = client.post("/api/v1/academic/students", headers=teacher_headers, json={
                "academic_id": "ST-0001", "full_name": "طالب مكرر"
            })
            assert duplicate_student.status_code == 409

            exam = client.post("/api/v1/academic/exams", headers=teacher_headers, json={
                "title": "اختبار تجريبي", "subject_name": "اللغة العربية", "exam_date": "2026-11-27", "total_marks": 20
            })
            assert exam.status_code == 201, exam.text
            exam_id = exam.json()["ExamId"]

            mcq = client.post(f"/api/v1/academic/exams/{exam_id}/questions", headers=teacher_headers, json={
                "question_number": 1, "question_type": "MULTIPLE_CHOICE", "question_text": "اختر الإجابة الصحيحة", "max_marks": 5,
                "choices": [
                    {"choice_label": "A", "choice_text": "الإجابة الصحيحة", "is_correct": True},
                    {"choice_label": "B", "choice_text": "إجابة خاطئة", "is_correct": False},
                ],
            })
            assert mcq.status_code == 201, mcq.text
            mcq_id = mcq.json()["QuestionId"]
            correct_choice_id = next(item["ChoiceId"] for item in mcq.json()["choices"] if item["IsCorrect"])

            fill = client.post(f"/api/v1/academic/exams/{exam_id}/questions", headers=teacher_headers, json={
                "question_number": 2, "question_type": "FILL_BLANK", "question_text": "أكمل: الخلية هي ____ الحياة", "max_marks": 5,
                "accepted_answers": [{"answer_text": "وحدة", "normalize_arabic": True}],
            })
            assert fill.status_code == 201, fill.text

            essay = client.post(f"/api/v1/academic/exams/{exam_id}/questions", headers=teacher_headers, json={
                "question_number": 3, "question_type": "ESSAY", "question_text": "اشرح مفهوم الخلية", "model_answer": "الخلية هي الوحدة الأساسية للحياة", "max_marks": 10,
                "rubric_criteria": [{"criterion_title": "التعريف", "criterion_description": "الخلية هي الوحدة الأساسية للحياة", "allocated_marks": 10}],
            })
            assert essay.status_code == 201, essay.text

            invalid_question = client.post(f"/api/v1/academic/exams/{exam_id}/questions", headers=teacher_headers, json={
                "question_number": 4, "question_type": "MULTIPLE_CHOICE", "question_text": "سؤال خاطئ", "max_marks": 2,
                "choices": [{"choice_label": "A", "choice_text": "واحد", "is_correct": True}],
            })
            assert invalid_question.status_code == 422

            overallocated_exam = client.patch(f"/api/v1/academic/exams/{exam_id}", headers=teacher_headers, json={"total_marks": 19})
            assert overallocated_exam.status_code == 409

            enrollment = client.post(f"/api/v1/academic/exams/{exam_id}/enrollments", headers=teacher_headers, json={"student_ids": [student_id]})
            assert enrollment.status_code == 200, enrollment.text
            exam_student_id = client.get(f"/api/v1/academic/exams/{exam_id}/enrollments", headers=teacher_headers).json()[0]["ExamStudentId"]

            sheet = client.post(f"/api/v1/academic/exams/{exam_id}/answer-sheets", headers=teacher_headers, json={"exam_student_id": exam_student_id})
            assert sheet.status_code == 201, sheet.text
            sheet_id = sheet.json()["AnswerSheetId"]
            assert sheet.json()["answer_count"] == 3

            duplicate_sheet = client.post(f"/api/v1/academic/exams/{exam_id}/answer-sheets", headers=teacher_headers, json={"exam_student_id": exam_student_id})
            assert duplicate_sheet.status_code == 409

            answers = client.get(f"/api/v1/academic/answer-sheets/{sheet_id}/answers", headers=teacher_headers)
            assert answers.status_code == 200
            answer_by_question = {row["QuestionNumber"]: row["AnswerId"] for row in answers.json()}
            answer1, answer2, answer3 = answer_by_question[1], answer_by_question[2], answer_by_question[3]

            update1 = client.patch(f"/api/v1/academic/answers/{answer1}/response", headers=teacher_headers, json={"selected_choice_id": correct_choice_id})
            assert update1.status_code == 200, update1.text
            mark_empty = client.patch(f"/api/v1/academic/answers/{answer2}/response", headers=teacher_headers, json={"is_empty_answer": True})
            assert mark_empty.status_code == 200, mark_empty.text
            update2 = client.patch(f"/api/v1/academic/answers/{answer2}/response", headers=teacher_headers, json={"edited_text": "وحدة"})
            assert update2.status_code == 200, update2.text
            assert update2.json()["is_empty_answer"] is False
            update3 = client.patch(f"/api/v1/academic/answers/{answer3}/response", headers=teacher_headers, json={"edited_text": "الخلية هي الوحدة الأساسية للحياة"})
            assert update3.status_code == 200, update3.text

            for answer_id in (answer1, answer2, answer3):
                evaluated = client.post(f"/api/v1/grading/answers/{answer_id}/evaluate", headers=teacher_headers)
                assert evaluated.status_code == 200, evaluated.text
            essay_eval = client.post(f"/api/v1/grading/answers/{answer3}/evaluate", headers=teacher_headers)
            assert essay_eval.status_code == 200
            # Essay baseline is deliberately not a final semantic grade and requires teacher review.
            assert essay_eval.json()["needs_grading_review"] is True

            adjusted = client.patch(f"/api/v1/academic/answers/{answer3}/grade", headers=teacher_headers, json={
                "adjusted_score": 8, "teacher_justification": "تمت مراجعة الإجابة يدوياً", "teacher_notes": "مراجعة معيار التعريف"
            })
            assert adjusted.status_code == 200, adjusted.text

            teacher_cannot_approve = client.post(f"/api/v1/academic/answers/{answer1}/approve", headers=teacher_headers, json={"approval_note": "موافقة"})
            assert teacher_cannot_approve.status_code == 403

            for answer_id in (answer1, answer2, answer3):
                approved = client.post(f"/api/v1/academic/answers/{answer_id}/approve", headers=admin_headers, json={"approval_note": "تمت مراجعة الدرجة واعتمادها"})
                assert approved.status_code == 200, approved.text

            final_sheet = client.get(f"/api/v1/academic/answer-sheets/{sheet_id}", headers=admin_headers)
            assert final_sheet.status_code == 200
            assert final_sheet.json()["ProcessingStatus"] == "FINALLY_APPROVED"

            results = client.get(f"/api/v1/academic/exams/{exam_id}/results", headers=admin_headers)
            assert results.status_code == 200, results.text
            item = results.json()["items"][0]
            assert item["final_score"] == 18.0
            assert item["approved_count"] == 3
            assert item["result_status"] == "FINAL"

            delete_enrolled_student = client.delete(f"/api/v1/academic/students/{student_id}", headers=admin_headers)
            assert delete_enrolled_student.status_code == 409
            delete_exam_with_enrollment = client.delete(f"/api/v1/academic/exams/{exam_id}", headers=admin_headers)
            assert delete_exam_with_enrollment.status_code == 409

            with manager.connection() as conn:
                audit_count = int(conn.execute("SELECT COUNT(*) FROM AuditLogs").fetchone()[0])
                fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            assert audit_count >= 12
            assert not fk_errors
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_question_created_after_answer_sheet_backfills_answer_row():
    root, manager, api = _test_app()
    try:
        with TestClient(api) as client:
            admin_token, _ = _bootstrap(client)
            teacher_token, _ = _create_teacher(client, admin_token)
            headers = {"Authorization": f"Bearer {teacher_token}"}
            student = client.post("/api/v1/academic/students", headers=headers, json={"academic_id": "LATE-1", "full_name": "Late Question Student"})
            exam = client.post("/api/v1/academic/exams", headers=headers, json={"title": "Late Exam", "subject_name": "Science", "total_marks": 10})
            exam_id = exam.json()["ExamId"]
            enrollment = client.post(f"/api/v1/academic/exams/{exam_id}/enrollments", headers=headers, json={"student_ids": [student.json()["StudentId"]]})
            exam_student_id = client.get(f"/api/v1/academic/exams/{exam_id}/enrollments", headers=headers).json()[0]["ExamStudentId"]
            sheet = client.post(f"/api/v1/academic/exams/{exam_id}/answer-sheets", headers=headers, json={"exam_student_id": exam_student_id})
            assert sheet.status_code == 201
            assert sheet.json()["answer_count"] == 0

            question = client.post(f"/api/v1/academic/exams/{exam_id}/questions", headers=headers, json={
                "question_number": 1, "question_type": "MULTIPLE_CHOICE", "question_text": "One?", "max_marks": 10,
                "choices": [{"choice_label": "A", "choice_text": "Yes", "is_correct": True}, {"choice_label": "B", "choice_text": "No", "is_correct": False}],
            })
            assert question.status_code == 201, question.text
            answers = client.get(f"/api/v1/academic/answer-sheets/{sheet.json()['AnswerSheetId']}/answers", headers=headers)
            assert answers.status_code == 200
            assert len(answers.json()) == 1
            assert answers.json()[0]["QuestionId"] == question.json()["QuestionId"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
