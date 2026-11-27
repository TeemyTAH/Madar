from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u0621-\u064A\u066E-\u06D3\u06FA-\u06FC]+")
_ARABIC_STOPWORDS = {
    "في", "من", "على", "الى", "إلى", "عن", "أن", "إن", "هو", "هي", "هم", "هن",
    "هذا", "هذه", "ذلك", "تلك", "مع", "ما", "لا", "لم", "لن", "قد", "ثم", "و", "أو",
    "الذي", "التي", "الذين", "اللتي", "كان", "كانت", "يكون", "تكون", "كل", "بعض",
}
_ENGLISH_STOPWORDS = {"the", "a", "an", "is", "are", "of", "to", "in", "on", "and", "or", "for", "with"}


def evidence_tokens(text: str) -> set[str]:
    value = unicodedata.normalize("NFC", str(text or ""))
    value = _ARABIC_DIACRITICS.sub("", value).replace("ـ", "")
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"}))
    tokens = {token.casefold() for token in _TOKEN_RE.findall(value)}
    return {
        token for token in tokens
        if token not in _ARABIC_STOPWORDS and token not in _ENGLISH_STOPWORDS and len(token) > 1
    }


@dataclass(frozen=True)
class CriterionEvidence:
    criterion_id: int
    title: str
    allocated_marks: float
    awarded_marks: float
    matched_terms: tuple[str, ...]
    required_terms: tuple[str, ...]
    coverage: float
    explanation: str


class RubricEvaluator(Protocol):
    """Replaceable evaluator contract for criterion-level scoring."""

    model_name: str
    model_version: str
    semantic_model_configured: bool

    def evaluate(self, answer_text: str, criteria: Sequence[Any]) -> list[CriterionEvidence]: ...


class KeywordEvidenceEvaluator:
    """Transparent lexical baseline; it does not understand paraphrases or synonyms."""

    model_name = "evidence-overlap-heuristic"
    model_version = "1.0.0"
    semantic_model_configured = False

    def evaluate(self, answer_text: str, criteria: Sequence[Any]) -> list[CriterionEvidence]:
        answer_terms = evidence_tokens(answer_text)
        results: list[CriterionEvidence] = []
        for criterion in criteria:
            description = str(criterion["CriterionDescription"] or "").strip()
            required = evidence_tokens(description)
            if not required:
                continue
            matched = sorted(required & answer_terms)
            coverage = len(matched) / len(required)
            allocated = float(criterion["AllocatedMarks"])
            awarded = round(allocated * coverage, 2)
            explanation = (
                f"تغطية مفردات الدليل المحددة: {len(matched)}/{len(required)}. "
                "هذا مؤشر لفظي أولي وليس حكماً على التكافؤ المعنوي."
            )
            results.append(CriterionEvidence(
                criterion_id=int(criterion["CriterionId"]),
                title=str(criterion["CriterionTitle"]),
                allocated_marks=allocated,
                awarded_marks=awarded,
                matched_terms=tuple(matched),
                required_terms=tuple(sorted(required)),
                coverage=coverage,
                explanation=explanation,
            ))
        return results
