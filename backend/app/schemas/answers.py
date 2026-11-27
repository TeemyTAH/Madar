from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnswerRegionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: int = Field(gt=0)
    segment_order: int = Field(default=1, gt=0)
    region_x: float | None = Field(default=None, ge=0, le=1)
    region_y: float | None = Field(default=None, ge=0, le=1)
    region_width: float | None = Field(default=None, gt=0, le=1)
    region_height: float | None = Field(default=None, gt=0, le=1)
