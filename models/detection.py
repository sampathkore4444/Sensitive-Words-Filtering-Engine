from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from enum import Enum


class DetectionMethod(str, Enum):
    EXACT = "exact"
    SEPARATOR_BYPASS = "separator_bypass"
    LEETSPEAK = "leetspeak"
    HOMOGLYPH = "homoglyph"
    REPETITION = "repetition"
    FUZZY = "fuzzy"


class SeverityTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Detection:
    word: str
    matched_form: str
    start: int
    end: int
    base_score: float
    final_score: float = 0.0
    method: DetectionMethod = DetectionMethod.EXACT
    sub_methods: List[str] = field(default_factory=list)
    homoglyphs_detected: List[Tuple[str, str]] = field(default_factory=list)
    distance: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    tier: SeverityTier = SeverityTier.LOW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "matched_form": self.matched_form,
            "start": self.start,
            "end": self.end,
            "base_score": self.base_score,
            "final_score": self.final_score,
            "method": self.method.value,
            "sub_methods": self.sub_methods,
            "homoglyphs_detected": [[h[0], h[1]] for h in self.homoglyphs_detected],
            "distance": self.distance,
            "tags": self.tags,
            "tier": self.tier.value,
        }


@dataclass
class ReportSummary:
    total_detections: int = 0
    distinct_words: int = 0
    highest_score: float = 0.0
    average_score: float = 0.0
    tier: SeverityTier = SeverityTier.LOW
    action: str = "log"
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_detections": self.total_detections,
            "distinct_words": self.distinct_words,
            "highest_score": self.highest_score,
            "average_score": self.average_score,
            "tier": self.tier.value,
            "action": self.action,
            "processing_time_ms": self.processing_time_ms,
        }


@dataclass
class DetectionReport:
    message_id: str
    timestamp: datetime
    text: str
    normalized_text: Optional[str] = None
    detections: List[Detection] = field(default_factory=list)
    summary: Optional[ReportSummary] = None
    context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "timestamp": self.timestamp.isoformat(),
            "text": self.text,
            "normalized_text": self.normalized_text,
            "detections": [d.to_dict() for d in self.detections],
            "summary": self.summary.to_dict() if self.summary else None,
            "context": self.context,
        }
