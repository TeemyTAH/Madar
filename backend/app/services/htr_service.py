from __future__ import annotations

import json
import math
from collections import OrderedDict
from pathlib import Path
from typing import Any

from PIL import Image

from backend.app.database.database_manager import DatabaseManager
from backend.app.services.processing_runs import ProcessingRunTracker, refresh_answer_sheet_status
from ai_engine.htr.engine import ArabicHTREngine


class HTRServiceError(RuntimeError):
    """Base exception for HTR orchestration errors."""


class HTRNotFoundError(HTRServiceError):
    pass


class HTRConflictError(HTRServiceError):
    pass


class HTRInputError(HTRServiceError):
    pass


class HTRService:
    """Connect page/answer image regions to Arabic HTR and persist auditable runs."""

    def __init__(self, manager: DatabaseManager, engine: ArabicHTREngine | Any | None = None) -> None:
        self.manager = manager
        self.engine = engine or ArabicHTREngine()
        self.runs = ProcessingRunTracker(manager)

    def _safe_project_path(self, relative_path: str | None) -> Path:
        if not relative_path:
            raise HTRInputError("No image path is stored for this answer page")
        root = self.manager.base_dir.resolve()
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise HTRInputError("Stored image path escapes the Madar project directory") from exc
        if not path.is_file():
            raise HTRInputError(f"Stored answer image is missing: {relative_path}")
        return path

    @staticmethod
    def _select_image_path(row) -> str:
        processed = row["PreprocessedImagePath"]
        original = row["OriginalImagePath"]
        return processed or original

    def recognize_page(self, page_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            page = conn.execute(
                """
                SELECT P.PageId, P.AnswerSheetId, P.PageNumber, P.OriginalImagePath,
                       P.PreprocessedImagePath, P.ImageQualityStatus
                FROM AnswerPages P WHERE P.PageId=?
                """,
                (page_id,),
            ).fetchone()
        if page is None:
            raise HTRNotFoundError(f"Answer page {page_id} was not found")

        image_path = self._safe_project_path(self._select_image_path(page))
        run_id = self.runs.create(
            answer_sheet_id=int(page["AnswerSheetId"]),
            page_id=int(page["PageId"]),
            stage="HTR",
            model_name=getattr(self.engine, "MODEL_NAME", "ArabicHTR-CTC-ONNX"),
            model_version=getattr(self.engine, "model_version", None),
            input_reference=str(image_path.relative_to(self.manager.base_dir).as_posix()),
        )
        started = self.runs.start(run_id)
        try:
            result = self.engine.recognize_page(image_path)
            review = (
                bool(result.get("needs_review", True))
                or int(result.get("line_count", 0)) == 0
                or not str(result.get("text", "")).strip()
                or page["ImageQualityStatus"] != "VALID"
            )
            result["needs_review"] = review
            result["page_id"] = int(page["PageId"])
            result["page_number"] = int(page["PageNumber"])
            result["image_quality_status"] = page["ImageQualityStatus"]
            self.runs.finish(
                run_id,
                started,
                status="REQUIRES_REVIEW" if review else "SUCCEEDED",
                output=result,
                output_reference=str(image_path.relative_to(self.manager.base_dir).as_posix()),
            )
            return {"processing_run_id": run_id, **result}
        except Exception as exc:
            self.runs.fail_if_running(run_id, started, exc)
            raise

    @staticmethod
    def _crop_region(image: Image.Image, row) -> Image.Image:
        coords = (row["RegionX"], row["RegionY"], row["RegionWidth"], row["RegionHeight"])
        if all(value is None for value in coords):
            return image.copy()
        if any(value is None for value in coords):
            raise HTRInputError("Answer region coordinates are incomplete")
        width, height = image.size
        x, y, w, h = coords
        left = max(0, min(width, math.floor(float(x) * width)))
        top = max(0, min(height, math.floor(float(y) * height)))
        right = max(0, min(width, math.ceil((float(x) + float(w)) * width)))
        bottom = max(0, min(height, math.ceil((float(y) + float(h)) * height)))
        if right <= left or bottom <= top:
            raise HTRInputError("Answer region is empty after converting normalized coordinates")
        return image.crop((left, top, right, bottom))

    def recognize_answer(self, answer_id: int) -> dict[str, Any]:
        with self.manager.connection() as conn:
            answer = conn.execute(
                """
                SELECT QA.AnswerId, QA.AnswerSheetId, QA.IsApproved,
                       Q.QuestionNumber, S.ProcessingStatus
                FROM QuestionAnswers QA
                JOIN Questions Q ON Q.QuestionId=QA.QuestionId
                JOIN AnswerSheets S ON S.AnswerSheetId=QA.AnswerSheetId
                WHERE QA.AnswerId=?
                """,
                (answer_id,),
            ).fetchone()
            segments = conn.execute(
                """
                SELECT QAP.AnswerPageSegmentId, QAP.SegmentOrder,
                       QAP.RegionX, QAP.RegionY, QAP.RegionWidth, QAP.RegionHeight,
                       AP.PageId, AP.PageNumber, AP.OriginalImagePath,
                       AP.PreprocessedImagePath, AP.ImageQualityStatus
                FROM QuestionAnswerPages QAP
                JOIN AnswerPages AP ON AP.PageId=QAP.PageId
                WHERE QAP.AnswerId=?
                ORDER BY AP.PageNumber, QAP.SegmentOrder
                """,
                (answer_id,),
            ).fetchall()

        if answer is None:
            raise HTRNotFoundError(f"Answer {answer_id} was not found")
        if answer["IsApproved"] or answer["ProcessingStatus"] == "FINALLY_APPROVED":
            raise HTRConflictError("This answer sheet has a final approved score; OCR reprocessing is blocked")
        if not segments:
            raise HTRConflictError(
                "No page regions are linked to this answer. Create QuestionAnswerPages mappings before OCR."
            )

        grouped: OrderedDict[int, list[Any]] = OrderedDict()
        for segment in segments:
            grouped.setdefault(int(segment["PageId"]), []).append(segment)

        all_text: list[str] = []
        all_lines: list[dict[str, Any]] = []
        all_confidence: list[float] = []
        page_results: list[dict[str, Any]] = []
        overall_review = False

        for page_id, page_segments in grouped.items():
            first = page_segments[0]
            relative_path = self._select_image_path(first)
            image_path = self._safe_project_path(relative_path)
            run_id = self.runs.create(
                answer_sheet_id=int(answer["AnswerSheetId"]),
                page_id=page_id,
                answer_id=answer_id,
                stage="HTR",
                model_name=getattr(self.engine, "MODEL_NAME", "ArabicHTR-CTC-ONNX"),
                model_version=getattr(self.engine, "model_version", None),
                input_reference=str(image_path.relative_to(self.manager.base_dir).as_posix()),
            )
            started = self.runs.start(run_id)
            try:
                with Image.open(image_path) as opened:
                    source_image = opened.convert("RGB").copy()
                page_texts: list[str] = []
                page_lines: list[dict[str, Any]] = []
                page_confidences: list[float] = []
                page_review = first["ImageQualityStatus"] != "VALID"

                for segment in page_segments:
                    crop = self._crop_region(source_image, segment)
                    is_full_page = all(
                        segment[key] is None
                        for key in ("RegionX", "RegionY", "RegionWidth", "RegionHeight")
                    )
                    result = self.engine.recognize_page(crop, paper=is_full_page)
                    segment_text = str(result.get("text", "") or "").strip()
                    page_texts.append(segment_text)
                    segment_lines = result.get("lines", [])
                    page_review = (
                        page_review
                        or bool(result.get("needs_review", True))
                        or int(result.get("line_count", len(segment_lines))) == 0
                        or not segment_text
                    )
                    for line in segment_lines:
                        line_record = dict(line)
                        line_record["segment_order"] = int(segment["SegmentOrder"])
                        line_record["page_id"] = page_id
                        page_lines.append(line_record)
                        if line.get("confidence") is not None:
                            page_confidences.append(float(line["confidence"]))

                page_text = "\n".join(text for text in page_texts if text).strip()
                page_confidence = min(page_confidences) if page_confidences else 0.0
                page_result = {
                    "page_id": page_id,
                    "page_number": int(first["PageNumber"]),
                    "text": page_text,
                    "lines": page_lines,
                    "confidence": round(page_confidence, 6),
                    "confidence_percent": round(page_confidence * 100, 2),
                    "needs_review": page_review,
                    "image_quality_status": first["ImageQualityStatus"],
                }
                self.runs.finish(
                    run_id,
                    started,
                    status="REQUIRES_REVIEW" if page_review else "SUCCEEDED",
                    output=page_result,
                    output_reference=str(image_path.relative_to(self.manager.base_dir).as_posix()),
                )
                page_results.append({"processing_run_id": run_id, **page_result})
                if page_text:
                    all_text.append(page_text)
                all_lines.extend(page_lines)
                all_confidence.extend(page_confidences)
                overall_review = overall_review or page_review
            except Exception as exc:
                self.runs.fail_if_running(run_id, started, exc)
                raise

        extracted_text = "\n".join(text for text in all_text if text).strip()
        confidence = min(all_confidence) if all_confidence else 0.0
        is_empty = not bool(extracted_text)
        overall_review = overall_review or is_empty
        with self.manager.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE QuestionAnswers
                SET ExtractedText=?, OcrConfidence=?, NeedsOcrReview=?, IsEmptyAnswer=?,
                    UpdatedAt=CURRENT_TIMESTAMP
                WHERE AnswerId=? AND IsApproved=0
                """,
                (extracted_text, round(confidence * 100, 2), int(overall_review), int(is_empty), answer_id),
            )
            if cursor.rowcount != 1:
                raise HTRConflictError("The answer was approved or changed while OCR was running")
            conn.execute(
                """
                INSERT INTO AuditLogs(EntityName, EntityId, ActionType, NewValue, Details)
                VALUES ('QuestionAnswers', ?, 'OCR_TEXT_EXTRACTED', ?, ?)
                """,
                (
                    str(answer_id),
                    f"confidence={round(confidence * 100, 2)};needs_review={int(overall_review)}",
                    json.dumps({"pages_processed": len(page_results), "line_count": len(all_lines)}, ensure_ascii=False),
                ),
            )

        sheet_status = refresh_answer_sheet_status(self.manager, int(answer["AnswerSheetId"]))

        return {
            "answer_id": answer_id,
            "question_number": int(answer["QuestionNumber"]),
            "text": extracted_text,
            "confidence": round(confidence, 6),
            "confidence_percent": round(confidence * 100, 2),
            "needs_review": bool(overall_review),
            "is_empty": is_empty,
            "pages_processed": len(page_results),
            "answer_sheet_status": sheet_status,
            "lines": all_lines,
            "page_results": page_results,
            "review_note": "OCR output is a draft. Verify it against the source image before grading.",
        }
