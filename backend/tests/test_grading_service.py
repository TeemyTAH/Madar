from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from backend.app.database.database_manager import DatabaseManager
from backend.app.services.grading_service import (
    GradingConfigurationError,
    GradingConflictError,
    GradingNotFoundError,
    GradingService,
)


class GradingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(tempfile.mkdtemp(prefix="madar_grading_"))
        db_dir = self.temp_root / "backend" / "app" / "database"
        db_dir.mkdir(parents=True)
        source_schema = Path(__file__).resolve().parents[1] / "app" / "database" / "schema.sql"
        shutil.copy2(source_schema, db_dir / "schema.sql")
        self.manager = DatabaseManager(base_dir=self.temp_root)
        self.manager.initialize_database()
        with self.manager.connection() as conn:
            student_id = conn.execute(
                "INSERT INTO Students(AcademicId, FullName) VALUES ('S-1', 'Student One')"
            ).lastrowid
            exam_id = conn.execute(
                "INSERT INTO Exams(Title, SubjectName, TotalMarks) VALUES ('Test', 'General', 30)"
            ).lastrowid
            exam_student_id = conn.execute(
                "INSERT INTO ExamStudents(ExamId, StudentId) VALUES (?, ?)", (exam_id, student_id)
            ).lastrowid
            self.sheet_id = conn.execute(
                "INSERT INTO AnswerSheets(ExamStudentId) VALUES (?)", (exam_student_id,)
            ).lastrowid
            self.exam_id = exam_id
        self.service = GradingService(self.manager)

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _add_question_answer(self, number, qtype, max_marks, answer_text=None, selected_choice=None, model_answer="Model"):
        with self.manager.connection() as conn:
            question_id = conn.execute(
                "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, ModelAnswer, MaxMarks) VALUES (?, ?, ?, 'Question text', ?, ?)",
                (self.exam_id, number, qtype, model_answer, max_marks),
            ).lastrowid
            answer_id = conn.execute(
                "INSERT INTO QuestionAnswers(AnswerSheetId, QuestionId, SelectedChoiceId, ExtractedText) VALUES (?, ?, ?, ?)",
                (self.sheet_id, question_id, selected_choice, answer_text),
            ).lastrowid
        return question_id, answer_id

    def test_multiple_choice_is_graded_deterministically(self):
        question_id, answer_id = self._add_question_answer(1, "MULTIPLE_CHOICE", 5)
        with self.manager.connection() as conn:
            correct_id = conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'A', 'Correct', 1, 1)",
                (question_id,),
            ).lastrowid
            conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'B', 'Wrong', 0, 2)",
                (question_id,),
            )
            conn.execute("UPDATE QuestionAnswers SET SelectedChoiceId=? WHERE AnswerId=?", (correct_id, answer_id))
        result = self.service.evaluate(answer_id)
        self.assertEqual(result["suggested_score"], 5.0)
        self.assertEqual(result["answer_sheet_status"], "PROCESSED")
        self.assertFalse(result["needs_grading_review"])
        self.assertEqual(result["final_approval"], "NOT_APPROVED")
        with self.manager.connection() as conn:
            row = conn.execute("SELECT SuggestedScore, IsApproved FROM QuestionAnswers WHERE AnswerId=?", (answer_id,)).fetchone()
            run = conn.execute("SELECT Stage, Status FROM AIProcessingRuns WHERE ProcessingRunId=?", (result["processing_run_id"],)).fetchone()
        self.assertEqual(row["SuggestedScore"], 5)
        self.assertEqual(row["IsApproved"], 0)
        self.assertEqual(tuple(run), ("SEMANTIC_EVALUATION", "SUCCEEDED"))

    def test_fill_blank_matches_normalized_arabic_variant(self):
        question_id, answer_id = self._add_question_answer(2, "FILL_BLANK", 3, "إِنسان")
        with self.manager.connection() as conn:
            conn.execute(
                "INSERT INTO AcceptedAnswers(QuestionId, AnswerText, CaseSensitive, NormalizeArabic, SortOrder) VALUES (?, 'انسان', 0, 1, 1)",
                (question_id,),
            )
        result = self.service.evaluate(answer_id)
        self.assertEqual(result["suggested_score"], 3.0)
        self.assertFalse(result["needs_grading_review"])


    def test_unmatched_accepted_text_is_flagged_for_teacher_review(self):
        question_id, answer_id = self._add_question_answer(8, "FILL_BLANK", 3, "صياغة بديلة")
        with self.manager.connection() as conn:
            conn.execute(
                "INSERT INTO AcceptedAnswers(QuestionId, AnswerText, CaseSensitive, NormalizeArabic, SortOrder) VALUES (?, 'الإجابة النموذجية', 0, 1, 1)",
                (question_id,),
            )
        result = self.service.evaluate(answer_id)
        self.assertEqual(result["suggested_score"], 0.0)
        self.assertTrue(result["needs_grading_review"])
        self.assertEqual(result["status"], "REQUIRES_REVIEW")
        with self.manager.connection() as conn:
            row = conn.execute(
                "SELECT NeedsGradingReview, EvaluationConfidence FROM QuestionAnswers WHERE AnswerId=?",
                (answer_id,),
            ).fetchone()
            run = conn.execute(
                "SELECT Status FROM AIProcessingRuns WHERE ProcessingRunId=?",
                (result["processing_run_id"],),
            ).fetchone()
        self.assertEqual(row["NeedsGradingReview"], 1)
        self.assertIsNone(row["EvaluationConfidence"])
        self.assertEqual(run["Status"], "REQUIRES_REVIEW")

    def test_rubric_baseline_produces_only_review_required_suggestion(self):
        question_id, answer_id = self._add_question_answer(
            3, "ESSAY", 10, "الخلية هي الوحدة الاساسية للحياة", model_answer="الخلية وحدة الحياة"
        )
        with self.manager.connection() as conn:
            criterion_id = conn.execute(
                "INSERT INTO RubricCriteria(QuestionId, CriterionTitle, CriterionDescription, AllocatedMarks, SortOrder) VALUES (?, 'Definition', 'الخلية الوحدة الاساسية للحياة', 10, 1)",
                (question_id,),
            ).lastrowid
        result = self.service.evaluate(answer_id)
        self.assertEqual(result["suggested_score"], 10.0)
        self.assertEqual(result["answer_sheet_status"], "PENDING_REVIEW")
        self.assertTrue(result["needs_grading_review"])
        self.assertFalse(result["semantic_model_configured"])
        self.assertEqual(result["status"], "REQUIRES_REVIEW")
        with self.manager.connection() as conn:
            answer = conn.execute(
                "SELECT SuggestedScore, EvaluationConfidence, NeedsGradingReview, IsApproved FROM QuestionAnswers WHERE AnswerId=?",
                (answer_id,),
            ).fetchone()
            evaluations = conn.execute(
                "SELECT CriterionId, ProcessingRunId, AwardedMarks, IsCurrent FROM AnswerCriterionEvaluations WHERE AnswerId=?",
                (answer_id,),
            ).fetchall()
            runs = conn.execute(
                "SELECT Stage, Status FROM AIProcessingRuns WHERE AnswerId=? ORDER BY ProcessingRunId",
                (answer_id,),
            ).fetchall()
        self.assertEqual(answer["SuggestedScore"], 10)
        self.assertIsNone(answer["EvaluationConfidence"])
        self.assertEqual(answer["NeedsGradingReview"], 1)
        self.assertEqual(answer["IsApproved"], 0)
        self.assertEqual(len(evaluations), 1)
        self.assertEqual(evaluations[0]["CriterionId"], criterion_id)
        self.assertEqual(evaluations[0]["IsCurrent"], 1)
        self.assertEqual([tuple(r) for r in runs], [
            ("SEMANTIC_EVALUATION", "REQUIRES_REVIEW"),
            ("RUBRIC", "REQUIRES_REVIEW"),
        ])

    def test_missing_rubric_description_requires_manual_review_without_score(self):
        question_id, answer_id = self._add_question_answer(4, "ESSAY", 10, "إجابة مكتوبة")
        with self.manager.connection() as conn:
            conn.execute(
                "INSERT INTO RubricCriteria(QuestionId, CriterionTitle, CriterionDescription, AllocatedMarks, SortOrder) VALUES (?, 'Criterion', NULL, 10, 1)",
                (question_id,),
            )
        result = self.service.evaluate(answer_id)
        self.assertIsNone(result["suggested_score"])
        self.assertTrue(result["needs_grading_review"])
        with self.manager.connection() as conn:
            row = conn.execute("SELECT SuggestedScore, NeedsGradingReview FROM QuestionAnswers WHERE AnswerId=?", (answer_id,)).fetchone()
        self.assertIsNone(row["SuggestedScore"])
        self.assertEqual(row["NeedsGradingReview"], 1)


    def test_repeated_rubric_evaluation_keeps_only_one_current_row_per_criterion(self):
        question_id, answer_id = self._add_question_answer(
            7, "ESSAY", 10, "الخلية الوحدة الاساسية للحياة", model_answer="الخلية وحدة الحياة"
        )
        with self.manager.connection() as conn:
            criterion_id = conn.execute(
                "INSERT INTO RubricCriteria(QuestionId, CriterionTitle, CriterionDescription, AllocatedMarks, SortOrder) VALUES (?, 'Definition', 'الخلية الوحدة الاساسية للحياة', 10, 1)",
                (question_id,),
            ).lastrowid
        first = self.service.evaluate(answer_id)
        second = self.service.evaluate(answer_id)
        self.assertNotEqual(first["rubric_processing_run_id"], second["rubric_processing_run_id"])
        with self.manager.connection() as conn:
            rows = conn.execute(
                "SELECT ProcessingRunId, IsCurrent FROM AnswerCriterionEvaluations WHERE AnswerId=? AND CriterionId=? ORDER BY EvaluationId",
                (answer_id, criterion_id),
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["IsCurrent"] for row in rows], [0, 1])

    def test_objective_question_without_correct_choice_is_rejected(self):
        question_id, answer_id = self._add_question_answer(5, "TRUE_FALSE", 2)
        with self.manager.connection() as conn:
            conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'T', 'True', 0, 1)",
                (question_id,),
            )
            conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'F', 'False', 0, 2)",
                (question_id,),
            )
        with self.assertRaises(GradingConfigurationError):
            self.service.evaluate(answer_id)

    def test_approved_answer_cannot_be_re_evaluated(self):
        question_id, answer_id = self._add_question_answer(6, "MULTIPLE_CHOICE", 2)
        with self.manager.connection() as conn:
            admin_id = conn.execute(
                "INSERT INTO Users(Username, FullName, PasswordHash, RoleName) VALUES ('admin', 'Admin', 'hash', 'Admin')"
            ).lastrowid
            correct_id = conn.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, 'A', 'A', 1, 1)",
                (question_id,),
            ).lastrowid
            conn.execute("UPDATE QuestionAnswers SET SelectedChoiceId=? WHERE AnswerId=?", (correct_id, answer_id))
            conn.execute(
                "UPDATE QuestionAnswers SET IsApproved=1, ApprovedScore=2, ApprovedByUserId=?, ApprovedAt=CURRENT_TIMESTAMP WHERE AnswerId=?",
                (admin_id, answer_id),
            )
        with self.assertRaises(GradingConflictError):
            self.service.evaluate(answer_id)

    def test_missing_answer_returns_not_found(self):
        with self.assertRaises(GradingNotFoundError):
            self.service.evaluate(99999)


if __name__ == "__main__":
    unittest.main(verbosity=2)
