from __future__ import annotations

from pydantic import BaseModel, Field


class HTRLineResult(BaseModel):
    line_number: int = Field(ge=1)
    text: str
    confidence: float = Field(ge=0, le=1)
    confidence_percent: float = Field(ge=0, le=100)
    needs_review: bool
    box: list[int]
    angle_degrees: float


class HTRRecognitionResponse(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    confidence_percent: float = Field(ge=0, le=100)
    needs_review: bool
    status: str
    line_count: int = Field(ge=0)
    lines: list[dict]
    model_name: str | None = None
    model_version: str | None = None


class GradingResponse(BaseModel):
    answer_id: int
    suggested_score: float | None
    max_marks: float
    needs_grading_review: bool
    status: str | None = None
    final_approval: str = "NOT_APPROVED"
