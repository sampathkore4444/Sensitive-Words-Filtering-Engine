from typing import List, Optional, Tuple
from models.detection import Detection, DetectionMethod


class FuzzyMatcher:
    def __init__(self, max_distance: int = 2, min_word_length: int = 4,
                 distance_ratio: float = 0.25, max_checks: int = 500):
        self.max_distance = max_distance
        self.min_word_length = min_word_length
        self.distance_ratio = distance_ratio
        self.max_checks = max_checks
        self.words: List[str] = []
        self.word_map: dict = {}
        self.length_buckets: dict = {}

    def build(self, words: List[str], word_map: dict):
        self.words = words
        self.word_map = word_map
        self.length_buckets = {}
        for w in words:
            l = len(w)
            if l not in self.length_buckets:
                self.length_buckets[l] = []
            self.length_buckets[l].append(w)

    @staticmethod
    def damerau_levenshtein(a: str, b: str, max_dist: int = 2) -> int:
        len_a, len_b = len(a), len(b)
        if abs(len_a - len_b) > max_dist:
            return max_dist + 1

        if len_a == 0:
            return len_b
        if len_b == 0:
            return len_a

        d = [[0] * (len_b + 1) for _ in range(2)]
        for j in range(len_b + 1):
            d[0][j] = j

        for i in range(1, len_a + 1):
            d[1][0] = i
            min_in_row = i
            for j in range(1, len_b + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                d[1][j] = min(
                    d[0][j] + 1,
                    d[1][j - 1] + 1,
                    d[0][j - 1] + cost,
                )
                if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                    d[1][j] = min(d[1][j], d[0][j - 2] + cost)

                if d[1][j] < min_in_row:
                    min_in_row = d[1][j]

            d[0], d[1] = d[1], [0] * (len_b + 1)

            if min_in_row > max_dist:
                return max_dist + 1

        return d[0][len_b]

    def find_matches(self, text: str, existing_matches: Optional[List[Detection]] = None) -> List[Detection]:
        detections = []
        checks = 0

        existing_words = set()
        if existing_matches:
            existing_words = {d.word.lower() for d in existing_matches}

        tokens = self._tokenize(text.lower())

        for token_start, token_end, token_text in tokens:
            if len(token_text) < self.min_word_length:
                continue
            if token_text in existing_words:
                continue

            candidate_length = len(token_text)
            min_len = candidate_length - self.max_distance
            max_len = candidate_length + self.max_distance
            candidates = []
            for l in range(min_len, max_len + 1):
                candidates.extend(self.length_buckets.get(l, []))

            best_match = None
            best_dist = self.max_distance + 1

            for pattern in candidates:
                if checks >= self.max_checks:
                    return detections
                checks += 1

                dist = self.damerau_levenshtein(
                    token_text, pattern.lower(), self.max_distance
                )
                if dist <= self.max_distance:
                    ratio = dist / max(len(pattern), 1)
                    if ratio <= self.distance_ratio:
                        if dist < best_dist:
                            best_dist = dist
                            best_match = pattern

            if best_match:
                base_score = self.word_map.get(best_match, 0.5)
                detections.append(Detection(
                    word=best_match,
                    matched_form=token_text,
                    start=token_start,
                    end=token_end,
                    base_score=base_score,
                    method=DetectionMethod.FUZZY,
                    sub_methods=["fuzzy"],
                    distance=best_dist,
                ))

        return detections

    def _tokenize(self, text: str):
        tokens = []
        i = 0
        while i < len(text):
            if text[i].isalnum():
                start = i
                while i < len(text) and text[i].isalnum():
                    i += 1
                tokens.append((start, i, text[start:i]))
            else:
                i += 1
        return tokens
