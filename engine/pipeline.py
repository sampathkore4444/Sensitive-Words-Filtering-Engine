import time
import unicodedata
from typing import List, Optional, Dict, Any
from datetime import datetime
from models.detection import (
    Detection, DetectionReport, ReportSummary, DetectionMethod, SeverityTier
)
from models.word_entry import WordEntry
from config import DetectionConfig
from engine.normalizer import TextNormalizer
from engine.aho_corasick import AhoCorasick
from engine.separator_bypass import SeparatorBypassDetector
from engine.leetspeak import LeetspeakDecoder, LEET_MAP
from engine.repetition import RepetitionNormalizer
from engine.fuzzy import FuzzyMatcher
from engine.scorer import RiskScorer


class DetectionPipeline:
    def __init__(self, config: DetectionConfig):
        self.config = config
        self.normalizer = TextNormalizer(
            homoglyph_enabled=config.homoglyph.enabled
        )
        self.ac = AhoCorasick()
        self.separator_detector = SeparatorBypassDetector(
            separator_chars=config.separator_bypass.separator_chars
        )
        self.leet_decoder = LeetspeakDecoder(
            max_expansions=config.leetspeak.max_expansions
        )
        self.repetition_normalizer = RepetitionNormalizer(
            collapse_threshold=config.repetition.collapse_threshold
        )
        self.fuzzy_matcher = FuzzyMatcher(
            max_distance=config.fuzzy.max_distance,
            min_word_length=config.fuzzy.min_word_length,
            distance_ratio=config.fuzzy.distance_ratio,
            max_checks=config.fuzzy.max_checks_per_message,
        )
        self.scorer = RiskScorer(config=config.scoring)
        self.word_map: Dict[str, float] = {}

    def load_words(self, word_entries: List[WordEntry]):
        self.word_map = {}
        patterns = []
        values = []
        for entry in word_entries:
            if not entry.enabled:
                continue
            word = entry.word.lower()
            self.word_map[word] = entry.base_score
            patterns.append(word)
            values.append(word)

        self.ac = AhoCorasick()
        for w in patterns:
            self.ac.add_word(w, w)
        self.ac.build()

        if self.config.separator_bypass.enabled:
            self.separator_detector.build(patterns, values)

        if self.config.leetspeak.enabled:
            self.leet_decoder.build(patterns, values)

        if self.config.repetition.enabled:
            self.repetition_normalizer.build(patterns, values)

        if self.config.fuzzy.enabled:
            self.fuzzy_matcher.build(patterns, self.word_map)

    def detect(self, text: str, message_id: str = "",
               context: Optional[Dict[str, Any]] = None,
               options: Optional[Dict[str, bool]] = None) -> DetectionReport:
        start_time = time.perf_counter()

        if options is None:
            options = {}

        opts = {
            "fuzzy": options.get("fuzzy", self.config.fuzzy.enabled),
            "leetspeak": options.get("leetspeak", self.config.leetspeak.enabled),
            "homoglyph": options.get("homoglyph", self.config.homoglyph.enabled),
            "separator_bypass": options.get("separator_bypass", self.config.separator_bypass.enabled),
            "repetition": options.get("repetition", self.config.repetition.enabled),
            "max_distance": options.get("max_distance", self.config.fuzzy.max_distance),
        }

        if len(text) > self.config.max_message_length:
            text = text[:self.config.max_message_length]

        normalized = self.normalizer.normalize(text, self.config.case_sensitive)

        all_detections: List[Detection] = []

        stage2_matches = self._stage_2_exact(normalized)
        all_detections.extend(stage2_matches)

        matched_words = {d.word.lower() for d in all_detections}
        total_matched_chars = sum(d.end - d.start for d in all_detections)
        text_coverage = total_matched_chars / max(1, len(normalized))

        if text_coverage < 1.0:
            if opts.get("homoglyph"):
                stage3_matches = self._stage_3_homoglyph(normalized, matched_words)
                all_detections.extend(stage3_matches)
                matched_words.update(d.word.lower() for d in stage3_matches)

            if opts.get("separator_bypass"):
                stage4_matches = self._stage_4_separator(normalized, matched_words)
                all_detections.extend(stage4_matches)
                matched_words.update(d.word.lower() for d in stage4_matches)

            if opts.get("leetspeak"):
                stage5_matches = self._stage_5_leetspeak(normalized, matched_words)
                all_detections.extend(stage5_matches)
                matched_words.update(d.word.lower() for d in stage5_matches)

            if opts.get("repetition"):
                stage6_matches = self._stage_6_repetition(normalized, matched_words)
                all_detections.extend(stage6_matches)
                matched_words.update(d.word.lower() for d in stage6_matches)

            leet_chars = set(LEET_MAP.keys())
            cleaned = self.normalizer.strip_keep_chars(normalized, leet_chars)
            if cleaned != normalized:
                if opts.get("leetspeak"):
                    leet_on_clean = self._stage_5_leetspeak(cleaned, matched_words)
                    all_detections.extend(leet_on_clean)
                    matched_words.update(d.word.lower() for d in leet_on_clean)
                if opts.get("repetition"):
                    rep_on_clean = self._stage_6_repetition(cleaned, matched_words)
                    all_detections.extend(rep_on_clean)
                    matched_words.update(d.word.lower() for d in rep_on_clean)

            if opts.get("fuzzy"):
                stage7_matches = self._stage_7_fuzzy(normalized, all_detections)
                all_detections.extend(stage7_matches)

        all_detections = self._deduplicate(all_detections)

        word_count = len(text.split())
        distinct_words = len(set(d.word.lower() for d in all_detections))

        for d in all_detections:
            self.scorer.compute(d, word_count, distinct_words)

        summary_data = self.scorer.compute_summary(all_detections, word_count)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        summary = ReportSummary(
            total_detections=summary_data["total_detections"],
            distinct_words=summary_data["distinct_words"],
            highest_score=summary_data["highest_score"],
            average_score=summary_data["average_score"],
            tier=SeverityTier(summary_data["tier"]),
            action=summary_data["action"],
            processing_time_ms=round(elapsed_ms, 2),
        )

        return DetectionReport(
            message_id=message_id or str(int(time.time() * 1000)),
            timestamp=datetime.utcnow(),
            text=text,
            normalized_text=normalized,
            detections=all_detections,
            summary=summary,
            context=context,
        )

    def _stage_2_exact(self, text: str) -> List[Detection]:
        detections = []
        matches = self.ac.iter(text)
        for start, end, word in matches:
            detections.append(Detection(
                word=word,
                matched_form=text[start:end + 1],
                start=start,
                end=end + 1,
                base_score=self.word_map.get(word, self.config.default_base_score),
                method=DetectionMethod.EXACT,
            ))
        return detections

    def _stage_3_homoglyph(self, text: str, existing: set) -> List[Detection]:
        detections = []
        replaced_text, homoglyphs = self.normalizer.replace_homoglyphs(text)
        if replaced_text == text:
            return detections

        matches = self.ac.iter(replaced_text)
        for start, end, word in matches:
            if word in existing:
                continue
            relevant_homs = self._find_relevant_homoglyphs(
                text[start:end + 1], replaced_text[start:end + 1], homoglyphs
            )
            detections.append(Detection(
                word=word,
                matched_form=text[start:end + 1],
                start=start,
                end=end + 1,
                base_score=self.word_map.get(word, self.config.default_base_score),
                method=DetectionMethod.HOMOGLYPH,
                sub_methods=["homoglyph"],
                homoglyphs_detected=relevant_homs,
            ))
        return detections

    def _find_relevant_homoglyphs(self, orig_segment: str, replaced_segment: str,
                                   all_homoglyphs: list) -> list:
        relevant = []
        for orig_ch, replaced_ch in all_homoglyphs:
            if orig_ch in orig_segment:
                relevant.append((orig_ch, replaced_ch))
        return relevant

    def _stage_4_separator(self, text: str, existing: set) -> List[Detection]:
        return [
            d for d in self.separator_detector.detect(text, self.word_map)
            if d.word not in existing
        ]

    def _stage_5_leetspeak(self, text: str, existing: set) -> List[Detection]:
        return [
            d for d in self.leet_decoder.detect(text, self.word_map)
            if d.word not in existing
        ]

    def _stage_6_repetition(self, text: str, existing: set) -> List[Detection]:
        return [
            d for d in self.repetition_normalizer.detect(text, self.word_map)
            if d.word not in existing
        ]

    def _stage_7_fuzzy(self, text: str, existing_detections: List[Detection]) -> List[Detection]:
        return self.fuzzy_matcher.find_matches(text, existing_detections)

    def _deduplicate(self, detections: List[Detection]) -> List[Detection]:
        seen = set()
        unique = []
        for d in detections:
            key = (d.word.lower(), d.start, d.end, d.method.value)
            if key not in seen:
                seen.add(key)
                unique.append(d)
        return unique
