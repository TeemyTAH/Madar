from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Request

from backend.app.schemas.answers import AnswerRegionCreate

router = APIRouter(prefix="/answers", tags=["Answers"])


@router.post("/{answer_id}/regions", status_code=201)
def create_answer_region(answer_id: int, payload: AnswerRegionCreate, request: Request):
    """Link one answer to a full page or normalized rectangular page region."""
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized")

    coords = (payload.region_x, payload.region_y, payload.region_width, payload.region_height)
    if not all(value is None for value in coords) and any(value is None for value in coords):
        raise HTTPException(status_code=422, detail="Provide all four region coordinates or leave all four null")
    if all(value is not None for value in coords):
        x, y, width, height = coords
        if x + width > 1 or y + height > 1:
            raise HTTPException(status_code=422, detail="Normalized region must stay within page bounds")

    try:
        with manager.connection() as conn:
            answer = conn.execute(
                "SELECT AnswerSheetId FROM QuestionAnswers WHERE AnswerId=?",
                (answer_id,),
            ).fetchone()
            if answer is None:
                raise HTTPException(status_code=404, detail="Answer not found")
            page = conn.execute(
                "SELECT AnswerSheetId FROM AnswerPages WHERE PageId=?",
                (payload.page_id,),
            ).fetchone()
            if page is None:
                raise HTTPException(status_code=404, detail="Answer page not found")
            if int(page["AnswerSheetId"]) != int(answer["AnswerSheetId"]):
                raise HTTPException(status_code=409, detail="Page and answer must belong to the same answer sheet")
            cursor = conn.execute(
                """
                INSERT INTO QuestionAnswerPages (
                    AnswerId, PageId, SegmentOrder, RegionX, RegionY, RegionWidth, RegionHeight
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (answer_id, payload.page_id, payload.segment_order, *coords),
            )
            segment_id = int(cursor.lastrowid)
        return {
            "status": "created",
            "segment_id": segment_id,
            "answer_id": answer_id,
            "page_id": payload.page_id,
            "segment_order": payload.segment_order,
            "region": {
                "x": payload.region_x,
                "y": payload.region_y,
                "width": payload.region_width,
                "height": payload.region_height,
            },
        }
    except HTTPException:
        raise
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Answer region conflicts with an existing mapping: {exc}") from exc


@router.get("/{answer_id}/regions")
def list_answer_regions(answer_id: int, request: Request):
    manager = getattr(request.app.state, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Database manager is not initialized")
    with manager.connection() as conn:
        exists = conn.execute("SELECT 1 FROM QuestionAnswers WHERE AnswerId=?", (answer_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="Answer not found")
        rows = conn.execute(
            """
            SELECT QAP.AnswerPageSegmentId, QAP.PageId, AP.PageNumber, QAP.SegmentOrder,
                   QAP.RegionX, QAP.RegionY, QAP.RegionWidth, QAP.RegionHeight
            FROM QuestionAnswerPages QAP
            JOIN AnswerPages AP ON AP.PageId=QAP.PageId
            WHERE QAP.AnswerId=?
            ORDER BY AP.PageNumber, QAP.SegmentOrder
            """,
            (answer_id,),
        ).fetchall()
    return {
        "answer_id": answer_id,
        "regions": [dict(row) for row in rows],
        "count": len(rows),
    }
