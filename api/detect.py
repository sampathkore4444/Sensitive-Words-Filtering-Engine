from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from models.detection import DetectionReport
from storage.word_list import WordListStore
from storage.reports import ReportStore
from engine.pipeline import DetectionPipeline
from config import config


router = APIRouter(prefix="/api/v1/detect", tags=["Detection"])


class DetectionOptions(BaseModel):
    fuzzy: Optional[bool] = None
    leetspeak: Optional[bool] = None
    homoglyph: Optional[bool] = None
    separator_bypass: Optional[bool] = None
    repetition: Optional[bool] = None
    max_distance: Optional[int] = None


class DetectionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=config.detection.max_message_length)
    message_id: str = ""
    context: Optional[Dict[str, Any]] = None
    options: Optional[DetectionOptions] = None


class BatchDetectionRequest(BaseModel):
    messages: List[DetectionRequest] = Field(..., max_length=1000)


def get_pipeline() -> DetectionPipeline:
    from main import detection_pipeline
    return detection_pipeline


def get_report_store() -> ReportStore:
    from main import report_store
    return report_store


@router.post("")
async def detect_text(
    req: DetectionRequest,
    pipeline: DetectionPipeline = Depends(get_pipeline),
    reports: ReportStore = Depends(get_report_store),
):
    try:
        opts = req.options.dict(exclude_none=True) if req.options else {}
        report = pipeline.detect(
            text=req.text,
            message_id=req.message_id,
            context=req.context,
            options=opts,
        )
        reports.save(report)
        return report.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch")
async def detect_batch(
    req: BatchDetectionRequest,
    pipeline: DetectionPipeline = Depends(get_pipeline),
    reports: ReportStore = Depends(get_report_store),
):
    results = []
    for msg in req.messages:
        try:
            opts = msg.options.dict(exclude_none=True) if msg.options else {}
            report = pipeline.detect(
                text=msg.text,
                message_id=msg.message_id,
                context=msg.context,
                options=opts,
            )
            reports.save(report)
            results.append(report.to_dict())
        except Exception as e:
            results.append({
                "message_id": msg.message_id,
                "error": str(e),
            })
    return {"results": results, "count": len(results)}


@router.post("/health")
async def detect_health(pipeline: DetectionPipeline = Depends(get_pipeline)):
    report = pipeline.detect("test", message_id="health-check")
    return {
        "status": "ok",
        "patterns_loaded": pipeline.ac.pattern_count,
        "processing_time_ms": report.summary.processing_time_ms if report.summary else 0,
    }
