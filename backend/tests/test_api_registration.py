from __future__ import annotations

import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.app.api.endpoints.ai import router as ai_router
from backend.app.api.endpoints.answers import router as answers_router
from backend.app.api.endpoints.grading import router as grading_router
from backend.app.api.endpoints.uploads import router as uploads_router
from backend.app.database.database_manager import DatabaseManager
from backend.app.main import app as production_app


class FakeHTREngine:
    MODEL_NAME = "fake-api-htr"
    model_version = "fake-v1"

    def recognize_page(self, source, paper=True):
        return {
            "text": "اختبار",
            "lines": [{
                "line_number": 1, "text": "اختبار", "confidence": 0.9,
                "confidence_percent": 90, "needs_review": False,
                "box": [0, 0, 100, 30], "angle_degrees": 0,
                "alternatives": [],
            }],
            "line_count": 1, "confidence": 0.9, "confidence_percent": 90,
            "needs_review": False, "status": "SUCCEEDED",
            "segmentation_method": "fake", "model_name": self.MODEL_NAME,
            "model_version": self.model_version,
        }


def test_phase_3_and_4_routes_are_registered():
    paths = set(production_app.openapi()["paths"])
    assert "/api/v1/ai/pages/{page_id}/recognize" in paths
    assert "/api/v1/ai/answers/{answer_id}/recognize" in paths
    assert "/api/v1/grading/answers/{answer_id}/evaluate" in paths
    assert "/api/v1/answers/{answer_id}/regions" in paths
    assert "/api/v1/auth/bootstrap-admin" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/academic/students" in paths
    assert "/api/v1/academic/exams" in paths
    assert "/api/v1/academic/exams/{exam_id}/results" in paths
    assert "/api/v1/academic/answer-sheets/{answer_sheet_id}/pages" in paths
    assert "/api/v1/uploads/pages/{page_id}/image" in paths


def test_ai_and_grading_api_endpoints_work_with_local_test_database():
    temp_root = Path(tempfile.mkdtemp(prefix="madar_api_test_"))
    try:
        db_dir = temp_root / "backend" / "app" / "database"
        db_dir.mkdir(parents=True)
        schema = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
        shutil.copy2(schema, db_dir / "schema.sql")
        manager = DatabaseManager(base_dir=temp_root)
        manager.initialize_database()
        image_path = temp_root / "storage" / "original_images" / "page.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (400, 300), "white").save(image_path)
        relative_image = image_path.relative_to(temp_root).as_posix()

        with manager.connection() as conn:
            student_id = conn.execute(
                "INSERT INTO Students(AcademicId, FullName) VALUES ('API-1', 'API Student')"
            ).lastrowid
            exam_id = conn.execute(
                "INSERT INTO Exams(Title, SubjectName, TotalMarks) VALUES ('API Exam', 'Arabic', 5)"
            ).lastrowid
            exam_student_id = conn.execute(
                "INSERT INTO ExamStudents(ExamId, StudentId) VALUES (?, ?)", (exam_id, student_id)
            ).lastrowid
            sheet_id = conn.execute(
                "INSERT INTO AnswerSheets(ExamStudentId) VALUES (?)", (exam_student_id,)
            ).lastrowid
            page_id = conn.execute(
                "INSERT INTO AnswerPages(AnswerSheetId, PageNumber, OriginalImagePath) VALUES (?, 1, ?)",
                (sheet_id, relative_image),
            ).lastrowid
            question_id = conn.execute(
                "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, ModelAnswer, MaxMarks) VALUES (?, 1, 'MULTIPLE_CHOICE', 'Choose', NULL, 5)",
                (exam_id,),
            ).lastrowid
            correct_id = conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'A', 'Yes', 1, 1)",
                (question_id,),
            ).lastrowid
            conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'B', 'No', 0, 2)",
                (question_id,),
            )
            answer_id = conn.execute(
                "INSERT INTO QuestionAnswers(AnswerSheetId, QuestionId, SelectedChoiceId) VALUES (?, ?, ?)",
                (sheet_id, question_id, correct_id),
            ).lastrowid

        api = FastAPI()
        api.state.db_manager = manager
        api.state.htr_engine = FakeHTREngine()
        api.include_router(ai_router, prefix="/api/v1")
        api.include_router(grading_router, prefix="/api/v1")
        api.include_router(answers_router, prefix="/api/v1")
        client = TestClient(api)

        region_response = client.post(
            f"/api/v1/answers/{answer_id}/regions",
            json={"page_id": page_id, "segment_order": 1, "region_x": 0.1, "region_y": 0.1, "region_width": 0.8, "region_height": 0.5},
        )
        assert region_response.status_code == 201, region_response.text
        listed_regions = client.get(f"/api/v1/answers/{answer_id}/regions")
        assert listed_regions.status_code == 200
        assert listed_regions.json()["count"] == 1

        htr_response = client.post(f"/api/v1/ai/answers/{answer_id}/recognize")
        assert htr_response.status_code == 200, htr_response.text
        assert htr_response.json()["text"] == "اختبار"

        grading_response = client.post(f"/api/v1/grading/answers/{answer_id}/evaluate")
        assert grading_response.status_code == 200, grading_response.text
        assert grading_response.json()["suggested_score"] == 5
        assert grading_response.json()["final_approval"] == "NOT_APPROVED"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_upload_api_records_image_processing_run_and_cleans_duplicate_files():
    temp_root = Path(tempfile.mkdtemp(prefix="madar_upload_api_test_"))
    try:
        db_dir = temp_root / "backend" / "app" / "database"
        db_dir.mkdir(parents=True)
        schema = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
        shutil.copy2(schema, db_dir / "schema.sql")
        manager = DatabaseManager(base_dir=temp_root)
        manager.initialize_database()
        with manager.connection() as conn:
            student_id = conn.execute(
                "INSERT INTO Students(AcademicId, FullName) VALUES ('UP-1', 'Upload Student')"
            ).lastrowid
            exam_id = conn.execute(
                "INSERT INTO Exams(Title, SubjectName, TotalMarks) VALUES ('Upload Exam', 'Arabic', 5)"
            ).lastrowid
            exam_student_id = conn.execute(
                "INSERT INTO ExamStudents(ExamId, StudentId) VALUES (?, ?)", (exam_id, student_id)
            ).lastrowid
            question_id = conn.execute(
                "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, MaxMarks) VALUES (?, 1, 'MULTIPLE_CHOICE', 'Choose', 5)",
                (exam_id,),
            ).lastrowid
            conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'A', 'Yes', 1, 1)",
                (question_id,),
            )
            conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'B', 'No', 0, 2)",
                (question_id,),
            )

        page = Image.new("RGB", (1200, 1200), "white")
        draw = ImageDraw.Draw(page)
        draw.line((80, 200, 1100, 200), fill="black", width=8)
        draw.line((80, 400, 1100, 400), fill="black", width=8)
        payload = BytesIO()
        page.save(payload, format="PNG")
        image_bytes = payload.getvalue()

        api = FastAPI()
        api.state.db_manager = manager
        api.include_router(uploads_router, prefix="/api/v1")
        client = TestClient(api)

        response = client.post(
            "/api/v1/uploads/answer-page",
            data={"exam_student_id": str(exam_student_id), "page_number": "1"},
            files={"file": ("answer.png", image_bytes, "image/png")},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["processing_run_id"] > 0
        assert result["page_id"] > 0

        with manager.connection() as conn:
            run = conn.execute(
                "SELECT Stage, Status, PageId, OutputJson, StartedAt, CompletedAt, DurationMs FROM AIProcessingRuns WHERE ProcessingRunId=?",
                (result["processing_run_id"],),
            ).fetchone()
            page_row = conn.execute(
                "SELECT OriginalImagePath, PreprocessedImagePath FROM AnswerPages WHERE PageId=?",
                (result["page_id"],),
            ).fetchone()
        assert run["Stage"] == "IMAGE_PROCESSING"
        assert run["Status"] in {"SUCCEEDED", "REQUIRES_REVIEW"}
        assert run["PageId"] == result["page_id"]
        assert run["OutputJson"]
        assert run["StartedAt"] and run["CompletedAt"]
        assert run["DurationMs"] >= 0
        with manager.connection() as conn:
            initialized_answers = conn.execute(
                "SELECT COUNT(*) FROM QuestionAnswers WHERE AnswerSheetId=?", (result["answer_sheet_id"],)
            ).fetchone()[0]
        assert initialized_answers == 1
        assert (temp_root / page_row["OriginalImagePath"]).is_file()
        assert (temp_root / page_row["PreprocessedImagePath"]).is_file()

        duplicate = client.post(
            "/api/v1/uploads/answer-page",
            data={"exam_student_id": str(exam_student_id), "page_number": "1"},
            files={"file": ("answer.png", image_bytes, "image/png")},
        )
        assert duplicate.status_code == 409
        assert len(list((temp_root / "storage" / "original_images").glob("*"))) == 1
        assert len(list((temp_root / "storage" / "processed_images").glob("*"))) == 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
