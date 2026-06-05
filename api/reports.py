from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from storage.reports import ReportStore


router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


def get_store() -> ReportStore:
    from main import report_store
    return report_store


@router.get("")
async def list_reports(
    page: int = 1,
    page_size: int = 100,
    tier: Optional[str] = None,
    store: ReportStore = Depends(get_store),
):
    if tier:
        reports = store.list_by_tier(tier, limit=page_size)
        offset = (page - 1) * page_size
        return {
            "total": len(reports),
            "page": page,
            "page_size": page_size,
            "reports": [r.to_dict() for r in reports[offset:offset + page_size]],
        }
    offset = (page - 1) * page_size
    reports = store.list_recent(limit=page_size, offset=offset)
    return {
        "total": len(store._reports),
        "page": page,
        "page_size": page_size,
        "reports": [r.to_dict() for r in reports],
    }


@router.get("/export")
async def export_reports(
    format: str = Query("json", regex="^(json)$"),
    store: ReportStore = Depends(get_store),
):
    reports = [r.to_dict() for r in store.list_recent(limit=10000)]
    if format == "json":
        import json
        content = json.dumps(reports, ensure_ascii=False, indent=2, default=str)
        return PlainTextResponse(content, media_type="application/json",
                                 headers={"Content-Disposition": "attachment; filename=reports.json"})


@router.get("/stats")
async def get_stats(hours: int = 24, store: ReportStore = Depends(get_store)):
    return store.get_stats(hours=hours)


@router.get("/{message_id}")
async def get_report(message_id: str, store: ReportStore = Depends(get_store)):
    report = store.get(message_id)
    if not report:
        return {"error": "Report not found"}
    return report.to_dict()


@router.delete("/older-than/{days}")
async def purge_old(days: int, store: ReportStore = Depends(get_store)):
    store.delete_older_than(days)
    return {"purged_older_than_days": days}
