from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.app.database.database_manager import DatabaseManager
from backend.app.services.htr_service import HTRConflictError, HTRInputError, HTRService


class FakeHTREngine:
    MODEL_NAME = "fake-arabic-htr"
    model_version = "fake-v1"

    def recognize_page(self, source, paper=True):
        return {
            "text": "السلام عليكم",
            "lines": [{
                "line_number": 1,
                "text": "السلام عليكم",
                "confidence": 0.91,
                "confidence_percent": 91.0,
                "needs_review": False,
                "box": [0, 0, 200, 50],
                "angle_degrees": 0.0,
                "alternatives": [],
            }],
            "line_count": 1,
            "confidence": 0.91,
            "confidence_percent": 91.0,
            "needs_review": False,
            "status": "SUCCEEDED",
            "segmentation_method": "fake",
            "model_name": self.MODEL_NAME,
            "model_version": self.model_version,
        }


class HTRServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(tempfile.mkdtemp(prefix="madar_htr_service_"))
        db_dir = self.temp_root / "backend" / "app" / "database"
        db_dir.mkdir(parents=True)
        source_schema = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
        shutil.copy2(source_schema, db_dir / "schema.sql")
        self.manager = DatabaseManager(base_dir=self.temp_root)
        self.manager.initialize_database()
        self.image_path = self.temp_root / "storage" / "original_images" / "sample.png"
        self.image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (500, 300), "white").save(self.image_path)
        self.relative_image = self.image_path.relative_to(self.temp_root).as_posix()
        with self.manager.connection() as conn:
            cur = conn.execute(
                "INSERT INTO Students(AcademicId, FullName) VALUES ('S-1', 'Student One')"
            )
            student_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO Exams(Title, SubjectName, TotalMarks) VALUES ('Test', 'Arabic', 10)"
            )
            exam_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO ExamStudents(ExamId, StudentId) VALUES (?, ?)",
                (exam_id, student_id),
            )
            exam_student_id = cur.lastrowid
            cur = conn.execute("INSERT INTO AnswerSheets(ExamStudentId) VALUES (?)", (exam_student_id,))
            self.sheet_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO AnswerPages(AnswerSheetId, PageNumber, OriginalImagePath, ImageQualityStatus) VALUES (?, 1, ?, 'VALID')",
                (self.sheet_id, self.relative_image),
            )
            self.page_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, ModelAnswer, MaxMarks) VALUES (?, 1, 'ESSAY', 'Question', 'Model answer', 10)",
                (exam_id,),
            )
            self.question_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO QuestionAnswers(AnswerSheetId, QuestionId) VALUES (?, ?)",
                (self.sheet_id, self.question_id),
            )
            self.answer_id = cur.lastrowid
            conn.execute(
                "INSERT INTO QuestionAnswerPages(AnswerId, PageId, SegmentOrder, RegionX, RegionY, RegionWidth, RegionHeight) VALUES (?, ?, 1, 0.1, 0.1, 0.8, 0.5)",
                (self.answer_id, self.page_id),
            )
        self.service = HTRService(self.manager, engine=FakeHTREngine())

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_recognize_page_persists_htr_run(self):
        result = self.service.recognize_page(self.page_id)
        self.assertEqual(result["text"], "السلام عليكم")
        with self.manager.connection() as conn:
            row = conn.execute(
                "SELECT Stage, Status, PageId, AnswerId, OutputJson FROM AIProcessingRuns WHERE ProcessingRunId=?",
                (result["processing_run_id"],),
            ).fetchone()
        self.assertEqual(row["Stage"], "HTR")
        self.assertEqual(row["Status"], "SUCCEEDED")
        self.assertEqual(row["PageId"], self.page_id)
        self.assertIsNone(row["AnswerId"])
        self.assertIn("السلام عليكم", row["OutputJson"])

    def test_recognize_answer_crops_region_and_persists_extracted_text(self):
        result = self.service.recognize_answer(self.answer_id)
        self.assertEqual(result["text"], "السلام عليكم")
        self.assertEqual(result["pages_processed"], 1)
        self.assertEqual(result["answer_sheet_status"], "PROCESSED")
        with self.manager.connection() as conn:
            answer = conn.execute(
                "SELECT ExtractedText, OcrConfidence, NeedsOcrReview, IsEmptyAnswer FROM QuestionAnswers WHERE AnswerId=?",
                (self.answer_id,),
            ).fetchone()
            run = conn.execute(
                "SELECT Status, Stage, PageId, AnswerId FROM AIProcessingRuns WHERE AnswerId=?",
                (self.answer_id,),
            ).fetchone()
        self.assertEqual(answer["ExtractedText"], "السلام عليكم")
        self.assertEqual(answer["OcrConfidence"], 91.0)
        self.assertEqual(answer["NeedsOcrReview"], 0)
        self.assertEqual(answer["IsEmptyAnswer"], 0)
        self.assertEqual(run["Status"], "SUCCEEDED")
        self.assertEqual(run["Stage"], "HTR")
        self.assertEqual(run["PageId"], self.page_id)
        self.assertEqual(run["AnswerId"], self.answer_id)

    def test_answer_without_page_mapping_is_rejected(self):
        with self.manager.connection() as conn:
            conn.execute("DELETE FROM QuestionAnswerPages WHERE AnswerId=?", (self.answer_id,))
        with self.assertRaises(HTRConflictError):
            self.service.recognize_answer(self.answer_id)


    def test_multi_page_answer_is_combined_in_page_order(self):
        second_image = self.temp_root / "storage" / "original_images" / "sample_page_2.png"
        Image.new("RGB", (500, 300), "white").save(second_image)
        second_relative = second_image.relative_to(self.temp_root).as_posix()
        with self.manager.connection() as conn:
            page2 = conn.execute(
                "INSERT INTO AnswerPages(AnswerSheetId, PageNumber, OriginalImagePath, ImageQualityStatus) VALUES (?, 2, ?, 'VALID')",
                (self.sheet_id, second_relative),
            ).lastrowid
            conn.execute(
                "INSERT INTO QuestionAnswerPages(AnswerId, PageId, SegmentOrder) VALUES (?, ?, 2)",
                (self.answer_id, page2),
            )
        result = self.service.recognize_answer(self.answer_id)
        self.assertEqual(result["pages_processed"], 2)
        self.assertEqual(result["text"], "السلام عليكم\nالسلام عليكم")
        with self.manager.connection() as conn:
            runs = conn.execute(
                "SELECT PageId, Status FROM AIProcessingRuns WHERE AnswerId=? ORDER BY PageId",
                (self.answer_id,),
            ).fetchall()
        self.assertEqual(len(runs), 2)
        self.assertTrue(all(row["Status"] == "SUCCEEDED" for row in runs))

    def test_failed_inference_is_recorded_as_failed_run(self):
        class FailingEngine(FakeHTREngine):
            def recognize_page(self, source, paper=True):
                raise RuntimeError("simulated inference failure")

        failing = HTRService(self.manager, engine=FailingEngine())
        with self.assertRaises(RuntimeError):
            failing.recognize_page(self.page_id)
        with self.manager.connection() as conn:
            row = conn.execute(
                "SELECT Status, ErrorMessage, StartedAt, CompletedAt, DurationMs FROM AIProcessingRuns WHERE PageId=? ORDER BY ProcessingRunId DESC LIMIT 1",
                (self.page_id,),
            ).fetchone()
        self.assertEqual(row["Status"], "FAILED")
        self.assertIn("simulated inference failure", row["ErrorMessage"])
        self.assertIsNotNone(row["StartedAt"])
        self.assertIsNotNone(row["CompletedAt"])
        self.assertGreaterEqual(row["DurationMs"], 0)

    def test_path_traversal_is_rejected(self):
        with self.manager.connection() as conn:
            conn.execute("UPDATE AnswerPages SET OriginalImagePath='../outside.png' WHERE PageId=?", (self.page_id,))
        with self.assertRaises(HTRInputError):
            self.service.recognize_page(self.page_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
