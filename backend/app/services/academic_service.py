from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.database.database_manager import DatabaseManager


class AcademicServiceError(RuntimeError):
    pass


class AcademicNotFoundError(AcademicServiceError):
    pass


class AcademicConflictError(AcademicServiceError):
    pass


class AcademicValidationError(AcademicServiceError):
    pass


def _dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _audit(
    conn: sqlite3.Connection,
    actor_user_id: int,
    entity_name: str,
    entity_id: int | str,
    action: str,
    *,
    old_value: Any = None,
    new_value: Any = None,
    details: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO AuditLogs
           (PerformedByUserId, EntityName, EntityId, ActionType, OldValue, NewValue, Details)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            actor_user_id, entity_name, str(entity_id), action,
            json.dumps(old_value, ensure_ascii=False, default=str) if old_value is not None else None,
            json.dumps(new_value, ensure_ascii=False, default=str) if new_value is not None else None,
            details,
        ),
    )


def ensure_answer_rows(conn: sqlite3.Connection, answer_sheet_id: int) -> int:
    """Create a blank QuestionAnswers row for every question in the sheet's exam."""
    sheet = conn.execute(
        """SELECT ES.ExamId FROM AnswerSheets S
           JOIN ExamStudents ES ON ES.ExamStudentId=S.ExamStudentId
           WHERE S.AnswerSheetId=?""",
        (answer_sheet_id,),
    ).fetchone()
    if sheet is None:
        raise AcademicNotFoundError(f"Answer sheet {answer_sheet_id} was not found")
    before = conn.total_changes
    conn.execute(
        """INSERT OR IGNORE INTO QuestionAnswers (AnswerSheetId, QuestionId)
           SELECT ?, Q.QuestionId FROM Questions Q WHERE Q.ExamId=?""",
        (answer_sheet_id, int(sheet["ExamId"])),
    )
    return conn.total_changes - before


class AcademicService:
    def __init__(self, manager: DatabaseManager) -> None:
        self.manager = manager

    # ---------- Students ----------
    def list_students(self, *, search: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        term = f"%{search.strip()}%" if search and search.strip() else None
        with self.manager.connection() as conn:
            total = int(conn.execute(
                "SELECT COUNT(*) FROM Students WHERE (? IS NULL OR AcademicId LIKE ? OR FullName LIKE ?)",
                (term, term, term),
            ).fetchone()[0])
            rows = conn.execute(
                """SELECT StudentId, AcademicId, FullName, CreatedAt FROM Students
                   WHERE (? IS NULL OR AcademicId LIKE ? OR FullName LIKE ?)
                   ORDER BY FullName COLLATE NOCASE, StudentId LIMIT ? OFFSET ?""",
                (term, term, term, limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def get_student(self, student_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            row = conn.execute(
                "SELECT StudentId, AcademicId, FullName, CreatedAt FROM Students WHERE StudentId=?",
                (student_id,),
            ).fetchone()
        if row is None:
            raise AcademicNotFoundError(f"Student {student_id} was not found")
        return dict(row)

    def create_student(self, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        try:
            with self.manager.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    "INSERT INTO Students (AcademicId, FullName) VALUES (?, ?)",
                    (payload["academic_id"], payload["full_name"]),
                )
                student_id = int(cursor.lastrowid)
                _audit(conn, actor_user_id, "Students", student_id, "STUDENT_CREATED", new_value=payload)
                row = conn.execute(
                    "SELECT StudentId, AcademicId, FullName, CreatedAt FROM Students WHERE StudentId=?",
                    (student_id,),
                ).fetchone()
            return dict(row)
        except sqlite3.IntegrityError as exc:
            raise AcademicConflictError("Academic ID already exists or student data conflicts") from exc

    def update_student(self, student_id: int, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        if not payload:
            raise AcademicValidationError("At least one student field must be provided")
        allowed = {"academic_id": "AcademicId", "full_name": "FullName"}
        if set(payload) - set(allowed):
            raise AcademicValidationError("Unsupported student fields")
        try:
            with self.manager.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT * FROM Students WHERE StudentId=?", (student_id,)).fetchone()
                if old is None:
                    raise AcademicNotFoundError(f"Student {student_id} was not found")
                assignments = ", ".join(f"{allowed[key]}=?" for key in payload)
                conn.execute(
                    f"UPDATE Students SET {assignments} WHERE StudentId=?",
                    (*payload.values(), student_id),
                )
                new = conn.execute("SELECT * FROM Students WHERE StudentId=?", (student_id,)).fetchone()
                _audit(conn, actor_user_id, "Students", student_id, "STUDENT_UPDATED", old_value=dict(old), new_value=dict(new))
            return {key: new[key] for key in ("StudentId", "AcademicId", "FullName", "CreatedAt")}
        except sqlite3.IntegrityError as exc:
            raise AcademicConflictError("Student data violates a uniqueness or required-field constraint") from exc

    def delete_student(self, student_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM Students WHERE StudentId=?", (student_id,)).fetchone()
            if row is None:
                raise AcademicNotFoundError(f"Student {student_id} was not found")
            linked = int(conn.execute("SELECT COUNT(*) FROM ExamStudents WHERE StudentId=?", (student_id,)).fetchone()[0])
            if linked:
                raise AcademicConflictError("Student is enrolled in one or more exams and cannot be deleted")
            conn.execute("DELETE FROM Students WHERE StudentId=?", (student_id,))
            _audit(conn, actor_user_id, "Students", student_id, "STUDENT_DELETED", old_value=dict(row))
        return {"deleted": True, "student_id": student_id}

    # ---------- Exams ----------
    def list_exams(self, *, search: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        term = f"%{search.strip()}%" if search and search.strip() else None
        with self.manager.connection() as conn:
            total = int(conn.execute(
                "SELECT COUNT(*) FROM Exams WHERE (? IS NULL OR Title LIKE ? OR SubjectName LIKE ?)",
                (term, term, term),
            ).fetchone()[0])
            rows = conn.execute(
                """SELECT E.ExamId, E.Title, E.SubjectName, E.ExamDate, E.TotalMarks, E.CreatedAt,
                          (SELECT COUNT(*) FROM Questions Q WHERE Q.ExamId=E.ExamId) AS QuestionCount,
                          (SELECT COUNT(*) FROM ExamStudents ES WHERE ES.ExamId=E.ExamId) AS EnrolledCount
                   FROM Exams E WHERE (? IS NULL OR E.Title LIKE ? OR E.SubjectName LIKE ?)
                   ORDER BY COALESCE(E.ExamDate, E.CreatedAt) DESC, E.ExamId DESC LIMIT ? OFFSET ?""",
                (term, term, term, limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def get_exam(self, exam_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            row = conn.execute(
                """SELECT E.*,
                          (SELECT COUNT(*) FROM Questions Q WHERE Q.ExamId=E.ExamId) AS QuestionCount,
                          (SELECT COALESCE(SUM(Q.MaxMarks),0) FROM Questions Q WHERE Q.ExamId=E.ExamId) AS AllocatedQuestionMarks,
                          (SELECT COUNT(*) FROM ExamStudents ES WHERE ES.ExamId=E.ExamId) AS EnrolledCount
                   FROM Exams E WHERE E.ExamId=?""",
                (exam_id,),
            ).fetchone()
        if row is None:
            raise AcademicNotFoundError(f"Exam {exam_id} was not found")
        return dict(row)

    def create_exam(self, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "INSERT INTO Exams (CreatedByUserId, Title, SubjectName, ExamDate, TotalMarks) VALUES (?, ?, ?, ?, ?)",
                (actor_user_id, payload["title"], payload["subject_name"], payload.get("exam_date"), payload["total_marks"]),
            )
            exam_id = int(cursor.lastrowid)
            _audit(conn, actor_user_id, "Exams", exam_id, "EXAM_CREATED", new_value=payload)
        return self.get_exam(exam_id)

    def update_exam(self, exam_id: int, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        if not payload:
            raise AcademicValidationError("At least one exam field must be provided")
        mapping = {"title": "Title", "subject_name": "SubjectName", "exam_date": "ExamDate", "total_marks": "TotalMarks"}
        if set(payload) - set(mapping):
            raise AcademicValidationError("Unsupported exam fields")
        try:
            with self.manager.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT * FROM Exams WHERE ExamId=?", (exam_id,)).fetchone()
                if old is None:
                    raise AcademicNotFoundError(f"Exam {exam_id} was not found")
                assignments = ", ".join(f"{mapping[key]}=?" for key in payload)
                conn.execute(f"UPDATE Exams SET {assignments} WHERE ExamId=?", (*payload.values(), exam_id))
                new = conn.execute("SELECT * FROM Exams WHERE ExamId=?", (exam_id,)).fetchone()
                _audit(conn, actor_user_id, "Exams", exam_id, "EXAM_UPDATED", old_value=dict(old), new_value=dict(new))
        except sqlite3.IntegrityError as exc:
            raise AcademicConflictError("Exam total marks cannot be lower than allocated question marks") from exc
        return self.get_exam(exam_id)

    def delete_exam(self, exam_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM Exams WHERE ExamId=?", (exam_id,)).fetchone()
            if row is None:
                raise AcademicNotFoundError(f"Exam {exam_id} was not found")
            enrolled = int(conn.execute("SELECT COUNT(*) FROM ExamStudents WHERE ExamId=?", (exam_id,)).fetchone()[0])
            if enrolled:
                raise AcademicConflictError("Exam has enrollments; remove or archive it instead of deleting it")
            conn.execute("DELETE FROM Exams WHERE ExamId=?", (exam_id,))
            _audit(conn, actor_user_id, "Exams", exam_id, "EXAM_DELETED", old_value=dict(row))
        return {"deleted": True, "exam_id": exam_id}

    # ---------- Questions ----------
    def list_questions(self, exam_id: int) -> list[dict[str, Any]]:
        self.get_exam(exam_id)
        with self.manager.connection() as conn:
            ids = [int(row[0]) for row in conn.execute(
                "SELECT QuestionId FROM Questions WHERE ExamId=? ORDER BY QuestionNumber", (exam_id,)
            ).fetchall()]
        return [self.get_question(question_id) for question_id in ids]

    def get_question(self, question_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            question = conn.execute("SELECT * FROM Questions WHERE QuestionId=?", (question_id,)).fetchone()
            if question is None:
                raise AcademicNotFoundError(f"Question {question_id} was not found")
            choices = conn.execute(
                "SELECT ChoiceId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder FROM QuestionChoices WHERE QuestionId=? ORDER BY SortOrder",
                (question_id,),
            ).fetchall()
            accepted = conn.execute(
                "SELECT AcceptedAnswerId, AnswerText, CaseSensitive, NormalizeArabic, SortOrder FROM AcceptedAnswers WHERE QuestionId=? ORDER BY SortOrder",
                (question_id,),
            ).fetchall()
            criteria = conn.execute(
                "SELECT CriterionId, CriterionTitle, CriterionDescription, AllocatedMarks, SortOrder FROM RubricCriteria WHERE QuestionId=? ORDER BY SortOrder",
                (question_id,),
            ).fetchall()
        result = dict(question)
        result["choices"] = [dict(row) for row in choices]
        result["accepted_answers"] = [dict(row) for row in accepted]
        result["rubric_criteria"] = [dict(row) for row in criteria]
        return result

    @staticmethod
    def _orders(items: list[dict[str, Any]]) -> list[int]:
        used = {int(item["sort_order"]) for item in items if item.get("sort_order") is not None}
        if len(used) != sum(item.get("sort_order") is not None for item in items):
            raise AcademicValidationError("Sort order values must be unique")
        result: list[int] = []
        next_value = 1
        for item in items:
            if item.get("sort_order") is not None:
                result.append(int(item["sort_order"]))
            else:
                while next_value in used:
                    next_value += 1
                result.append(next_value)
                used.add(next_value)
        if len(set(result)) != len(result):
            raise AcademicValidationError("Sort order values must be unique")
        return result

    def create_question(self, exam_id: int, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        choices = payload.get("choices", [])
        accepted = payload.get("accepted_answers", [])
        criteria = payload.get("rubric_criteria", [])
        choice_orders = self._orders(choices)
        accepted_orders = self._orders(accepted)
        criterion_orders = self._orders(criteria)
        try:
            with self.manager.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT 1 FROM Exams WHERE ExamId=?", (exam_id,)).fetchone() is None:
                    raise AcademicNotFoundError(f"Exam {exam_id} was not found")
                cursor = conn.execute(
                    """INSERT INTO Questions
                       (ExamId, QuestionNumber, QuestionType, QuestionText, ModelAnswer, MaxMarks)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (exam_id, payload["question_number"], payload["question_type"], payload["question_text"], payload.get("model_answer"), payload["max_marks"]),
                )
                question_id = int(cursor.lastrowid)
                for item, order in zip(choices, choice_orders):
                    conn.execute(
                        "INSERT INTO QuestionChoices (QuestionId, ChoiceLabel, ChoiceText, IsCorrect, SortOrder) VALUES (?, ?, ?, ?, ?)",
                        (question_id, item["choice_label"], item["choice_text"], int(item["is_correct"]), order),
                    )
                for item, order in zip(accepted, accepted_orders):
                    conn.execute(
                        "INSERT INTO AcceptedAnswers (QuestionId, AnswerText, CaseSensitive, NormalizeArabic, SortOrder) VALUES (?, ?, ?, ?, ?)",
                        (question_id, item["answer_text"], int(item["case_sensitive"]), int(item["normalize_arabic"]), order),
                    )
                for item, order in zip(criteria, criterion_orders):
                    conn.execute(
                        "INSERT INTO RubricCriteria (QuestionId, CriterionTitle, CriterionDescription, AllocatedMarks, SortOrder) VALUES (?, ?, ?, ?, ?)",
                        (question_id, item["criterion_title"], item["criterion_description"], item["allocated_marks"], order),
                    )
                sheet_ids = [int(row[0]) for row in conn.execute(
                    """SELECT S.AnswerSheetId FROM AnswerSheets S JOIN ExamStudents ES ON ES.ExamStudentId=S.ExamStudentId
                       WHERE ES.ExamId=?""", (exam_id,)
                ).fetchall()]
                for sheet_id in sheet_ids:
                    conn.execute(
                        "INSERT OR IGNORE INTO QuestionAnswers (AnswerSheetId, QuestionId) VALUES (?, ?)",
                        (sheet_id, question_id),
                    )
                _audit(conn, actor_user_id, "Questions", question_id, "QUESTION_CREATED", new_value=payload)
        except sqlite3.IntegrityError as exc:
            message = str(exc)
            if "Question marks exceed" in message:
                raise AcademicConflictError("Question marks exceed the exam total marks") from exc
            raise AcademicConflictError(f"Question configuration conflicts with existing data: {message}") from exc
        return self.get_question(question_id)

    def update_question(self, question_id: int, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        if not payload:
            raise AcademicValidationError("At least one question field must be provided")
        mapping = {"question_text": "QuestionText", "model_answer": "ModelAnswer", "max_marks": "MaxMarks"}
        if set(payload) - set(mapping):
            raise AcademicValidationError("Unsupported question fields")
        try:
            with self.manager.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT * FROM Questions WHERE QuestionId=?", (question_id,)).fetchone()
                if old is None:
                    raise AcademicNotFoundError(f"Question {question_id} was not found")
                if "model_answer" in payload and payload["model_answer"] is None and old["QuestionType"] in {"SHORT_ANSWER", "ESSAY"}:
                    raise AcademicValidationError("This question type requires a model answer")
                assignments = ", ".join(f"{mapping[key]}=?" for key in payload)
                conn.execute(f"UPDATE Questions SET {assignments} WHERE QuestionId=?", (*payload.values(), question_id))
                new = conn.execute("SELECT * FROM Questions WHERE QuestionId=?", (question_id,)).fetchone()
                _audit(conn, actor_user_id, "Questions", question_id, "QUESTION_UPDATED", old_value=dict(old), new_value=dict(new))
        except sqlite3.IntegrityError as exc:
            raise AcademicConflictError(f"Question update conflicts with allocated marks or existing evaluations: {exc}") from exc
        return self.get_question(question_id)

    def delete_question(self, question_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM Questions WHERE QuestionId=?", (question_id,)).fetchone()
            if row is None:
                raise AcademicNotFoundError(f"Question {question_id} was not found")
            answers = int(conn.execute("SELECT COUNT(*) FROM QuestionAnswers WHERE QuestionId=?", (question_id,)).fetchone()[0])
            if answers:
                raise AcademicConflictError("Question already has student answers and cannot be deleted")
            conn.execute("DELETE FROM Questions WHERE QuestionId=?", (question_id,))
            _audit(conn, actor_user_id, "Questions", question_id, "QUESTION_DELETED", old_value=dict(row))
        return {"deleted": True, "question_id": question_id}

    # ---------- Enrollments ----------
    def enroll_students(self, exam_id: int, student_ids: list[int], actor_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM Exams WHERE ExamId=?", (exam_id,)).fetchone() is None:
                raise AcademicNotFoundError(f"Exam {exam_id} was not found")
            placeholders = ",".join("?" for _ in student_ids)
            found = {int(row[0]) for row in conn.execute(
                f"SELECT StudentId FROM Students WHERE StudentId IN ({placeholders})", student_ids
            ).fetchall()}
            missing = sorted(set(student_ids) - found)
            if missing:
                raise AcademicNotFoundError(f"Students not found: {missing}")
            added: list[int] = []
            existing: list[int] = []
            for student_id in student_ids:
                before = conn.total_changes
                conn.execute("INSERT OR IGNORE INTO ExamStudents (ExamId, StudentId) VALUES (?, ?)", (exam_id, student_id))
                if conn.total_changes > before:
                    added.append(student_id)
                else:
                    existing.append(student_id)
            _audit(conn, actor_user_id, "Exams", exam_id, "STUDENTS_ENROLLED", new_value={"added": added}, details=f"Existing enrollments: {existing}")
        return {"exam_id": exam_id, "added_student_ids": added, "already_enrolled_student_ids": existing, "added_count": len(added)}

    def list_enrollments(self, exam_id: int) -> list[dict[str, Any]]:
        self.get_exam(exam_id)
        with self.manager.connection() as conn:
            rows = conn.execute(
                """SELECT ES.ExamStudentId, ES.ExamId, ES.StudentId, S.AcademicId, S.FullName
                   FROM ExamStudents ES JOIN Students S ON S.StudentId=ES.StudentId
                   WHERE ES.ExamId=? ORDER BY S.FullName COLLATE NOCASE""",
                (exam_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def remove_enrollment(self, exam_id: int, student_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM ExamStudents WHERE ExamId=? AND StudentId=?", (exam_id, student_id)).fetchone()
            if row is None:
                raise AcademicNotFoundError("Enrollment was not found")
            if conn.execute("SELECT 1 FROM AnswerSheets WHERE ExamStudentId=?", (row["ExamStudentId"],)).fetchone():
                raise AcademicConflictError("Enrollment already has an answer sheet and cannot be removed")
            conn.execute("DELETE FROM ExamStudents WHERE ExamStudentId=?", (row["ExamStudentId"],))
            _audit(conn, actor_user_id, "ExamStudents", row["ExamStudentId"], "ENROLLMENT_REMOVED", old_value=dict(row))
        return {"removed": True, "exam_id": exam_id, "student_id": student_id}

    # ---------- Answer sheets and answers ----------
    def create_answer_sheet(self, exam_id: int, exam_student_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            enrollment = conn.execute(
                "SELECT ExamStudentId, ExamId FROM ExamStudents WHERE ExamStudentId=?",
                (exam_student_id,),
            ).fetchone()
            if enrollment is None or int(enrollment["ExamId"]) != exam_id:
                raise AcademicNotFoundError("Exam enrollment was not found for this exam")
            existing = conn.execute("SELECT AnswerSheetId FROM AnswerSheets WHERE ExamStudentId=?", (exam_student_id,)).fetchone()
            if existing is not None:
                raise AcademicConflictError(f"An answer sheet already exists: {existing['AnswerSheetId']}")
            cursor = conn.execute("INSERT INTO AnswerSheets (ExamStudentId) VALUES (?)", (exam_student_id,))
            sheet_id = int(cursor.lastrowid)
            created_answers = ensure_answer_rows(conn, sheet_id)
            _audit(conn, actor_user_id, "AnswerSheets", sheet_id, "ANSWER_SHEET_CREATED", new_value={"exam_student_id": exam_student_id, "initialized_answers": created_answers})
        return self.get_answer_sheet(sheet_id)

    def get_answer_sheet(self, answer_sheet_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            row = conn.execute(
                """SELECT S.AnswerSheetId, S.ExamStudentId, S.ProcessingStatus, S.IsBlankOrUnreadable,
                          S.Notes, S.CreatedAt, S.UpdatedAt, ES.ExamId, E.Title AS ExamTitle,
                          ES.StudentId, ST.AcademicId, ST.FullName
                   FROM AnswerSheets S JOIN ExamStudents ES ON ES.ExamStudentId=S.ExamStudentId
                   JOIN Exams E ON E.ExamId=ES.ExamId JOIN Students ST ON ST.StudentId=ES.StudentId
                   WHERE S.AnswerSheetId=?""",
                (answer_sheet_id,),
            ).fetchone()
            if row is None:
                raise AcademicNotFoundError(f"Answer sheet {answer_sheet_id} was not found")
            result = dict(row)
            result["page_count"] = int(conn.execute("SELECT COUNT(*) FROM AnswerPages WHERE AnswerSheetId=?", (answer_sheet_id,)).fetchone()[0])
            result["answer_count"] = int(conn.execute("SELECT COUNT(*) FROM QuestionAnswers WHERE AnswerSheetId=?", (answer_sheet_id,)).fetchone()[0])
        return result

    def list_answer_sheets(self, exam_id: int) -> list[dict[str, Any]]:
        self.get_exam(exam_id)
        with self.manager.connection() as conn:
            rows = conn.execute(
                """SELECT S.AnswerSheetId, S.ExamStudentId, S.ProcessingStatus, S.IsBlankOrUnreadable,
                          ES.StudentId, ST.AcademicId, ST.FullName,
                          (SELECT COUNT(*) FROM AnswerPages P WHERE P.AnswerSheetId=S.AnswerSheetId) AS PageCount,
                          (SELECT COUNT(*) FROM QuestionAnswers A WHERE A.AnswerSheetId=S.AnswerSheetId) AS AnswerCount
                   FROM AnswerSheets S JOIN ExamStudents ES ON ES.ExamStudentId=S.ExamStudentId
                   JOIN Students ST ON ST.StudentId=ES.StudentId
                   WHERE ES.ExamId=? ORDER BY ST.FullName COLLATE NOCASE""",
                (exam_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sheet_answers(self, answer_sheet_id: int) -> list[dict[str, Any]]:
        self.get_answer_sheet(answer_sheet_id)
        with self.manager.connection() as conn:
            rows = conn.execute(
                """SELECT QA.AnswerId, QA.QuestionId, Q.QuestionNumber, Q.QuestionType, Q.QuestionText,
                          Q.MaxMarks, QA.SelectedChoiceId, QA.ExtractedText, QA.EditedText,
                          QA.OcrConfidence, QA.NeedsOcrReview, QA.IsEmptyAnswer, QA.SuggestedScore,
                          QA.SuggestedJustification, QA.EvaluationConfidence, QA.NeedsGradingReview,
                          QA.AdjustedScore, QA.TeacherJustification, QA.TeacherNotes,
                          QA.ApprovedScore, QA.IsApproved,
                          C.ChoiceLabel AS SelectedChoiceLabel, C.ChoiceText AS SelectedChoiceText
                   FROM QuestionAnswers QA JOIN Questions Q ON Q.QuestionId=QA.QuestionId
                   LEFT JOIN QuestionChoices C ON C.ChoiceId=QA.SelectedChoiceId
                   WHERE QA.AnswerSheetId=? ORDER BY Q.QuestionNumber""",
                (answer_sheet_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_answer_response(self, answer_id: int, payload: dict[str, Any], actor_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            answer = conn.execute(
                """SELECT QA.*, Q.QuestionType, Q.MaxMarks, S.ProcessingStatus
                   FROM QuestionAnswers QA JOIN Questions Q ON Q.QuestionId=QA.QuestionId
                   JOIN AnswerSheets S ON S.AnswerSheetId=QA.AnswerSheetId WHERE QA.AnswerId=?""",
                (answer_id,),
            ).fetchone()
            if answer is None:
                raise AcademicNotFoundError(f"Answer {answer_id} was not found")
            if int(answer["IsApproved"]) or answer["ProcessingStatus"] == "FINALLY_APPROVED":
                raise AcademicConflictError("Final-approved answers cannot be changed")
            if answer["QuestionType"] in {"MULTIPLE_CHOICE", "TRUE_FALSE"}:
                if "edited_text" in payload and payload["edited_text"] is not None:
                    raise AcademicValidationError("Objective answers must use selected_choice_id, not edited_text")
                choice_id = payload.get("selected_choice_id", answer["SelectedChoiceId"])
                if choice_id is not None:
                    valid = conn.execute("SELECT 1 FROM QuestionChoices WHERE ChoiceId=? AND QuestionId=?", (choice_id, answer["QuestionId"])).fetchone()
                    if valid is None:
                        raise AcademicValidationError("Selected choice does not belong to this question")
            elif payload.get("selected_choice_id") is not None:
                raise AcademicValidationError("Text questions cannot use selected_choice_id")

            if "is_empty_answer" in payload:
                is_empty = bool(payload["is_empty_answer"])
            elif (payload.get("edited_text") is not None) or (payload.get("selected_choice_id") is not None):
                is_empty = False
            else:
                is_empty = bool(answer["IsEmptyAnswer"])
            selected_choice = None if is_empty else payload.get("selected_choice_id", answer["SelectedChoiceId"])
            edited_text = None if is_empty else payload.get("edited_text", answer["EditedText"])
            extracted_text = None if is_empty else answer["ExtractedText"]
            conn.execute(
                """UPDATE QuestionAnswers SET SelectedChoiceId=?, EditedText=?, ExtractedText=?, IsEmptyAnswer=?,
                   SuggestedScore=NULL, SuggestedJustification=NULL, EvaluationConfidence=NULL, NeedsGradingReview=0,
                   AdjustedScore=NULL, ReviewedByUserId=NULL, TeacherJustification=NULL, TeacherNotes=NULL,
                   UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerId=? AND IsApproved=0""",
                (selected_choice, edited_text, extracted_text, int(is_empty), answer_id),
            )
            new = conn.execute("SELECT * FROM QuestionAnswers WHERE AnswerId=?", (answer_id,)).fetchone()
            conn.execute(
                "UPDATE AnswerSheets SET ProcessingStatus='PENDING_REVIEW', UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerSheetId=? AND ProcessingStatus<>'FINALLY_APPROVED'",
                (answer["AnswerSheetId"],),
            )
            _audit(conn, actor_user_id, "QuestionAnswers", answer_id, "ANSWER_RESPONSE_UPDATED", old_value=dict(answer), new_value=dict(new))
        return {"answer_id": answer_id, "selected_choice_id": selected_choice, "edited_text": edited_text, "is_empty_answer": is_empty}

    def adjust_grade(self, answer_id: int, *, score: float, justification: str, notes: str | None, teacher_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT RoleName, IsActive FROM Users WHERE UserId=?", (teacher_user_id,)).fetchone()
            if user is None or user["RoleName"] != "Teacher" or int(user["IsActive"]) != 1:
                raise AcademicConflictError("Only an active Teacher may adjust a score")
            answer = conn.execute(
                """SELECT QA.*, Q.MaxMarks, S.ProcessingStatus FROM QuestionAnswers QA
                   JOIN Questions Q ON Q.QuestionId=QA.QuestionId JOIN AnswerSheets S ON S.AnswerSheetId=QA.AnswerSheetId
                   WHERE QA.AnswerId=?""",
                (answer_id,),
            ).fetchone()
            if answer is None:
                raise AcademicNotFoundError(f"Answer {answer_id} was not found")
            if int(answer["IsApproved"]) or answer["ProcessingStatus"] == "FINALLY_APPROVED":
                raise AcademicConflictError("Final-approved answers cannot be adjusted")
            if score > float(answer["MaxMarks"]):
                raise AcademicValidationError("Adjusted score exceeds question maximum marks")
            conn.execute(
                """UPDATE QuestionAnswers SET AdjustedScore=?, ReviewedByUserId=?, TeacherJustification=?,
                   TeacherNotes=?, NeedsGradingReview=0, UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerId=?""",
                (score, teacher_user_id, justification, notes, answer_id),
            )
            _audit(conn, teacher_user_id, "QuestionAnswers", answer_id, "TEACHER_SCORE_ADJUSTED", old_value={"adjusted_score": answer["AdjustedScore"]}, new_value={"adjusted_score": score, "justification": justification, "notes": notes})
            self._refresh_sheet_review_status(conn, int(answer["AnswerSheetId"]))
        return {"answer_id": answer_id, "adjusted_score": score, "reviewed_by_user_id": teacher_user_id, "status": "TEACHER_REVIEWED"}

    @staticmethod
    def _refresh_sheet_review_status(conn: sqlite3.Connection, answer_sheet_id: int) -> str:
        sheet = conn.execute("SELECT ProcessingStatus FROM AnswerSheets WHERE AnswerSheetId=?", (answer_sheet_id,)).fetchone()
        if sheet is None:
            raise AcademicNotFoundError("Answer sheet was not found")
        if sheet["ProcessingStatus"] == "FINALLY_APPROVED":
            return "FINALLY_APPROVED"
        counts = conn.execute(
            """SELECT COUNT(*) AS Total,
                      SUM(CASE WHEN IsApproved=1 THEN 1 ELSE 0 END) AS Approved,
                      SUM(CASE WHEN AdjustedScore IS NOT NULL OR (SuggestedScore IS NOT NULL AND NeedsGradingReview=0) THEN 1 ELSE 0 END) AS Reviewed
               FROM QuestionAnswers WHERE AnswerSheetId=?""",
            (answer_sheet_id,),
        ).fetchone()
        total = int(counts["Total"] or 0)
        approved = int(counts["Approved"] or 0)
        reviewed = int(counts["Reviewed"] or 0)
        if total > 0 and approved == total:
            status = "FINALLY_APPROVED"
        elif total > 0 and reviewed == total:
            status = "REVIEWED"
        else:
            status = "PENDING_REVIEW"
        conn.execute("UPDATE AnswerSheets SET ProcessingStatus=?, UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerSheetId=?", (status, answer_sheet_id))
        return status

    def approve_grade(self, answer_id: int, *, score: float | None, note: str, admin_user_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT RoleName, IsActive FROM Users WHERE UserId=?", (admin_user_id,)).fetchone()
            if user is None or user["RoleName"] != "Admin" or int(user["IsActive"]) != 1:
                raise AcademicConflictError("Only an active Admin may approve a final score")
            answer = conn.execute(
                """SELECT QA.*, Q.MaxMarks FROM QuestionAnswers QA JOIN Questions Q ON Q.QuestionId=QA.QuestionId
                   WHERE QA.AnswerId=?""",
                (answer_id,),
            ).fetchone()
            if answer is None:
                raise AcademicNotFoundError(f"Answer {answer_id} was not found")
            if int(answer["IsApproved"]):
                raise AcademicConflictError("Answer already has a final approved score")
            if score is None:
                if int(answer["NeedsGradingReview"] or 0) and answer["AdjustedScore"] is None:
                    raise AcademicConflictError("This answer requires teacher review before administrator approval")
                score = answer["AdjustedScore"] if answer["AdjustedScore"] is not None else answer["SuggestedScore"]
            if score is None:
                raise AcademicValidationError("No score is available to approve; evaluate or adjust the answer first")
            if float(score) < 0 or float(score) > float(answer["MaxMarks"]):
                raise AcademicValidationError("Approved score must be within the question mark range")
            conn.execute(
                """UPDATE QuestionAnswers SET ApprovedScore=?, IsApproved=1, ApprovedByUserId=?,
                   ApprovedAt=CURRENT_TIMESTAMP, UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerId=? AND IsApproved=0""",
                (float(score), admin_user_id, answer_id),
            )
            _audit(conn, admin_user_id, "QuestionAnswers", answer_id, "FINAL_SCORE_APPROVED", old_value={"approved_score": None}, new_value={"approved_score": float(score)}, details=note)
            sheet_status = self._refresh_sheet_review_status(conn, int(answer["AnswerSheetId"]))
        return {"answer_id": answer_id, "approved_score": float(score), "approved_by_user_id": admin_user_id, "answer_sheet_status": sheet_status, "is_approved": True}

    # ---------- Gradebook ----------
    def exam_results(self, exam_id: int) -> dict[str, Any]:
        exam = self.get_exam(exam_id)
        with self.manager.connection() as conn:
            rows = conn.execute(
                """SELECT ES.ExamStudentId, ST.StudentId, ST.AcademicId, ST.FullName,
                          S.AnswerSheetId, S.ProcessingStatus,
                          (SELECT COUNT(*) FROM Questions Q WHERE Q.ExamId=ES.ExamId) AS QuestionCount,
                          (SELECT COUNT(*) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId) AS AnswerCount,
                          (SELECT COUNT(*) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId AND QA.IsApproved=1) AS ApprovedCount,
                          (SELECT COALESCE(SUM(QA.ApprovedScore),0) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId AND QA.IsApproved=1) AS FinalScore,
                          (SELECT COALESCE(SUM(COALESCE(QA.ApprovedScore, QA.AdjustedScore, QA.SuggestedScore, 0)),0) FROM QuestionAnswers QA WHERE QA.AnswerSheetId=S.AnswerSheetId) AS ProvisionalScore
                   FROM ExamStudents ES JOIN Students ST ON ST.StudentId=ES.StudentId
                   LEFT JOIN AnswerSheets S ON S.ExamStudentId=ES.ExamStudentId
                   WHERE ES.ExamId=? ORDER BY ST.FullName COLLATE NOCASE""",
                (exam_id,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            q_count = int(item["QuestionCount"] or 0)
            approved = int(item["ApprovedCount"] or 0)
            item["question_count"] = q_count
            item["answer_count"] = int(item["AnswerCount"] or 0)
            item["approved_count"] = approved
            item["final_score"] = float(item["FinalScore"] or 0) if q_count > 0 and approved == q_count else None
            item["provisional_score"] = float(item["ProvisionalScore"] or 0)
            item["completion_percent"] = round((approved / q_count) * 100, 2) if q_count else 0.0
            item["result_status"] = "FINAL" if item["final_score"] is not None else (item["ProcessingStatus"] or "NO_ANSWER_SHEET")
            items.append(item)
        return {"exam": exam, "items": items, "enrolled_count": len(items), "question_count": int(exam["QuestionCount"])}
