from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.api.endpoints.academic import router as academic_router
from backend.app.api.endpoints.uploads import router as uploads_router
from backend.app.database.database_manager import DatabaseManager


def _make_api(tmp_path: Path):
    schema_source = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
    schema_dir = tmp_path / "backend" / "app" / "database"
    schema_dir.mkdir(parents=True)
    shutil.copy2(schema_source, schema_dir / "schema.sql")

    manager = DatabaseManager(base_dir=tmp_path)
    manager.initialize_database()

    original = tmp_path / "storage" / "original_images" / "page.png"
    processed = tmp_path / "storage" / "processed_images" / "page_processed.png"
    original.parent.mkdir(parents=True, exist_ok=True)
    processed.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (240, 120), "white").save(original)
    Image.new("RGB", (240, 120), "gray").save(processed)

    with manager.connection() as conn:
        student_id = conn.execute(
            "INSERT INTO Students(AcademicId, FullName) VALUES ('INT-1', 'Integration Student')"
        ).lastrowid
        exam_id = conn.execute(
            "INSERT INTO Exams(Title, SubjectName, TotalMarks) VALUES ('Integration Exam', 'Arabic', 10)"
        ).lastrowid
        exam_student_id = conn.execute(
            "INSERT INTO ExamStudents(ExamId, StudentId) VALUES (?, ?)",
            (exam_id, student_id),
        ).lastrowid
        sheet_id = conn.execute(
            "INSERT INTO AnswerSheets(ExamStudentId) VALUES (?)",
            (exam_student_id,),
        ).lastrowid
        page_id = conn.execute(
            """
            INSERT INTO AnswerPages(
                AnswerSheetId, PageNumber, OriginalImagePath, PreprocessedImagePath,
                ImageQualityStatus, ImageWidth, ImageHeight
            ) VALUES (?, 1, ?, ?, 'VALID', 240, 120)
            """,
            (
                sheet_id,
                original.relative_to(tmp_path).as_posix(),
                processed.relative_to(tmp_path).as_posix(),
            ),
        ).lastrowid

    app = FastAPI()
    app.state.db_manager = manager

    @app.middleware("http")
    async def fake_authenticated_user(request, call_next):
        request.state.current_user = {
            "UserId": 1,
            "Username": "integration",
            "FullName": "Integration User",
            "RoleName": "Teacher",
            "IsActive": 1,
        }
        return await call_next(request)

    app.include_router(academic_router, prefix="/api/v1")
    app.include_router(uploads_router, prefix="/api/v1")
    return TestClient(app), manager, sheet_id, page_id, original.read_bytes()


def test_answer_sheet_pages_and_protected_image_are_available_to_frontend():
    temp_root = Path(tempfile.mkdtemp(prefix="madar_frontend_api_"))
    try:
        client, _, sheet_id, page_id, expected_bytes = _make_api(temp_root)
        headers = {"Authorization": "Bearer integration-test-token"}

        pages = client.get(
            f"/api/v1/academic/answer-sheets/{sheet_id}/pages",
            headers=headers,
        )
        assert pages.status_code == 200, pages.text
        payload = pages.json()
        assert payload["answer_sheet_id"] == sheet_id
        assert payload["total"] == 1
        assert payload["items"][0]["PageId"] == page_id
        assert payload["items"][0]["HasOriginalImage"] == 1
        assert "OriginalImagePath" not in payload["items"][0]

        image = client.get(
            f"/api/v1/uploads/pages/{page_id}/image?variant=original",
            headers=headers,
        )
        assert image.status_code == 200, image.text
        assert image.content == expected_bytes
        assert image.headers["content-type"].startswith("image/png")
        assert image.headers["x-content-type-options"] == "nosniff"

        processed = client.get(
            f"/api/v1/uploads/pages/{page_id}/image?variant=processed",
            headers=headers,
        )
        assert processed.status_code == 200, processed.text
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_answer_page_image_endpoint_rejects_paths_outside_storage():
    temp_root = Path(tempfile.mkdtemp(prefix="madar_frontend_path_guard_"))
    try:
        client, manager, _, page_id, _ = _make_api(temp_root)
        outside = temp_root / "outside.png"
        Image.new("RGB", (10, 10), "black").save(outside)
        with manager.connection() as conn:
            conn.execute(
                "UPDATE AnswerPages SET OriginalImagePath=? WHERE PageId=?",
                ("../outside.png", page_id),
            )
        response = client.get(
            f"/api/v1/uploads/pages/{page_id}/image",
            headers={"Authorization": "Bearer integration-test-token"},
        )
        assert response.status_code == 403
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
