from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QuestionType = Literal["MULTIPLE_CHOICE", "TRUE_FALSE", "FILL_BLANK", "SHORT_ANSWER", "ESSAY", "ASSIGNMENT"]


class AcademicPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudentCreate(AcademicPayload):
    academic_id: str = Field(min_length=1, max_length=80)
    full_name: str = Field(min_length=2, max_length=200)

    @field_validator("academic_id", "full_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value


class StudentUpdate(AcademicPayload):
    academic_id: str | None = Field(default=None, min_length=1, max_length=80)
    full_name: str | None = Field(default=None, min_length=2, max_length=200)

    @field_validator("academic_id", "full_name")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_update_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one student field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Student fields cannot be null")
        return self


class ExamCreate(AcademicPayload):
    title: str = Field(min_length=2, max_length=200)
    subject_name: str = Field(min_length=2, max_length=120)
    exam_date: str | None = Field(default=None, max_length=40)
    total_marks: float = Field(gt=0, le=100000)

    @field_validator("title", "subject_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("exam_date")
    @classmethod
    def validate_exam_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        from datetime import date, datetime
        try:
            date.fromisoformat(value)
        except ValueError:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("exam_date must be ISO date or ISO datetime") from exc
        return value


class ExamUpdate(AcademicPayload):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    subject_name: str | None = Field(default=None, min_length=2, max_length=120)
    exam_date: str | None = Field(default=None, max_length=40)
    total_marks: float | None = Field(default=None, gt=0, le=100000)

    @field_validator("title", "subject_name")
    @classmethod
    def strip_optional_exam_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("exam_date")
    @classmethod
    def validate_optional_exam_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        from datetime import date, datetime
        try:
            date.fromisoformat(value)
        except ValueError:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("exam_date must be ISO date or ISO datetime") from exc
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field in ("title", "subject_name", "total_marks"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ChoiceInput(AcademicPayload):
    choice_label: str = Field(min_length=1, max_length=10)
    choice_text: str = Field(min_length=1, max_length=2000)
    is_correct: bool = False
    sort_order: int | None = Field(default=None, gt=0)

    @field_validator("choice_label", "choice_text")
    @classmethod
    def strip_choice(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Choice values cannot be blank")
        return value


class AcceptedAnswerInput(AcademicPayload):
    answer_text: str = Field(min_length=1, max_length=2000)
    case_sensitive: bool = False
    normalize_arabic: bool = True
    sort_order: int | None = Field(default=None, gt=0)

    @field_validator("answer_text")
    @classmethod
    def strip_answer(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Accepted answer cannot be blank")
        return value


class RubricCriterionInput(AcademicPayload):
    criterion_title: str = Field(min_length=1, max_length=200)
    criterion_description: str = Field(min_length=1, max_length=4000)
    allocated_marks: float = Field(ge=0, le=100000)
    sort_order: int | None = Field(default=None, gt=0)

    @field_validator("criterion_title", "criterion_description")
    @classmethod
    def strip_criterion(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Rubric text cannot be blank")
        return value


class QuestionCreate(AcademicPayload):
    question_number: int = Field(gt=0)
    question_type: QuestionType
    question_text: str = Field(min_length=1, max_length=10000)
    model_answer: str | None = Field(default=None, max_length=10000)
    max_marks: float = Field(gt=0, le=100000)
    choices: list[ChoiceInput] = Field(default_factory=list, max_length=20)
    accepted_answers: list[AcceptedAnswerInput] = Field(default_factory=list, max_length=100)
    rubric_criteria: list[RubricCriterionInput] = Field(default_factory=list, max_length=100)

    @field_validator("question_text", "model_answer")
    @classmethod
    def strip_question_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_question_configuration(self):
        qtype = self.question_type
        if qtype in {"MULTIPLE_CHOICE", "TRUE_FALSE"}:
            if qtype == "MULTIPLE_CHOICE" and len(self.choices) < 2:
                raise ValueError("MULTIPLE_CHOICE requires at least two choices")
            if qtype == "TRUE_FALSE" and len(self.choices) != 2:
                raise ValueError("TRUE_FALSE requires exactly two choices")
            if sum(choice.is_correct for choice in self.choices) != 1:
                raise ValueError("Objective questions require exactly one correct choice")
            if self.accepted_answers or self.rubric_criteria:
                raise ValueError("Objective questions cannot contain accepted answers or rubric criteria")
            labels = [choice.choice_label.casefold() for choice in self.choices]
            if len(labels) != len(set(labels)):
                raise ValueError("Choice labels must be unique")
        elif qtype == "FILL_BLANK":
            if not self.accepted_answers:
                raise ValueError("FILL_BLANK requires at least one accepted answer")
            if self.choices or self.rubric_criteria:
                raise ValueError("FILL_BLANK cannot contain choices or rubric criteria")
        elif qtype == "SHORT_ANSWER":
            if not self.model_answer:
                raise ValueError("SHORT_ANSWER requires a model answer")
            if bool(self.accepted_answers) == bool(self.rubric_criteria):
                raise ValueError("SHORT_ANSWER requires either accepted answers or rubric criteria, not both")
            if self.choices:
                raise ValueError("SHORT_ANSWER cannot contain choices")
        elif qtype in {"ESSAY", "ASSIGNMENT"}:
            if qtype == "ESSAY" and not self.model_answer:
                raise ValueError("ESSAY requires a model answer")
            if not self.rubric_criteria:
                raise ValueError(f"{qtype} requires rubric criteria")
            if self.choices or self.accepted_answers:
                raise ValueError(f"{qtype} cannot contain choices or accepted answers")

        if self.rubric_criteria:
            total = sum(item.allocated_marks for item in self.rubric_criteria)
            if abs(total - self.max_marks) > 1e-6:
                raise ValueError("Rubric allocated marks must equal question max_marks")
            orders = [item.sort_order for item in self.rubric_criteria if item.sort_order is not None]
            if len(orders) != len(set(orders)):
                raise ValueError("Rubric sort_order values must be unique")
        answer_texts = [item.answer_text for item in self.accepted_answers]
        if len(answer_texts) != len(set(answer_texts)):
            raise ValueError("Accepted answer variants must be unique")
        return self


class QuestionUpdate(AcademicPayload):
    question_text: str | None = Field(default=None, min_length=1, max_length=10000)
    model_answer: str | None = Field(default=None, max_length=10000)
    max_marks: float | None = Field(default=None, gt=0, le=100000)

    @field_validator("question_text", "model_answer")
    @classmethod
    def strip_optional_question_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field in ("question_text", "max_marks"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class EnrollmentBatch(AcademicPayload):
    student_ids: list[int] = Field(min_length=1, max_length=500)

    @field_validator("student_ids")
    @classmethod
    def unique_student_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("Student IDs must be positive")
        if len(value) != len(set(value)):
            raise ValueError("Duplicate student IDs are not allowed")
        return value


class AnswerSheetCreate(AcademicPayload):
    exam_student_id: int = Field(gt=0)


class AnswerResponseUpdate(AcademicPayload):
    selected_choice_id: int | None = Field(default=None, gt=0)
    edited_text: str | None = Field(default=None, max_length=20000)
    is_empty_answer: bool = False

    @field_validator("edited_text")
    @classmethod
    def strip_edited_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def require_response_field(self):
        if not self.model_fields_set:
            raise ValueError("At least one response field must be provided")
        return self


class GradeAdjustment(AcademicPayload):
    adjusted_score: float = Field(ge=0, le=100000)
    teacher_justification: str = Field(min_length=3, max_length=4000)
    teacher_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("teacher_justification", "teacher_notes")
    @classmethod
    def strip_grade_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value and value is not None:
            raise ValueError("Text cannot be blank")
        return value


class ScoreApproval(AcademicPayload):
    approved_score: float | None = Field(default=None, ge=0, le=100000)
    approval_note: str = Field(min_length=3, max_length=4000)

    @field_validator("approval_note")
    @classmethod
    def strip_approval_note(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Approval note cannot be blank")
        return value
