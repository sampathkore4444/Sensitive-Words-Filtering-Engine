import re
from typing import List, Optional
from engine.aho_corasick import AhoCorasick
from models.detection import Detection, DetectionMethod


class SeparatorBypassDetector:
    def __init__(self, separator_chars: Optional[List[str]] = None):
        self.separator_chars = separator_chars or [' ', '-', '.', '_', '/', '|', '~', '*', '!']
        sep_pattern = '|'.join(re.escape(c) for c in self.separator_chars)
        self.non_alnum_pattern = re.compile(rf'[^a-zA-Z0-9]')
        self.clean_ac = AhoCorasick()

    def build(self, patterns: List[str], values: Optional[List] = None):
        self.clean_ac = AhoCorasick()
        for i, pattern in enumerate(patterns):
            clean = self.non_alnum_pattern.sub("", pattern)
            val = values[i] if values else pattern
            self.clean_ac.add_word(clean, val)
        self.clean_ac.build()

    def detect(self, text: str, word_map: dict) -> List[Detection]:
        detections = []

        text_lower = text.lower()

        alnum_spans = self._find_alnum_spans(text_lower)
        for span_start, span_end, span_text in alnum_spans:
            clean_text = self.non_alnum_pattern.sub("", span_text)
            for start_offset, end_offset, value in self._scan_clean_text(clean_text):
                original_start = self._map_to_original(span_text, start_offset)
                original_end = self._map_to_original(span_text, end_offset, is_end=True)
                pattern_word = value if isinstance(value, str) else word_map.get(value, value)

                detections.append(Detection(
                    word=pattern_word if isinstance(pattern_word, str) else str(pattern_word),
                    matched_form=text_lower[span_start + original_start:span_start + original_end],
                    start=span_start + original_start,
                    end=span_start + original_end,
                    base_score=word_map.get(pattern_word, 0.5) if isinstance(pattern_word, str) else 0.5,
                    method=DetectionMethod.SEPARATOR_BYPASS,
                    sub_methods=["separator_bypass"],
                ))

        return detections

    def _find_alnum_spans(self, text: str):
        spans = []
        i = 0
        while i < len(text):
            if text[i].isalnum():
                start = i
                while i < len(text) and (text[i].isalnum() or not text[i].isspace()):
                    i += 1
                span_text = text[start:i]
                if any(c.isalpha() for c in span_text):
                    spans.append((start, i, span_text))
            else:
                i += 1
        return spans

    def _scan_clean_text(self, clean_text: str):
        results = []
        state = 0
        for i, ch in enumerate(clean_text):
            while state and ch not in self.clean_ac.goto[state]:
                state = self.clean_ac.fail[state]
            state = self.clean_ac.goto[state].get(ch, 0)
            if self.clean_ac.output[state]:
                for val in self.clean_ac.output[state]:
                    pattern_len = len(val) if isinstance(val, str) else 0
                    start = i - pattern_len + 1
                    results.append((start, i, val))
        return results

    def _map_to_original(self, span_text: str, clean_offset: int, is_end: bool = False) -> int:
        count = 0
        for i, ch in enumerate(span_text):
            if ch.isalnum():
                if count == clean_offset:
                    if is_end:
                        return i + 1
                    return i
                count += 1
        return len(span_text) - 1 if is_end else 0
