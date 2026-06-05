import re
from typing import List, Optional, Tuple
from engine.aho_corasick import AhoCorasick
from models.detection import Detection, DetectionMethod


class RepetitionNormalizer:
    def __init__(self, collapse_threshold: int = 2):
        self.collapse_threshold = collapse_threshold
        self.rep_ac = AhoCorasick()

    def build(self, patterns: List[str], values: Optional[List] = None):
        self.rep_ac = AhoCorasick()
        collapsed_variants = set()

        for i, pattern in enumerate(patterns):
            val = values[i] if values else pattern
            self.rep_ac.add_word(pattern, val)
            collapsed_variants.add(pattern)

            collapsed_to1 = self._collapse_to_n(pattern, 1)
            if collapsed_to1 != pattern:
                self.rep_ac.add_word(collapsed_to1, val)
                collapsed_variants.add(collapsed_to1)

        self.rep_ac.build()

    def normalize(self, text: str, threshold: int = None) -> str:
        if threshold is None:
            threshold = self.collapse_threshold
        if threshold <= 1:
            return re.sub(r"(.)\1+", r"\1", text)
        pattern = f"(.)\\1{{{threshold},}}"
        return re.sub(pattern, r"\1" * threshold, text)

    def _collapse_to_n(self, text: str, n: int) -> str:
        result = []
        count = 0
        prev = ""
        for ch in text:
            if ch == prev:
                count += 1
                if count <= n:
                    result.append(ch)
            else:
                count = 1
                result.append(ch)
            prev = ch
        return "".join(result)

    def detect(self, text: str, word_map: dict) -> List[Detection]:
        detections = []
        text_lower = text.lower()

        collapsed_to2 = self.normalize(text_lower)
        if collapsed_to2 != text_lower:
            matches = self.rep_ac.search_all(collapsed_to2)
            for pattern, start, end in matches:
                original_start, original_end = self._map_collapsed_positions(
                    text_lower, collapsed_to2, start, end
                )
                base_score = word_map.get(pattern, 0.5)
                detections.append(Detection(
                    word=pattern,
                    matched_form=text_lower[original_start:original_end + 1],
                    start=original_start,
                    end=original_end,
                    base_score=base_score,
                    method=DetectionMethod.REPETITION,
                    sub_methods=["repetition"],
                ))

            collapsed_to1 = self._collapse_to_n(text_lower, 1)
            if collapsed_to1 != collapsed_to2:
                matches1 = self.rep_ac.search_all(collapsed_to1)
                for pattern, start, end in matches1:
                    if not any(d.word == pattern and d.method == DetectionMethod.REPETITION for d in detections):
                        original_start, original_end = self._map_collapsed_positions(
                            text_lower, collapsed_to1, start, end
                        )
                        base_score = word_map.get(pattern, 0.5)
                        detections.append(Detection(
                            word=pattern,
                            matched_form=text_lower[original_start:original_end + 1],
                            start=original_start,
                            end=original_end,
                            base_score=base_score,
                            method=DetectionMethod.REPETITION,
                            sub_methods=["repetition"],
                        ))

        return detections

    def _map_collapsed_positions(self, original: str, collapsed: str,
                                  match_start: int, match_end: int) -> Tuple[int, int]:
        orig_idx = 0
        col_idx = 0

        while col_idx < match_start and orig_idx < len(original):
            if col_idx < len(collapsed) and collapsed[col_idx] == original[orig_idx]:
                col_idx += 1
            orig_idx += 1

        orig_start = orig_idx

        while col_idx <= match_end and orig_idx < len(original):
            if col_idx < len(collapsed) and collapsed[col_idx] == original[orig_idx]:
                col_idx += 1
            orig_idx += 1

        return orig_start, orig_idx - 1
