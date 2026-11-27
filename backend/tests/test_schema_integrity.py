"""Self-contained integrity tests for Madar_Schema_v1.sql.

Run from the same folder as the schema file:
    py Madar_Schema_Tests.py
Uses only Python's standard library (sqlite3, unittest).
"""
from pathlib import Path
import sqlite3
import unittest

_HERE = Path(__file__).resolve().parent
SCHEMA_PATH = _HERE / "Madar_Schema_v1.sql"
if not SCHEMA_PATH.exists():
    SCHEMA_PATH = _HERE.parent / "app" / "database" / "schema.sql"


class MadarSchemaTests(unittest.TestCase):
    def setUp(self):
        if not SCHEMA_PATH.exists():
            self.fail(f"Schema file not found: {SCHEMA_PATH}")
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._seed_base()

    def tearDown(self):
        self.db.close()

    def _seed_base(self):
        cur = self.db.cursor()
        cur.execute(
            "INSERT INTO Users(Username, FullName, PasswordHash, RoleName) VALUES (?, ?, ?, ?)",
            ("teacher1", "Teacher One", "test-hash", "Teacher"),
        )
        self.teacher_id = cur.lastrowid
        cur.execute(
            "INSERT INTO Users(Username, FullName, PasswordHash, RoleName) VALUES (?, ?, ?, ?)",
            ("admin1", "Admin One", "test-hash", "Admin"),
        )
        self.admin_id = cur.lastrowid
        cur.execute(
            "INSERT INTO Users(Username, FullName, PasswordHash, RoleName) VALUES (?, ?, ?, ?)",
            ("reviewer1", "Reviewer One", "test-hash", "Reviewer"),
        )
        self.reviewer_id = cur.lastrowid
        cur.execute("INSERT INTO Students(AcademicId, FullName) VALUES (?, ?)", ("ST-001", "Student One"))
        self.student_id = cur.lastrowid
        cur.execute(
            "INSERT INTO Exams(CreatedByUserId, Title, SubjectName, TotalMarks) VALUES (?, ?, ?, ?)",
            (self.teacher_id, "Science Exam", "Science", 20),
        )
        self.exam_id = cur.lastrowid
        cur.execute("INSERT INTO ExamStudents(ExamId, StudentId) VALUES (?, ?)", (self.exam_id, self.student_id))
        self.exam_student_id = cur.lastrowid
        cur.execute(
            "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, ModelAnswer, MaxMarks) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self.exam_id, 1, "ESSAY", "Define a cell", "The cell is the basic unit of life.", 10),
        )
        self.question_id = cur.lastrowid
        cur.execute(
            "INSERT INTO RubricCriteria(QuestionId, CriterionTitle, AllocatedMarks, SortOrder) VALUES (?, ?, ?, ?)",
            (self.question_id, "Definition", 4, 1),
        )
        self.criterion_id = cur.lastrowid
        cur.execute("INSERT INTO AnswerSheets(ExamStudentId) VALUES (?)", (self.exam_student_id,))
        self.sheet_id = cur.lastrowid
        cur.execute(
            "INSERT INTO AnswerPages(AnswerSheetId, PageNumber, OriginalImagePath) VALUES (?, ?, ?)",
            (self.sheet_id, 1, "storage/original_images/page1.jpg"),
        )
        self.page_id = cur.lastrowid
        cur.execute(
            "INSERT INTO QuestionAnswers(AnswerSheetId, QuestionId, ExtractedText, SuggestedScore, EvaluationConfidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.sheet_id, self.question_id, "The cell is the basic unit.", 4, 95),
        )
        self.answer_id = cur.lastrowid
        cur.execute(
            "INSERT INTO QuestionAnswerPages(AnswerId, PageId, SegmentOrder, RegionX, RegionY, RegionWidth, RegionHeight) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.answer_id, self.page_id, 1, 0.1, 0.1, 0.6, 0.25),
        )
        cur.execute(
            "INSERT INTO AIProcessingRuns(AnswerSheetId, AnswerId, Stage, ModelName, Status) "
            "VALUES (?, ?, 'RUBRIC', 'test-model', 'SUCCEEDED')",
            (self.sheet_id, self.answer_id),
        )
        self.run_id = cur.lastrowid
        cur.execute(
            "INSERT INTO AnswerCriterionEvaluations(AnswerId, CriterionId, ProcessingRunId, AwardedMarks, "
            "EvidenceText, Explanation, Confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.answer_id, self.criterion_id, self.run_id, 4, "basic unit", "Key idea present", 93),
        )
        self.db.commit()

    def _new_question_in_other_exam(self):
        cur = self.db.cursor()
        cur.execute("INSERT INTO Exams(Title, SubjectName, TotalMarks) VALUES (?, ?, ?)", ("Other Exam", "Science", 10))
        other_exam_id = cur.lastrowid
        cur.execute(
            "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, ModelAnswer, MaxMarks) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (other_exam_id, 1, "ESSAY", "Other question", "Other answer", 5),
        )
        return cur.lastrowid

    def test_schema_objects_exist(self):
        tables = self.db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        triggers = self.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
        self.assertEqual(tables, 17)
        self.assertEqual(triggers, 29)

    def test_multi_page_answer_and_rubric_evaluation(self):
        count = self.db.execute(
            "SELECT COUNT(*) FROM QuestionAnswerPages WHERE AnswerId=?", (self.answer_id,)
        ).fetchone()[0]
        self.assertEqual(count, 1)
        awarded = self.db.execute(
            "SELECT AwardedMarks FROM AnswerCriterionEvaluations WHERE AnswerId=? AND IsCurrent=1",
            (self.answer_id,),
        ).fetchone()[0]
        self.assertEqual(awarded, 4)

    def test_question_must_belong_to_same_exam(self):
        other_question_id = self._new_question_in_other_exam()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO QuestionAnswers(AnswerSheetId, QuestionId) VALUES (?, ?)",
                (self.sheet_id, other_question_id),
            )

    def test_page_must_belong_to_same_answer_sheet(self):
        cur = self.db.cursor()
        cur.execute("INSERT INTO Students(AcademicId, FullName) VALUES (?, ?)", ("ST-002", "Student Two"))
        student2 = cur.lastrowid
        cur.execute("INSERT INTO ExamStudents(ExamId, StudentId) VALUES (?, ?)", (self.exam_id, student2))
        exam_student2 = cur.lastrowid
        cur.execute("INSERT INTO AnswerSheets(ExamStudentId) VALUES (?)", (exam_student2,))
        sheet2 = cur.lastrowid
        cur.execute(
            "INSERT INTO AnswerPages(AnswerSheetId, PageNumber, OriginalImagePath) VALUES (?, ?, ?)",
            (sheet2, 1, "storage/original_images/page2.jpg"),
        )
        page2 = cur.lastrowid
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO QuestionAnswerPages(AnswerId, PageId, SegmentOrder) VALUES (?, ?, ?)",
                (self.answer_id, page2, 2),
            )

    def test_only_teacher_can_adjust_score(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE QuestionAnswers SET AdjustedScore=3, ReviewedByUserId=? WHERE AnswerId=?",
                (self.reviewer_id, self.answer_id),
            )
        self.db.execute(
            "UPDATE QuestionAnswers SET AdjustedScore=3, ReviewedByUserId=? WHERE AnswerId=?",
            (self.teacher_id, self.answer_id),
        )

    def test_only_admin_can_approve_score(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE QuestionAnswers SET IsApproved=1, ApprovedScore=4, ApprovedByUserId=?, "
                "ApprovedAt=CURRENT_TIMESTAMP WHERE AnswerId=?",
                (self.teacher_id, self.answer_id),
            )
        self.db.execute(
            "UPDATE QuestionAnswers SET IsApproved=1, ApprovedScore=4, ApprovedByUserId=?, "
            "ApprovedAt=CURRENT_TIMESTAMP WHERE AnswerId=?",
            (self.admin_id, self.answer_id),
        )

    def test_rubric_total_cannot_exceed_question_marks(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO RubricCriteria(QuestionId, CriterionTitle, AllocatedMarks, SortOrder) "
                "VALUES (?, ?, ?, ?)",
                (self.question_id, "Excess criterion", 7, 2),
            )

    def test_answer_score_cannot_exceed_question_marks(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE QuestionAnswers SET SuggestedScore=11 WHERE AnswerId=?", (self.answer_id,)
            )

    def test_exam_total_cannot_be_reduced_below_question_sum(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE Exams SET TotalMarks=5 WHERE ExamId=?", (self.exam_id,))

    def test_multiple_choice_question_and_selected_choice(self):
        cur = self.db.cursor()
        cur.execute(
            "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, MaxMarks) "
            "VALUES (?, ?, 'MULTIPLE_CHOICE', ?, ?)",
            (self.exam_id, 2, "Choose the correct answer", 2),
        )
        question_id = cur.lastrowid
        cur.execute(
            "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) "
            "VALUES (?, 'A', 'Option A', 1, 1)",
            (question_id,),
        )
        correct_choice_id = cur.lastrowid
        cur.execute(
            "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) "
            "VALUES (?, 'B', 'Option B', 0, 2)",
            (question_id,),
        )
        cur.execute(
            "INSERT INTO QuestionAnswers(AnswerSheetId, QuestionId, SelectedChoiceId) VALUES (?, ?, ?)",
            (self.sheet_id, question_id, correct_choice_id),
        )
        self.assertEqual(
            self.db.execute(
                "SELECT SelectedChoiceId FROM QuestionAnswers WHERE AnswerSheetId=? AND QuestionId=?",
                (self.sheet_id, question_id),
            ).fetchone()[0],
            correct_choice_id,
        )

    def test_only_one_correct_choice_is_allowed(self):
        cur = self.db.cursor()
        cur.execute(
            "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, MaxMarks) "
            "VALUES (?, ?, 'MULTIPLE_CHOICE', ?, ?)",
            (self.exam_id, 2, "Choose one", 2),
        )
        question_id = cur.lastrowid
        cur.execute(
            "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) "
            "VALUES (?, 'A', 'A', 1, 1)",
            (question_id,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO QuestionChoices(QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) "
                "VALUES (?, 'B', 'B', 1, 2)",
                (question_id,),
            )

    def test_fill_blank_accepted_answers(self):
        cur = self.db.cursor()
        cur.execute(
            "INSERT INTO Questions(ExamId, QuestionNumber, QuestionType, QuestionText, MaxMarks) "
            "VALUES (?, ?, 'FILL_BLANK', ?, ?)",
            (self.exam_id, 2, "Complete the sentence", 2),
        )
        question_id = cur.lastrowid
        cur.execute(
            "INSERT INTO AcceptedAnswers(QuestionId, AnswerText, SortOrder) VALUES (?, ?, ?)",
            (question_id, "mitochondria", 1),
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM AcceptedAnswers WHERE QuestionId=?", (question_id,)).fetchone()[0],
            1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO AcceptedAnswers(QuestionId, AnswerText, SortOrder) VALUES (?, ?, ?)",
                (self.question_id, "not allowed for essay", 1),
            )

    def test_answer_region_must_be_within_page(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO QuestionAnswerPages(AnswerId, PageId, SegmentOrder, RegionX, RegionY, RegionWidth, RegionHeight) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.answer_id, self.page_id, 2, 0.8, 0.1, 0.4, 0.2),
            )

    def test_foreign_key_integrity(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MadarSchemaTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
