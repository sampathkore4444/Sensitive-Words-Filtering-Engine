from typing import List, Optional
from models.detection import Detection, DetectionMethod, SeverityTier
from config import ScoringConfig


class RiskScorer:
    def __init__(self, config: ScoringConfig):
        self.config = config

    def compute(self, detection: Detection, word_count: int = 1, distinct_count: int = 1) -> float:
        raw_score = detection.base_score

        if detection.method == DetectionMethod.SEPARATOR_BYPASS:
            raw_score += 0.2
        elif detection.method == DetectionMethod.LEETSPEAK:
            raw_score += 0.2
        elif detection.method == DetectionMethod.HOMOGLYPH:
            raw_score += 0.1
        elif detection.method == DetectionMethod.REPETITION:
            raw_score += 0.15
        elif detection.method == DetectionMethod.FUZZY:
            raw_score += 0.05 * (detection.distance or 1)

        raw_score = min(1.0, raw_score)

        context_modifier = 1.0
        if word_count > 0:
            context_modifier = min(1.5, 1.0 + (distinct_count / max(1, word_count)))

        final_score = min(1.0, raw_score * context_modifier)
        detection.final_score = final_score
        detection.tier = self._get_tier(final_score)

        return final_score

    def _get_tier(self, score: float) -> SeverityTier:
        for tier_cfg in reversed(self.config.tiers):
            if score >= tier_cfg.threshold and score < 1.0:
                return SeverityTier(tier_cfg.label)
            if score >= 1.0:
                return SeverityTier.CRITICAL
        return SeverityTier.LOW

    def get_action(self, score: float) -> str:
        for tier_cfg in reversed(self.config.tiers):
            if score >= tier_cfg.threshold:
                return tier_cfg.action
        return "log"

    def compute_summary(self, detections: List[Detection], word_count: int) -> dict:
        if not detections:
            return {
                "total_detections": 0,
                "distinct_words": 0,
                "highest_score": 0.0,
                "average_score": 0.0,
                "tier": SeverityTier.LOW.value,
                "action": "log",
            }

        distinct = set(d.word.lower() for d in detections)
        scores = [d.final_score for d in detections]
        highest = max(scores)
        avg = sum(scores) / len(scores)
        tier = self._get_tier(highest)

        return {
            "total_detections": len(detections),
            "distinct_words": len(distinct),
            "highest_score": highest,
            "average_score": round(avg, 4),
            "tier": tier.value,
            "action": self.get_action(highest),
        }
