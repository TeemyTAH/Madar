from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from backend.app.database.database_manager import DatabaseManager
from backend.app.services.processing_runs import ProcessingRunTracker, refresh_answer_sheet_status
from backend.app.services.rubric_evaluator import KeywordEvidenceEvaluator, RubricEvaluator


class GradingServiceError(RuntimeError):
    pass


class GradingNotFoundError(GradingServiceError):
    pass


class GradingConflictError(GradingServiceError):
    pass


class GradingConfigurationError(GradingServiceError):
    pass


def normalize_answer_text(text: str, normalize_arabic: bool = True, case_sensitive: bool = False) -> str:
    value = unicodedata.normalize("NFC", str(text or "")).strip()
    value = re.sub(r"\s+", " ", value)
    if normalize_arabic:
        value = re.sub(r"[\u064B-\u065F\u0670\u06D6-\u06ED]", "", value).replace("ـ", "")
        value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"}))
    return value if case_sensitive else value.casefold()


class GradingService:
    """Deterministic objective grading plus a conservative rubric evidence baseline.

    No semantic-language model is bundled/configured in this package. Free-response
    suggestions are therefore explicitly heuristic and ALWAYS require teacher review.
    This service never writes AdjustedScore or ApprovedScore.
    """

    MODEL_NAME = "Madar-Grading-Rules"
    MODEL_VERSION = "1.0.0"

    def __init__(self, manager: DatabaseManager, rubric_evaluator: RubricEvaluator | None = None) -> None:
        self.manager = manager
        self.runs = ProcessingRunTracker(manager)
        self.rubric_evaluator = rubric_evaluator or KeywordEvidenceEvaluator()

    def _load_answer(self, answer_id: int) -> tuple[Any, list[Any], list[Any], list[Any]]:
        with self.manager.connection() as conn:
            answer = conn.execute(
                """
                SELECT QA.*, Q.QuestionNumber, Q.QuestionType, Q.QuestionText,
                       Q.ModelAnswer, Q.MaxMarks, S.ProcessingStatus
                FROM QuestionAnswers QA
                JOIN Questions Q ON Q.QuestionId=QA.QuestionId
                JOIN AnswerSheets S ON S.AnswerSheetId=QA.AnswerSheetId
                WHERE QA.AnswerId=?
                """,
                (answer_id,),
            ).fetchone()
            if answer is None:
                return None, [], [], []
            choices = conn.execute(
                "SELECT ChoiceId, ChoiceLabel, ChoiceText, IsCorrect FROM QuestionChoices WHERE QuestionId=? ORDER BY SortOrder",
                (answer["QuestionId"],),
            ).fetchall()
            accepted = conn.execute(
                "SELECT AnswerText, CaseSensitive, NormalizeArabic FROM AcceptedAnswers WHERE QuestionId=? ORDER BY SortOrder",
                (answer["QuestionId"],),
            ).fetchall()
            criteria = conn.execute(
                "SELECT CriterionId, CriterionTitle, CriterionDescription, AllocatedMarks, SortOrder FROM RubricCriteria WHERE QuestionId=? ORDER BY SortOrder",
                (answer["QuestionId"],),
            ).fetchall()
        return answer, list(choices), list(accepted), list(criteria)

    def _create_run(self, answer, stage: str, model_name: str | None = None, model_version: str | None = None) -> tuple[int, float]:
        run_id = self.runs.create(
            answer_sheet_id=int(answer["AnswerSheetId"]),
            answer_id=int(answer["AnswerId"]),
            stage=stage,
            model_name=model_name or self.MODEL_NAME,
            model_version=model_version or self.MODEL_VERSION,
        )
        return run_id, self.runs.start(run_id)

    def evaluate(self, answer_id: int) -> dict[str, Any]:
        answer, choices, accepted, criteria = self._load_answer(answer_id)
        if answer is None:
            raise GradingNotFoundError(f"Answer {answer_id} was not found")
        if answer["IsApproved"]:
            raise GradingConflictError("This answer already has a final approved score; new AI evaluation is blocked")

        question_type = answer["QuestionType"]
        if question_type in {"MULTIPLE_CHOICE", "TRUE_FALSE"}:
            return self._evaluate_choice(answer, choices)
        if question_type == "FILL_BLANK":
            return self._evaluate_accepted_text(answer, accepted)
        if question_type == "SHORT_ANSWER" and accepted:
            return self._evaluate_accepted_text(answer, accepted)
        return self._evaluate_rubric(answer, criteria)

    def _persist_deterministic(
        self,
        answer,
        *,
        score: float,
        explanation: str,
        method: str,
        needs_review: bool = False,
    ) -> dict[str, Any]:
        run_id, started = self._create_run(answer, "SEMANTIC_EVALUATION", model_name=method)
        result = {
            "answer_id": int(answer["AnswerId"]),
            "question_number": int(answer["QuestionNumber"]),
            "question_type": answer["QuestionType"],
            "suggested_score": round(float(score), 2),
            "max_marks": float(answer["MaxMarks"]),
            "evaluation_confidence": None if needs_review else 100.0,
            "needs_grading_review": bool(needs_review),
            "status": "REQUIRES_REVIEW" if needs_review else "SUCCEEDED",
            "method": method,
            "explanation": explanation,
            "final_approval": "NOT_APPROVED",
        }
        try:
            with self.manager.connection() as conn:
                cursor = conn.execute(
                    """
                    UPDATE QuestionAnswers
                    SET SuggestedScore=?, SuggestedJustification=?, EvaluationConfidence=?,
                        NeedsGradingReview=?, UpdatedAt=CURRENT_TIMESTAMP
                    WHERE AnswerId=? AND IsApproved=0
                    """,
                    (round(float(score), 2), explanation, None if needs_review else 100, int(needs_review), answer["AnswerId"]),
                )
                if cursor.rowcount != 1:
                    raise GradingConflictError("The answer was approved while grading was running")
                conn.execute(
                    """
                    INSERT INTO AuditLogs(EntityName, EntityId, ActionType, NewValue, Details)
                    VALUES ('QuestionAnswers', ?, 'DETERMINISTIC_SCORE_SUGGESTED', ?, ?)
                    """,
                    (str(answer["AnswerId"]), str(round(float(score), 2)), json.dumps(result, ensure_ascii=False)),
                )
            self.runs.finish(
                run_id, started,
                status="REQUIRES_REVIEW" if needs_review else "SUCCEEDED",
                output=result,
            )
            result["answer_sheet_status"] = refresh_answer_sheet_status(
                self.manager, int(answer["AnswerSheetId"])
            )
        except Exception as exc:
            self.runs.fail_if_running(run_id, started, exc)
            raise
        return {**result, "processing_run_id": run_id}

    def _evaluate_choice(self, answer, choices: list[Any]) -> dict[str, Any]:
        correct = [choice for choice in choices if int(choice["IsCorrect"]) == 1]
        if len(correct) != 1:
            raise GradingConfigurationError(
                "Published objective question must contain exactly one correct choice"
            )
        if answer["QuestionType"] == "TRUE_FALSE" and len(choices) != 2:
            raise GradingConfigurationError("TRUE_FALSE question must contain exactly two choices")
        if answer["QuestionType"] == "MULTIPLE_CHOICE" and len(choices) < 2:
            raise GradingConfigurationError("MULTIPLE_CHOICE question must contain at least two choices")
        selected_id = answer["SelectedChoiceId"]
        if selected_id is not None and not any(int(c["ChoiceId"]) == int(selected_id) for c in choices):
            raise GradingConfigurationError("Selected choice does not belong to this question")
        is_correct = selected_id is not None and int(selected_id) == int(correct[0]["ChoiceId"])
        score = float(answer["MaxMarks"]) if is_correct else 0.0
        explanation = "الإجابة المحددة صحيحة." if is_correct else (
            "لم تُسجّل إجابة محددة." if selected_id is None else "الإجابة المحددة لا تطابق الخيار الصحيح."
        )
        return self._persist_deterministic(
            answer, score=score, explanation=explanation,
            method="deterministic-choice-v1",
        )

    def _evaluate_accepted_text(self, answer, accepted: list[Any]) -> dict[str, Any]:
        if not accepted:
            raise GradingConfigurationError("No accepted answer variants are configured for this question")
        submitted = answer["EditedText"] if answer["EditedText"] is not None else answer["ExtractedText"]
        submitted = str(submitted or "").strip()
        matched = False
        matched_variant = None
        if submitted:
            for variant in accepted:
                expected = str(variant["AnswerText"])
                actual_norm = normalize_answer_text(
                    submitted,
                    normalize_arabic=bool(variant["NormalizeArabic"]),
                    case_sensitive=bool(variant["CaseSensitive"]),
                )
                expected_norm = normalize_answer_text(
                    expected,
                    normalize_arabic=bool(variant["NormalizeArabic"]),
                    case_sensitive=bool(variant["CaseSensitive"]),
                )
                if actual_norm == expected_norm:
                    matched = True
                    matched_variant = expected
                    break
        score = float(answer["MaxMarks"]) if matched else 0.0
        explanation = (
            f"تمت مطابقة الإجابة مع إجابة مقبولة: {matched_variant}." if matched
            else "لم تتطابق الإجابة مع أي صيغة مقبولة مسجلة؛ يلزم التحقق من الإجابة إذا كانت صياغتها صحيحة بمعنى مختلف."
        )
        return self._persist_deterministic(
            answer,
            score=score,
            explanation=explanation,
            method="deterministic-accepted-answer-v1",
            needs_review=not matched,
        )

    def _evaluate_rubric(self, answer, criteria: list[Any]) -> dict[str, Any]:
        semantic_run, semantic_started = self._create_run(
            answer, "SEMANTIC_EVALUATION", model_name="semantic-model-not-configured", model_version="none"
        )
        rubric_run = None
        rubric_started = None
        try:
            submitted = answer["EditedText"] if answer["EditedText"] is not None else answer["ExtractedText"]
            submitted = str(submitted or "").strip()
            max_marks = float(answer["MaxMarks"])
            rubric_total = sum(float(c["AllocatedMarks"]) for c in criteria)
            reasons: list[str] = []
            if not submitted:
                reasons.append("لا يوجد نص إجابة صالح للتقييم.")
            if not criteria:
                reasons.append("لا توجد معايير Rubric مرتبطة بالسؤال.")
            if criteria and not math_isclose(rubric_total, max_marks):
                reasons.append("مجموع درجات المعايير لا يساوي الدرجة الكلية للسؤال.")
            if criteria and any(not str(c["CriterionDescription"] or "").strip() for c in criteria):
                reasons.append("يجب إضافة وصف واضح قابل للتقييم لكل معيار Rubric.")

            semantic_output = {
                "answer_id": int(answer["AnswerId"]),
                "status": "REQUIRES_REVIEW",
                "semantic_model_configured": False,
                "message": "لا يوجد نموذج دلالي Semantic Model مهيأ في هذه النسخة؛ لن ندّعي فهماً دلالياً غير موجود.",
            }
            self.runs.finish(
                semantic_run, semantic_started, status="REQUIRES_REVIEW", output=semantic_output
            )

            rubric_run, rubric_started = self._create_run(
                answer, "RUBRIC", model_name=self.rubric_evaluator.model_name,
                model_version=self.rubric_evaluator.model_version
            )
            if reasons:
                result = {
                    "answer_id": int(answer["AnswerId"]),
                    "question_number": int(answer["QuestionNumber"]),
                    "question_type": answer["QuestionType"],
                    "suggested_score": None,
                    "max_marks": max_marks,
                    "evaluation_confidence": None,
                    "needs_grading_review": True,
                    "status": "REQUIRES_REVIEW",
                    "review_reasons": reasons,
                    "semantic_model_configured": False,
                    "final_approval": "NOT_APPROVED",
                }
                with self.manager.connection() as conn:
                    cursor = conn.execute(
                        "UPDATE QuestionAnswers SET SuggestedScore=NULL, SuggestedJustification=?, EvaluationConfidence=NULL, NeedsGradingReview=1, UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerId=? AND IsApproved=0",
                        (" ".join(reasons), answer["AnswerId"]),
                    )
                    if cursor.rowcount != 1:
                        raise GradingConflictError("The answer was approved while grading was running")
                self.runs.finish(rubric_run, rubric_started, status="REQUIRES_REVIEW", output=result)
                result["answer_sheet_status"] = refresh_answer_sheet_status(
                    self.manager, int(answer["AnswerSheetId"])
                )
                return {**result, "semantic_processing_run_id": semantic_run, "rubric_processing_run_id": rubric_run}

            suggestions = self.rubric_evaluator.evaluate(submitted, criteria)
            if len(suggestions) != len(criteria):
                reasons.append("معيار واحد على الأقل لا يحتوي مفردات دليل كافية في وصفه.")

            if reasons or len(suggestions) != len(criteria):
                result = {
                    "answer_id": int(answer["AnswerId"]),
                    "question_number": int(answer["QuestionNumber"]),
                    "suggested_score": None,
                    "max_marks": max_marks,
                    "evaluation_confidence": None,
                    "needs_grading_review": True,
                    "status": "REQUIRES_REVIEW",
                    "review_reasons": reasons or ["تعذر استخراج مفردات تقييم كافية من معيار واحد على الأقل."],
                    "semantic_model_configured": False,
                    "final_approval": "NOT_APPROVED",
                }
                with self.manager.connection() as conn:
                    cursor = conn.execute(
                        "UPDATE QuestionAnswers SET SuggestedScore=NULL, SuggestedJustification=?, EvaluationConfidence=NULL, NeedsGradingReview=1, UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerId=? AND IsApproved=0",
                        (" ".join(result["review_reasons"]), answer["AnswerId"]),
                    )
                    if cursor.rowcount != 1:
                        raise GradingConflictError("The answer was approved while grading was running")
                self.runs.finish(rubric_run, rubric_started, status="REQUIRES_REVIEW", output=result)
                result["answer_sheet_status"] = refresh_answer_sheet_status(
                    self.manager, int(answer["AnswerSheetId"])
                )
                return {**result, "semantic_processing_run_id": semantic_run, "rubric_processing_run_id": rubric_run}

            suggested_score = round(sum(item.awarded_marks for item in suggestions), 2)
            if suggested_score > max_marks + 1e-6:
                raise GradingConfigurationError("Rubric suggestion exceeds the question maximum marks")
            result = {
                "answer_id": int(answer["AnswerId"]),
                "question_number": int(answer["QuestionNumber"]),
                "question_type": answer["QuestionType"],
                "suggested_score": suggested_score,
                "max_marks": max_marks,
                "evaluation_confidence": None,
                "needs_grading_review": True,
                "status": "REQUIRES_REVIEW",
                "method": self.rubric_evaluator.model_name,
                "evaluator_version": self.rubric_evaluator.model_version,
                "semantic_model_configured": bool(self.rubric_evaluator.semantic_model_configured),
                "review_reasons": [
                    "الدرجة اقتراح أولي قائم على تطابق مفردات وصف المعايير فقط.",
                    "لا يوجد نموذج دلالي مدرّب أو مهيأ لفهم إعادة الصياغة والمرادفات.",
                    "يجب على المعلم مراجعة الإجابة والصورة قبل اعتماد الدرجة.",
                ],
                "criteria": [
                    {
                        "criterion_id": item.criterion_id,
                        "title": item.title,
                        "allocated_marks": item.allocated_marks,
                        "awarded_marks": item.awarded_marks,
                        "matched_terms": list(item.matched_terms),
                        "required_terms": list(item.required_terms),
                        "coverage": round(item.coverage, 4),
                        "explanation": item.explanation,
                    }
                    for item in suggestions
                ],
                "final_approval": "NOT_APPROVED",
            }
            with self.manager.connection() as conn:
                conn.execute(
                    "UPDATE AnswerCriterionEvaluations SET IsCurrent=0, UpdatedAt=CURRENT_TIMESTAMP WHERE AnswerId=? AND IsCurrent=1",
                    (answer["AnswerId"],),
                )
                for item in suggestions:
                    conn.execute(
                        """
                        INSERT INTO AnswerCriterionEvaluations (
                            AnswerId, CriterionId, ProcessingRunId, EvaluationMethod,
                            AwardedMarks, EvidenceText, Explanation, Confidence, IsCurrent
                        ) VALUES (?, ?, ?, 'AUTOMATIC', ?, ?, ?, NULL, 1)
                        """,
                        (
                            answer["AnswerId"], item.criterion_id, rubric_run,
                            item.awarded_marks, "، ".join(item.matched_terms), item.explanation,
                        ),
                    )
                cursor = conn.execute(
                    """
                    UPDATE QuestionAnswers
                    SET SuggestedScore=?, SuggestedJustification=?, EvaluationConfidence=NULL,
                        NeedsGradingReview=1, UpdatedAt=CURRENT_TIMESTAMP
                    WHERE AnswerId=? AND IsApproved=0
                    """,
                    (suggested_score, " ".join(result["review_reasons"]), answer["AnswerId"]),
                )
                if cursor.rowcount != 1:
                    raise GradingConflictError("The answer was approved while grading was running")
                conn.execute(
                    """
                    INSERT INTO AuditLogs(EntityName, EntityId, ActionType, NewValue, Details)
                    VALUES ('QuestionAnswers', ?, 'HEURISTIC_RUBRIC_SUGGESTED', ?, ?)
                    """,
                    (str(answer["AnswerId"]), str(suggested_score), json.dumps(result, ensure_ascii=False)),
                )
            self.runs.finish(rubric_run, rubric_started, status="REQUIRES_REVIEW", output=result)
            result["answer_sheet_status"] = refresh_answer_sheet_status(
                self.manager, int(answer["AnswerSheetId"])
            )
            return {**result, "semantic_processing_run_id": semantic_run, "rubric_processing_run_id": rubric_run}
        except Exception as exc:
            if rubric_run is not None and rubric_started is not None:
                self.runs.fail_if_running(rubric_run, rubric_started, exc)
            self.runs.fail_if_running(semantic_run, semantic_started, exc)
            raise


def math_isclose(left: float, right: float, tolerance: float = 0.01) -> bool:
    return abs(float(left) - float(right)) <= tolerance
