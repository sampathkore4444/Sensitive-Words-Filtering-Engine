from collections import deque
from typing import List, Tuple, Optional, Any


class AhoCorasick:
    def __init__(self):
        self.goto: List[dict] = [{}]
        self.fail: List[int] = [0]
        self.output: List[list] = [[]]
        self.built = False
        self.pattern_count = 0

    def add_word(self, keyword: str, value: Any = None) -> None:
        if self.built:
            self.goto = [{}]
            self.fail = [0]
            self.output = [[]]
            self.built = False
            self.pattern_count = 0

        state = 0
        for ch in keyword:
            if ch not in self.goto[state]:
                self.goto[state][ch] = len(self.goto)
                self.goto.append({})
                self.fail.append(0)
                self.output.append([])
            state = self.goto[state][ch]

        self.output[state].append(value if value is not None else keyword)
        self.pattern_count += 1

    def build(self) -> None:
        q = deque()
        for ch, state in self.goto[0].items():
            q.append(state)
            self.fail[state] = 0

        while q:
            r = q.popleft()
            for ch, u in self.goto[r].items():
                q.append(u)
                v = self.fail[r]
                while v and ch not in self.goto[v]:
                    v = self.fail[v]
                self.fail[u] = self.goto[v].get(ch, 0)
                if self.output[self.fail[u]]:
                    self.output[u] = list(set(self.output[u] + self.output[self.fail[u]]))

        self.built = True

    def iter(self, text: str) -> List[Tuple[int, int, Any]]:
        if not self.built:
            self.build()

        results = []
        state = 0

        for i, ch in enumerate(text):
            while state and ch not in self.goto[state]:
                state = self.fail[state]
            state = self.goto[state].get(ch, 0)

            if self.output[state]:
                for val in self.output[state]:
                    pattern_len = len(val) if isinstance(val, str) else 0
                    start = i - pattern_len + 1
                    results.append((start, i, val))

        return results

    def iter_items(self, text: str) -> List[Tuple[int, int, Any]]:
        return self.iter(text)

    def search_all(self, text: str) -> List[Tuple[str, int, int]]:
        matches = self.iter(text)
        return [(value, start, end) for start, end, value in matches]

    def has_match(self, text: str) -> bool:
        if not self.built:
            self.build()

        state = 0
        for ch in text:
            while state and ch not in self.goto[state]:
                state = self.fail[state]
            state = self.goto[state].get(ch, 0)
            if self.output[state]:
                return True
        return False

    def get_pattern_count(self) -> int:
        return self.pattern_count
