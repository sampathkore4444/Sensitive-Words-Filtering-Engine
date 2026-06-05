import json
import os
import logging
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime, timedelta
from models.detection import DetectionReport

logger = logging.getLogger(__name__)


class ReportStore:
    def __init__(self, persist_path: Optional[str] = None, retention_days: int = 90,
                 webhook_url: str = ""):
        self._reports: Dict[str, DetectionReport] = {}
        self.persist_path = persist_path
        self.retention_days = retention_days
        self.webhook_url = webhook_url
        self.hooks: List[Callable[[DetectionReport], None]] = []

    def add_hook(self, hook: Callable[[DetectionReport], None]):
        self.hooks.append(hook)

    def save(self, report: DetectionReport):
        self._reports[report.message_id] = report
        self._prune()
        if self.persist_path:
            self._append_to_file(report)
        self._fire_hooks(report)

    def _fire_hooks(self, report: DetectionReport):
        for hook in self.hooks:
            try:
                hook(report)
            except Exception as e:
                logger.warning("Report hook failed: %s", e)

    def get(self, message_id: str) -> Optional[DetectionReport]:
        return self._reports.get(message_id)

    def list_recent(self, limit: int = 100, offset: int = 0) -> List[DetectionReport]:
        sorted_reports = sorted(
            self._reports.values(),
            key=lambda r: r.timestamp,
            reverse=True
        )
        return sorted_reports[offset:offset + limit]

    def list_by_tier(self, tier: str, limit: int = 100) -> List[DetectionReport]:
        return [
            r for r in self._reports.values()
            if r.summary and r.summary.tier.value == tier
        ][:limit]

    def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        recent = [r for r in self._reports.values() if r.timestamp >= cutoff]

        total = len(recent)
        if total == 0:
            return {"total": 0, "detections": 0, "blocked": 0, "flagged": 0}

        total_detections = sum(len(r.detections) for r in recent)
        blocked = sum(1 for r in recent if r.summary and r.summary.action == "block")
        flagged = sum(1 for r in recent if r.summary and r.summary.action == "flag")

        avg_processing = 0.0
        if recent:
            avg_processing = sum(
                r.summary.processing_time_ms for r in recent if r.summary
            ) / total

        top_words = {}
        for r in recent:
            for d in r.detections:
                w = d.word.lower()
                top_words[w] = top_words.get(w, 0) + 1

        top_words_sorted = sorted(top_words.items(), key=lambda x: -x[1])[:10]

        return {
            "total": total,
            "detections": total_detections,
            "blocked": blocked,
            "flagged": flagged,
            "average_processing_time_ms": round(avg_processing, 2),
            "top_words": [{"word": w, "count": c} for w, c in top_words_sorted],
        }

    def delete_older_than(self, days: int):
        cutoff = datetime.utcnow() - timedelta(days=days)
        to_delete = [
            mid for mid, r in self._reports.items()
            if r.timestamp < cutoff
        ]
        for mid in to_delete:
            del self._reports[mid]

    def _prune(self):
        if self.retention_days <= 0:
            return
        self.delete_older_than(self.retention_days)

    def _append_to_file(self, report: DetectionReport):
        if not self.persist_path:
            return
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        with open(self.persist_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
