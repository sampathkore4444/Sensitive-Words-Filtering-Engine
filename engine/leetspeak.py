from typing import Dict, List, Optional, Set
from collections import deque
from engine.aho_corasick import AhoCorasick
from models.detection import Detection, DetectionMethod


LEET_MAP: Dict[str, List[str]] = {
    "4": ["a"], "@": ["a"],
    "8": ["b"],
    "(": ["c"], "{": ["c"], "<": ["c"], "[": ["c"],
    "3": ["e"], "&": ["e", "c"],
    "6": ["g"], "9": ["g"],
    "#": ["h"],
    "1": ["l", "i"], "!": ["i"], "|": ["i", "l"],
    "0": ["o"],
    "$": ["s"], "5": ["s"],
    "7": ["t"], "+": ["t"],
    "2": ["z"],
    "%": ["x"],
}


class LeetspeakDecoder:
    def __init__(self, max_expansions: int = 1024):
        self.max_expansions = max_expansions
        self._build_char_set()
        self.leet_ac = AhoCorasick()

    def _build_char_set(self):
        self.leet_chars: Set[str] = set(LEET_MAP.keys())
        self.plain_chars: Set[str] = set()
        for variants in LEET_MAP.values():
            self.plain_chars.update(variants)

    def is_leet_char(self, ch: str) -> bool:
        return ch in self.leet_chars

    def has_leet(self, text: str) -> bool:
        return any(ch in self.leet_chars for ch in text)

    def build(self, patterns: List[str], values: Optional[List] = None):
        self.leet_ac = AhoCorasick()
        for i, pattern in enumerate(patterns):
            val = values[i] if values else pattern
            self.leet_ac.add_word(pattern, val)
        self.leet_ac.build()

    def greedy_decode(self, text: str) -> str:
        result = []
        for ch in text:
            if ch in LEET_MAP:
                result.append(LEET_MAP[ch][0])
            else:
                result.append(ch)
        return "".join(result)

    def decode_all(self, text: str) -> List[str]:
        candidates = [""]
        total = 0
        for ch in text:
            replacements = LEET_MAP.get(ch, [ch])
            new_candidates = []
            for candidate in candidates:
                for r in replacements:
                    new_candidates.append(candidate + r)
                    total += 1
                    if total > self.max_expansions:
                        return self._dedupe(candidates + new_candidates)
            candidates = new_candidates
        return self._dedupe(candidates)

    def _dedupe(self, items: List[str]) -> List[str]:
        seen: Set[str] = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def detect(self, text: str, word_map: dict) -> List[Detection]:
        detections = []
        if not self.has_leet(text):
            return detections

        text_lower = text.lower()
        tokens = self._tokenize(text_lower)

        for token_start, token_end, token_text in tokens:
            if not self.has_leet(token_text):
                continue

            greedy = self.greedy_decode(token_text)
            if self._ac_has_match(greedy):
                matches = self._ac_search(greedy)
                for pattern, m_start, m_end in matches:
                    detections.append(self._make_detection(
                        pattern, word_map,
                        token_start, token_end,
                        token_text
                    ))
                continue

            candidates = self.decode_all(token_text)
            best_match = None
            best_len = float("inf")
            for candidate in candidates:
                if self._ac_has_match(candidate):
                    matches = self._ac_search(candidate)
                    for pattern, _, _ in matches:
                        if len(pattern) < best_len:
                            best_len = len(pattern)
                            best_match = (pattern, candidate)

            if best_match:
                pattern, matched_form = best_match
                detections.append(self._make_detection(
                    pattern, word_map,
                    token_start, token_end,
                    matched_form
                ))

        return detections

    def _tokenize(self, text: str):
        tokens = []
        i = 0
        while i < len(text):
            if text[i].isalnum() or self.is_leet_char(text[i]):
                start = i
                while i < len(text) and (text[i].isalnum() or self.is_leet_char(text[i])):
                    i += 1
                tokens.append((start, i, text[start:i]))
            else:
                i += 1
        return tokens

    def _ac_has_match(self, text: str) -> bool:
        return self.leet_ac.has_match(text)

    def _ac_search(self, text: str):
        return self.leet_ac.search_all(text)

    def _make_detection(self, pattern: str, word_map: dict, token_start: int, token_end: int, matched_text: str) -> Detection:
        base_score = word_map.get(pattern, 0.5) if isinstance(pattern, str) else 0.5
        return Detection(
            word=pattern if isinstance(pattern, str) else str(pattern),
            matched_form=matched_text,
            start=token_start,
            end=token_end,
            base_score=base_score,
            method=DetectionMethod.LEETSPEAK,
            sub_methods=["leetspeak"],
        )
