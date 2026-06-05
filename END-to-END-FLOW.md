# End-to-End Flow — Sensitive Words Filteration Platform

> A complete walkthrough covering architecture, detection pipeline, frontend-backend communication, API contracts, and server operations.

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [System Architecture](#2-system-architecture)
3. [End-to-End Data Flow](#3-end-to-end-data-flow)
4. [Detection Pipeline — Phase by Phase](#4-detection-pipeline--phase-by-phase)
5. [How Each Feature Works](#5-how-each-feature-works)
6. [Frontend-Backend Communication](#6-frontend-backend-communication)
7. [API Contracts — Complete Reference](#7-api-contracts--complete-reference)
8. [Server Management](#8-server-management)
9. [Appendix — Edge Cases & Behavior](#9-appendix--edge-cases--behavior)

---

## 1. Platform Overview

The **Sensitive Words Filteration Platform** is a real-time content moderation engine. It accepts text input, scans it against a configurable list of sensitive words using 7 progressive detection stages, assigns a risk score, and returns a structured detection report.

```
Input Text ──▶ Normalization ──▶ Detection Pipeline ──▶ Scoring ──▶ Report
                    │                    │                   │            │
               NFKC Unicode       7 detection stages     Risk score    JSON response
               Homoglyph Repl     (fast → slow)          + tier        + webhook
```

### 1.1 Core Capabilities

| Capability | What it detects | Example |
|------------|----------------|---------|
| **Exact match** | Literal sensitive word | `anal` → match |
| **Separator bypass** | Characters separated by non-alnum delimiters | `a-n-a-l`, `a n a l` |
| **Leetspeak** | Leet/numeric substitutions | `4n4l`, `@n@l` |
| **Repetition** | Repeated characters | `annnnal` |
| **Unicode normalization** | NFKC equivalence | `ＡＮＡＬ` (fullwidth) |
| **Homoglyph** | Visually similar Unicode chars | Cyrillic `а` instead of Latin `a` |
| **Fuzzy** | Small edit distance variations | `anxl`, `anql` |
| **Combined** | Multiple obfuscations at once | `4-n-4-l`, `@-n-@-l` |

### 1.2 Risk Tiers

| Score Range | Label | Action | Meaning |
|-------------|-------|--------|---------|
| 0.0 – 0.3 | Low | `log` | Log only, no action needed |
| 0.3 – 0.6 | Medium | `flag` | Flag for human review |
| 0.6 – 0.8 | High | `warn` | Warn user, notify moderator |
| 0.8 – 1.0 | Critical | `block` | Block message, auto-moderation |

The score is computed as:
```
raw_score         = min(1.0, base_score + obfuscation_penalty + homoglyph_penalty + repetition_penalty + distance_penalty)
context_modifier  = min(1.5, 1.0 + distinct_sensitive_words / total_words)
final_score       = min(1.0, raw_score × context_modifier)
```

Penalties: separator_bypass/leetspeak +0.2, homoglyph +0.1, repetition +0.15, fuzzy +0.05 per unit distance.

**Example:** A word with base_score=0.8 detected via separator bypass in a 5-word message with 1 distinct match:
```
raw = min(1.0, 0.8 + 0.2) = 1.0
modifier = min(1.5, 1.0 + 1/5) = 1.2
final = min(1.0, 1.0 × 1.2) = 1.0 → CRITICAL → block
```

---

## 2. System Architecture

### 2.1 Module Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (main.py)                      │
│                                                                     │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │   API Layer   │  │  Detection Engine │  │     Storage Layer    │  │
│  │              │  │                  │  │                      │  │
│  │ /detect      │  │  Pipeline        │  │  WordListStore       │  │
│  │ /words       │──│→  Normalizer     │──│→  (in-memory + JSON) │  │
│  │ /reports     │  │  Aho-Corasick    │  │  ReportStore         │  │
│  │ /health      │  │  SeparatorBypass │  │  (in-memory + JSONL) │  │
│  └──────────────┘  │  Leetspeak       │  └──────────────────────┘  │
│                    │  Repetition      │                            │
│                    │  Fuzzy           │  ┌──────────────────────┐  │
│                    │  Scorer          │  │   Webhook Dispatch   │  │
│                    └──────────────────┘  │   (optional HTTP POST)│  │
│                                          └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 File Layout

```
project_root/
├── main.py                 # FastAPI app, global state, webhook, startup
├── config.py               # Dataclass-based config, YAML loading
├── config.yaml             # User-editable settings
├── requirements.txt        # Python dependencies
├── engine/
│   ├── __init__.py         # Re-exports all engine classes
│   ├── normalizer.py       # NFKC normalize, homoglyph replace, strip helpers
│   ├── aho_corasick.py     # Pure Python Aho-Corasick DFA
│   ├── separator_bypass.py # Strip non-alnum separators, AC rescan
│   ├── leetspeak.py        # Greedy + BFS leet decoder, leet tokenizer
│   ├── repetition.py       # Collapse repeated chars to threshold
│   ├── fuzzy.py            # Damerau-Levenshtein with length bucketing
│   ├── scorer.py           # Score computation, tier mapping, summary
│   └── pipeline.py         # Orchestrator: stages 1–7 + combined pass
├── models/
│   ├── __init__.py
│   ├── word_entry.py       # WordEntry dataclass
│   └── detection.py        # Detection, DetectionReport, ReportSummary, enums
├── api/
│   ├── __init__.py
│   ├── detect.py           # POST /api/v1/detect, /detect/batch, /detect/health
│   ├── words.py            # CRUD /api/v1/words, file upload
│   └── reports.py          # GET /api/v1/reports, /export, /stats
├── storage/
│   ├── __init__.py
│   ├── word_list.py        # In-memory + JSON file persistence
│   └── reports.py          # In-memory + JSONL file + webhook hooks
└── data/
    ├── sensitive_words.txt  # Default word list (plain text)
    ├── word_list.json       # Auto-persisted word list (JSON)
    └── reports.jsonl        # Auto-persisted reports (JSON Lines)
```

---

## 3. End-to-End Data Flow

### 3.1 Complete Request Lifecycle

```
User/Frontend                     Server                         Detection Engine
     │                              │                                │
     │  POST /api/v1/detect         │                                │
     │  {"text": "a-n-a-l", ...}    │                                │
     │─────────────────────────────▶│                                │
     │                              │  ┌─────────────────────────┐   │
     │                              │  │ 1. Validate input       │   │
     │                              │  │ 2. Truncate to 10K     │   │
     │                              │  │ 3. Call pipeline.detect()│   │
     │                              │  └──────────┬──────────────┘   │
     │                              │             │                   │
     │                              │             │ pipeline.detect() │
     │                              │─────────────┼─────────────────▶│
     │                              │             │                   │
     │                              │             │  Stage 1: NFKC    │
     │                              │             │  "a-n-a-l" unchanged│
     │                              │             │                   │
     │                              │             │  Stage 2: AC      │
     │                              │             │  no exact match   │
     │                              │             │  coverage=0/7     │
     │                              │             │                   │
     │                              │             │  Stage 3: Homo    │
     │                              │             │  no change        │
     │                              │             │                   │
     │                              │             │  Stage 4: Sep     │
     │                              │             │  strip→"anal"    │
     │                              │             │  AC→FOUND!       │
     │                              │             │                   │
     │                              │             │  Stage 7: Fuzzy   │
     │                              │             │  (already matched) │
     │                              │             │                   │
     │                              │             │  Scorer:          │
     │                              │             │  0.8+0.2=1.0      │
     │                              │             │  →critical→block  │
     │                              │             │                   │
     │                              │  ◀──────────┼─────────────────│
     │                              │  return Report                  │
     │  ◀───────────────────────────│                                │
     │                              │                                │
     │                              │  ┌─────────────────────────┐   │
     │                              │  │ 4. Save to ReportStore  │   │
     │                              │  │ 5. Fire webhook (opt)   │   │
     │                              │  └─────────────────────────┘   │
```

### 3.2 Internal Pipeline Flow (Detailed)

```
detect(text, message_id, context, options)
│
├── 1. NFKC Normalize
│      text = unicodedata.normalize("NFKC", text).lower()
│
├── 2. Aho-Corasick Exact Match
│      matches = ac.iter(text)  ← O(n) scan
│      for each (start, end, word): create Detection(word, method=exact)
│      if coverage == 100% → skip stages 3-7 (short-circuit)
│
├── 3. Homoglyph Replacement + AC Rescan
│      replaced, homoglyphs = normalizer.replace_homoglyphs(text)
│      if replaced != text:
│          matches = ac.iter(replaced)
│          for each match: create Detection(word, method=homoglyph, homoglyphs_detected)
│
├── 4. Separator Bypass
│      for each alnum-or-leet span in text:
│          clean = strip non-alnum chars
│          matches = clean_ac.iter(clean)
│          map positions back to original text
│          create Detection(word, method=separator_bypass)
│
├── 5. Leetspeak Decoder
│      for each alnum-or-leet token:
│          if has_leet(token):
│              greedy = greedy_decode(token)  → e.g., "4n4l" → "anal"
│              if ac_has_match(greedy) → DONE
│              else: bfs_decode(token, max_expansions=1024)
│              create Detection(word, method=leetspeak)
│
├── 6. Repetition Normalization
│      collapsed = collapse_repeated(text, threshold=2)  → "annnnal" → "annal"
│      also try collapse_to_1: "annnnal" → "anal"
│      matches = rep_ac.iter(collapsed)
│      create Detection(word, method=repetition)
│
├── 6b. Combined Pass (strip non-alnum/non-leet + rerun leetspeak & repetition)
│      leet_chars = set(LEET_MAP.keys())
│      cleaned = strip_keep_chars(text, keep=leet_chars)
│      if cleaned != text:
│          rerun leetspeak and repetition on cleaned
│          (handles "4-n-4-l" → "4n4l" → leetspeak → "anal")
│
├── 7. Fuzzy Matching
│      for each unmatched alnum token (length >= 4):
│          bucket by length, compare against patterns of similar length
│          damerau_levenshtein(token, pattern, max_dist=2)
│          if distance <= 2 AND distance/len(pattern) <= 0.25:
│              create Detection(word, method=fuzzy, distance)
│
├── 8. Deduplicate
│      remove duplicates by (word.lower, start, end, method)
│
├── 9. Risk Scoring
│      for each detection:
│          final_score = scorer.compute(detection, word_count, distinct_count)
│
├── 10. Build Report
│       DetectionReport {
│           message_id, timestamp, text, normalized_text,
│           detections: [...],
│           summary: { total_detections, highest_score, tier, action, processing_time_ms }
│       }
│
└── 11. Save & Dispatch
        report_store.save(report)      → appends to JSONL
        webhook_hook(report)           → POST to configured URL (async)
```

---

## 4. Detection Pipeline — Phase by Phase

### Phase 1: Unicode Normalization (Always Runs)

**Module:** `engine/normalizer.py` — `TextNormalizer.normalize()`

**Purpose:** Normalize Unicode characters that have multiple representations.

**Algorithm:**
```python
def normalize(text, case_sensitive=False):
    result = unicodedata.normalize("NFKC", text)
    if not case_sensitive:
        result = result.lower()
    return result
```

**Input/Output examples:**

| Input | Output | Why |
|-------|--------|-----|
| `héllo` | `héllo` | Accented chars preserved (NFC form) |
| `ﬁ` (ligature fi) | `fi` | Compatibility decomposition |
| `²` (superscript 2) | `2` | Compatibility decomposition |
| `Ａ` (fullwidth A) | `a` | Fullwidth → halfwidth + lowercase |
| `ＣＡＳＥ` (fullwidth) | `case` | All fullwidth → ASCII |

**Edge cases:**
- Empty string → empty string
- Already normalized → no change
- CJK characters → unchanged (Han ideographs not affected by NFKC in a meaningful way)
- Surrogate pairs → preserved

---

### Phase 2: Aho-Corasick Exact Matching (Always Runs)

**Module:** `engine/aho_corasick.py` — `AhoCorasick`

**Purpose:** Find ALL sensitive words in the text simultaneously in O(n) time, regardless of position.

**Data structure:** A trie with failure links → Deterministic Finite Automaton (DFA).

**Build process:**
```
Insert patterns: ["anal", "fuck", "drugs"]

Root state 0
├── 'a' → state 1 (output: [])
│   └── 'n' → state 2 (output: [])
│       └── 'a' → state 3 (output: [])
│           └── 'l' → state 4 (output: ["anal"])
├── 'f' → state 5 (output: [])
│   └── 'u' → state 6 (output: [])
│       └── 'c' → state 7 (output: [])
│           └── 'k' → state 8 (output: ["fuck"])
└── 'd' → state 9 (output: [])
    └── 'r' → state 10 (output: [])
        └── 'u' → state 11 (output: [])
            └── 'g' → state 12 (output: [])
                └── 's' → state 13 (output: ["drugs"])
```

**Failure links** are built using BFS. Each state points to the longest proper suffix that is also a prefix of some pattern. This enables skipping characters when no match is possible.

**Scan process:**
```
text = "this is anal"
state = 0
i=0: 't' → no transition, stay at 0
     (wait for a known starting character)
i=8: 'a' → goto[0]['a'] = 1
i=9: 'n' → goto[1]['n'] = 2
i=10: 'a' → goto[2]['a'] = 3
i=11: 'l' → goto[3]['l'] = 4, output[4] = ["anal"]
      → EMIT match "anal" at (8, 11)
```

**Edge cases:**
- Overlapping patterns: `anal` and `analysis` → both detected
- Pattern as substring: `"fuck" in "fucking"` → detected at correct position
- No match: returns empty list

---

### Phase 3: Homoglyph Detection (Conditional)

**Module:** `engine/normalizer.py` — `TextNormalizer.replace_homoglyphs()`

**Purpose:** Detect characters that look like Latin letters but are from different Unicode blocks (Cyrillic, Greek, etc.).

**Homoglyph Map** (150+ entries in `HOMOGLYPH_MAP`):
```python
'\u0430': 'a',   # Cyrillic small letter 'а'
'\u03b1': 'a',   # Greek small letter 'α'
'\u0441': 'c',   # Cyrillic small letter 'с'
'\u03b5': 'e',   # Greek small letter 'ε'
'\u03bf': 'o',   # Greek small letter 'ο'
'\u0445': 'x',   # Cyrillic small letter 'х'
"0": "o",        # Digit zero
"1": "l",        # Digit one
# ...150+ more mappings
```

**Algorithm:**
```python
def replace_homoglyphs(text):
    result = []
    homoglyphs = []
    for ch in text:
        mapped = HOMOGLYPH_MAP.get(ch)
        if mapped is not None and mapped != ch.lower():
            result.append(mapped)
            homoglyphs.append((ch, mapped))  # (original → replacement)
        else:
            result.append(ch)
    return "".join(result), homoglyphs
```

**Input/Output examples:**

| Input | After replacement | Homoglyphs detected |
|-------|------------------|-------------------|
| `аnаl` (Cyrillic а) | `anal` | `(а, a), (а, a)` |
| `αναλ` (Greek) | `anal` | `(α, a)` |
| `sсhооl` (Cyrillic с, о) | `school` | `(с, c), (о, o), (о, o)` |
| `0r4ng3` | `or4ng3` | `(0, o)` (digit 0 → letter o) |

**Note:** The replaced text still contains leet chars (`4`, `3`). The AC scan on the replaced text catches homoglyph-based obfuscation. Leet chars are handled in Phase 5.

**Edge cases:**
- Character maps to itself → no-op
- CJK characters → no mapping, unchanged
- Emoji → not in map, unchanged

---

### Phase 4: Separator Bypass (Conditional)

**Module:** `engine/separator_bypass.py` — `SeparatorBypassDetector`

**Purpose:** Detect words where characters are deliberately separated by non-alphanumeric characters.

**Algorithm in detail:**

1. **Find alnum spans** — Locate all contiguous sequences of alphanumeric-or-leet characters:
   ```python
   # For text "check a-n-a-l out"
   # Spans found:
   #   (0, 5): "check"
   #   (6, 13): "a-n-a-l"
   #   (14, 17): "out"
   ```

2. **Strip non-alnum** from each span:
   ```python
   "a-n-a-l" → "anal"
   ```

3. **AC scan** on the cleaned text:
   ```python
   ac.iter("anal") → [(0, 3, "anal")]
   ```

4. **Map positions** back to the original text:
   ```python
   clean_offset=0 → original char 'a' at span position 0 → global position 6
   clean_offset=3 → original char 'l' at span position 6 → global position 12
   # Detection: word="anal", start=6, end=13, method="separator_bypass"
   ```

**Separator characters** (configurable in `config.yaml`):
```
' ', '-', '.', '_', '/', '|', '~', '*', '!'
```

**Input/Output examples:**

| Input | Cleaned | Detected? |
|-------|---------|-----------|
| `a-n-a-l` | `anal` | ✅ Yes |
| `a n a l` | `anal` | ✅ Yes |
| `a!!!n!!!a!!!l` | `anal` | ✅ Yes |
| `a-n-a-l-y-s-i-s` | `analysis` | ✅ Yes (if "analysis" is in word list) |
| `hello` | `hello` | ❌ No (no separators) |

**Edge cases:**
- Leading/trailing separators → ignored: `--a-n-a-l--` → `anal` ✅
- Only separators → no span → no scan
- Mixed with leet → cleaned text still contains leet → passed to Phase 5/6 in combined pass

---

### Phase 5: Leetspeak Decoder (Conditional)

**Module:** `engine/leetspeak.py` — `LeetspeakDecoder`

**Purpose:** Decode leet (1337) speak substitutions back to plain text.

**Leet Map** (20 entries):
```python
LEET_MAP = {
    "4": ["a"],    "@": ["a"],
    "8": ["b"],
    "(": ["c"],   "{": ["c"],   "<": ["c"],   "[": ["c"],
    "3": ["e"],   "&": ["e", "c"],
    "6": ["g"],   "9": ["g"],
    "#": ["h"],
    "1": ["l", "i"],   "!": ["i"],   "|": ["i", "l"],
    "0": ["o"],
    "$": ["s"],   "5": ["s"],
    "7": ["t"],   "+": ["t"],
    "2": ["z"],
    "%": ["x"],
}
```

**Tokenization** — The decoder uses a custom tokenizer that keeps both alphanumeric AND leet characters as a single token:
```python
# "check @n@l" → tokens: ["check", "@n@l"]
# Previously: only alnum → ["check", "n", "l"] (BROKEN for @n@l)
```

**Decoding algorithm (two strategies):**

**Strategy 1 — Greedy** (fast path):
```python
greedy_decode("@n@l") → for each char:
    "@" → "a"    (first replacement in LEET_MAP["@"])
    "n" → "n"    (not in leet map)
    "@" → "a"
    "l" → "l"
    = "anal"
```

**Strategy 2 — BFS** (fallback, bounded):
```python
decode_all("4n4l", max_expansions=1024):
    candidates = [""]
    for '4': → ["a"]                       (LEET_MAP["4"] = ["a"])
    for 'n': → ["an"]                      (not leet)
    for '4': → ["ana"]                     (LEET_MAP["4"] = ["a"])
    for 'l': → ["anal"]                    (not leet)
    Result: ["anal"]
```

For ambiguous cases (e.g., `"1"` can be `"l"` or `"i"`):
```python
"4n4l" → ["anal"]  (straightforward)
"l" → ["l", "i"]   (ambiguous, both checked against AC)
```

**Input/Output examples:**

| Input | Greedy decode | AC match? | Detected? |
|-------|--------------|-----------|-----------|
| `4n4l` | `anal` | ✅ Yes | ✅ |
| `@n@l` | `anal` | ✅ Yes | ✅ |
| `4-ss-w0rd` | `a-ss-w0rd` → AC fails → BFS: `password` | ✅ Yes | ✅ |
| `h3ll0` | `hello` | ✅ Yes | ✅ |
| `1337` | `le37` → AC fails → BFS: `leet` | 🔶 If "leet" is in list | 🔶 |

**Edge cases:**
- No leet chars → skipped immediately (fast path)
- Mixed leet + plain → `h3ll0` correctly decoded to `hello`
- All digits → `8008135` → `boobies` works with BFS (expansions bounded)
- Case-insensitive: input lowercased before processing

---

### Phase 6: Repetition Normalization (Conditional)

**Module:** `engine/repetition.py` — `RepetitionNormalizer`

**Purpose:** Detect words with characters repeated beyond normal length.

**Algorithm:**

1. **Collapse to threshold=2:**
   ```
   "annnnal" → re.sub(r"(.)\2{2,}", r"\1\1", text)
   → "annal"  (3 'n's → 2 'n's)
   ```

2. **Also try collapse to 1:**
   ```
   "annnnal" → re.sub(r"(.)\1+", r"\1", text)
   → "anal"   (all runs → single char)
   ```

3. **AC scan** on both collapsed forms.
4. **Map positions** back to original text using a pointer walk.

**Input/Output examples:**

| Input | Collapsed (t=2) | Collapsed (t=1) | Match? |
|-------|-----------------|-----------------|--------|
| `annnnal` | `annal` | `anal` | ✅ `anal` |
| `fuuuuck` | `fuuck` | `fuck` | ✅ `fuck` |
| `drrugs` | `drugs` (already ≤2) | `drugs` | ✅ `drugs` |
| `aaaaaal` | `aaal` | `al` | ❌ (not in list) |
| `hello` | `hello` | `helo` | ❌ (not in list) |

**Edge cases:**
- No repetitions → no collapse → no scan (fast skip)
- Single character collapse (t=1) caught first → no need for t=2 check
- Different chars repeating → `aabb` stays `aabb` (each run collapsed independently)

---

### Phase 6b: Combined Obfuscation Pass

**Module:** `engine/pipeline.py` — combined stage after stage 6

**Purpose:** Handle the intersection of separator bypases and leetspeak/repetition, like `4-n-4-l`.

**Algorithm:**
```python
leet_chars = set(LEET_MAP.keys())   # {"4", "@", "3", "(", ...}
# Keep only alnum chars AND leet chars
cleaned = "".join(c for c in text if c.isalnum() or c in leet_chars)
# Then rerun leetspeak and repetition on the cleaned text
```

**Input/Output examples:**

| Input | Keep alnum+leet | After leetspeak | Match? |
|-------|----------------|-----------------|--------|
| `4-n-4-l` | `4n4l` | `anal` | ✅ |
| `@-n-@-l` | `@n@l` | `anal` | ✅ |
| `4-n-n-n-4-l` | `4nnn4l` | `annal` (leet) → `anal` (repetition) | ✅ |

**Why this is needed:** The separator bypass stage strips ALL non-alnum (including leet chars), so `4-n-4-l` becomes just `4n4l`. The clean AC only has `anal` (non-leet version), so `4n4l` ≠ `anal`. The leetspeak stage runs on the original text, where `4-n-4-l` is split into tokens `4`, `n`, `4`, `l` (by the alnum-only tokenizer). This combined pass bridges the gap.

---

### Phase 7: Fuzzy Matching (Conditional, Slowest)

**Module:** `engine/fuzzy.py` — `FuzzyMatcher`

**Purpose:** Detect words that are similar (but not equal) to sensitive words via Damerau-Levenshtein distance.

**Algorithm:**

1. **Tokenize** the text into alnum tokens.
2. **Filter** tokens shorter than `min_word_length=4` — these are too short for meaningful fuzzy matching.
3. **Filter** tokens already matched in previous stages — avoid redundant work.
4. **Length-bucket** sensitive words:
   ```python
   length_buckets = {
       4: ["anal", "fuck", "drug", "kill", "bomb"],
       5: ["drugs", "bombs", "kills"],
       6: ["murder", "heroin"],
       ...
   }
   ```
5. **For each candidate token** of length L:
   - Check only patterns with length in `[L-2, L+2]` (bounded by max_distance)
   - Compute Damerau-Levenshtein distance using a 2-row DP matrix
   - Early termination: if `abs(len(a) - len(b)) > max_dist` → skip
   - Early termination: if all values in current DP row > max_dist → skip

6. **Accept if:** `distance <= max_distance` AND `distance / len(pattern) <= distance_ratio`

**Damerau-Levenshtein** supports 4 operations:
- Insertion: `anal` → `anxal` (cost 1)
- Deletion: `anal` → `ana` (cost 1)
- Substitution: `anal` → `anxl` (cost 1)
- Transposition: `anal` → `anla` (cost 1)

**Input/Output examples:**

| Input | Compared against | Distance | Ratio | Accepted? |
|-------|-----------------|----------|-------|-----------|
| `anxl` | `anal` | 1 (x≠a) | 1/4=0.25 | ✅ Yes |
| `anql` | `anal` | 1 (q≠a) | 0.25 | ✅ Yes |
| `annl` | `anal` | 1 (n→a) | 0.25 | ✅ Yes |
| `xyz` | `anal` | 4 | 1.0 | ❌ No (dist>2) |
| `analyze` | `anal` | 3 | 0.75 | ❌ No (dist>2) |
| `abcd` | anything | varies | varies | ❌ No distance_ratio > 0.25 |

**Performance bounding:** Max 500 fuzzy checks per message (`max_checks_per_message`). Once exceeded, remaining tokens are skipped.

**Edge cases:**
- Token matches an existing detection → skipped (already handled)
- Very short words (<4 chars) → skipped
- No sensitive words of similar length → skipped quickly via length check

---

### Phase 8: Risk Scoring

**Module:** `engine/scorer.py` — `RiskScorer`

**Purpose:** Convert a raw detection into a meaningful severity score.

**Complete formula with all penalties:**

```python
def compute(detection, word_count, distinct_count):
    # Base score from the word's configuration
    score = detection.base_score                    # e.g., 0.8

    # Detection method penalties
    if method == SEPARATOR_BYPASS:    score += 0.20
    if method == LEETSPEAK:           score += 0.20
    if method == HOMOGLYPH:           score += 0.10
    if method == REPETITION:          score += 0.15
    if method == FUZZY:               score += 0.05 * detection.distance

    # Clamp to [0.0, 1.0]
    raw_score = min(1.0, score)

    # Context modifier: more distinct hits in shorter text → higher score
    modifier = 1.0 + (distinct_count / max(1, word_count))
    modifier = min(1.5, modifier)

    # Final score
    final = min(1.0, raw_score * modifier)
    return final
```

**Score walkthroughs:**

| Scenario | base | penalty | raw | distinct/total | modifier | final | tier | action |
|----------|------|---------|-----|---------------|----------|-------|------|--------|
| Exact "anal" in 10-word msg | 0.8 | +0 | 0.8 | 1/10=0.1 | 1.1 | 0.88 | critical | block |
| Separator "a-n-a-l" in 6-word msg | 0.8 | +0.2 | 1.0 | 1/6=0.17 | 1.17 | 1.0 | critical | block |
| Leet "4n4l" in 5-word msg | 0.8 | +0.2 | 1.0 | 1/5=0.2 | 1.2 | 1.0 | critical | block |
| Fuzzy "anxl" in 8-word msg | 0.8 | +0.05 | 0.85 | 1/8=0.125 | 1.125 | 0.96 | critical | block |
| Homoglyph "аnаl" in 20-word msg | 0.8 | +0.1 | 0.9 | 1/20=0.05 | 1.05 | 0.95 | critical | block |
| Repetition "annnnal" in 12-word msg | 0.8 | +0.15 | 0.95 | 1/12=0.08 | 1.08 | 1.0 | critical | block |
| Exact "drugs" (base=0.7) in 50-word msg | 0.7 | +0 | 0.7 | 1/50=0.02 | 1.02 | 0.71 | high | warn |
| Fuzzy "drvgs" (dist=1) in 10-word msg | 0.7 | +0.05 | 0.75 | 1/10=0.1 | 1.1 | 0.83 | critical | block |
| Two hits: "fuck"+"anal" in 10-word msg | 0.9+0.8 | +0 | 0.9(highest) | 2/10=0.2 | 1.2 | 1.0 | critical | block |

---

## 5. How Each Feature Works

### 5.1 Exact Matching — `engine/aho_corasick.py`

```
Build:   Insert words into trie → BFS to compute failure links → ready
Scan:    Walk text char by char → follow goto/fail transitions → emit matches
Output:  List of (start_index, end_index, matched_word)
```

**Time complexity:** O(n + m) where n = text length, m = total matches.

### 5.2 Separator Bypass — `engine/separator_bypass.py`

```
1. Find all spans of [alnum | leet-char] in the text
2. For each span:
   a. Remove all non-[alnum] characters
   b. Run AC on the cleaned span
   c. If match found, map positions back to original text
```

**Built-in AC automaton:** Built with patterns stripped of separators. So if "anal" is in the word list, the bypass AC has "anal" (stripped version = same for non-leet words). This means the bypass AC matches the clean word, not the obfuscated form.

### 5.3 Leetspeak — `engine/leetspeak.py`

```
1. Tokenize text into [alnum | leet-char] spans
2. For each token containing leet chars:
   a. Greedy decode (pick first replacement for each leet char)
   b. Check AC match
   c. If no match, BFS decode all possible forms (bounded)
   d. Check AC match for each candidate
   e. Return shortest matching candidate
```

**Built-in AC automaton:** Same as exact match — built with original word forms.

### 5.4 Repetition — `engine/repetition.py`

```
1. Regex collapse runs > threshold to threshold
2. Also collapse ALL runs to single char
3. Run AC on both collapsed forms
4. Map positions back to original text
```

**Built-in AC automaton:** Includes both original patterns AND their collapsed-to-1 forms (e.g., "anal" AND its patterns). This means the AC directly recognises "anal" whether it's the original or collapsed form.

### 5.5 Unicode/Homoglyph — `engine/normalizer.py`

```
1. NFKC normalize input text
2. For homoglyph detection:
   a. Iterate through each character
   b. Look up in HOMOGLYPH_MAP (150+ entries)
   c. Replace if mapping exists AND mapped value differs
   d. Record original → replacement pairs
3. Run AC scan on replaced text
```

### 5.6 Fuzzy — `engine/fuzzy.py`

```
1. Tokenize text
2. For each unmatched token (len >= 4):
   a. Find patterns with |len(pattern) - len(token)| <= max_distance
   b. Compute Damerau-Levenshtein distance (2-row DP)
   c. Early abort if distance exceeds max_distance
   d. Accept if distance <= max_distance AND distance/len(pattern) <= 0.25
```

### 5.7 Risk Scoring — `engine/scorer.py`

```
For each detection:
    score = base_score
    + 0.20 if separator_bypass or leetspeak
    + 0.10 if homoglyph
    + 0.15 if repetition
    + 0.05 × distance if fuzzy
    score = min(1.0, score)
    modifier = 1.0 + (distinct_matches / total_words), capped at 1.5
    final = min(1.0, score × modifier)

Tier mapping:
    final >= 0.8: CRITICAL → action = "block"
    final >= 0.6: HIGH      → action = "warn"
    final >= 0.3: MEDIUM    → action = "flag"
    else:         LOW       → action = "log"
```

### 5.8 Word List Management — `storage/word_list.py` + `api/words.py`

```
WordEntry {
    word: str           # The sensitive word (e.g., "anal")
    normalized: str     # NFKC-lowercased form
    base_score: float   # 0.0–1.0 severity
    tags: List[str]     # e.g., ["sexual", "profanity"]
    enabled: bool       # Active in detection?
    id: int             # Auto-increment
    created_at: datetime
    updated_at: datetime
}

Storage: In-memory dict keyed by lowered word + JSON file persistence.

On change → pipeline.load_words(entries) rebuilds ALL AC automatons:
    - exact_match_ac
    - separator_bypass_ac
    - leetspeak_ac
    - repetition_ac
    - fuzzy_matcher
```

### 5.9 Detection Reports — `storage/reports.py` + `api/reports.py`

```
Storage: In-memory dict keyed by message_id + JSONL file append.
Retention: Auto-prune entries older than retention_days (configurable).

Output channels:
    Inline:  returned in HTTP response
    Webhook: POST report JSON to configured URL (async, fire-and-forget)
    File:    appended to reports.jsonl (one JSON object per line)
```

**Webhook dispatch:**
```python
def _fire_webhook(report):
    if not webhook_url:
        return
    data = json.dumps(report.to_dict())
    req = urllib.request.Request(webhook_url, data=data,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3)
```

---

## 6. Frontend-Backend Communication

### 6.1 Communication Model

The frontend communicates with the backend via **RESTful HTTP/JSON**. All requests and responses use `Content-Type: application/json`. There is no real-time push (SSE/WebSocket) in the current implementation.

### 6.2 Architecture Diagram

```
┌─────────────┐         HTTP/JSON          ┌──────────────────┐
│   Frontend   │──────────────────────────▶│  FastAPI Server   │
│  (Web/Mobile)│                           │  Port 8080/9090   │
│              │◀──────────────────────────│                   │
│   React/Ang  │       JSON Response       │  Uvicorn ASGI     │
│   Vue/App    │                           └──────────────────┘
└─────────────┘
```

### 6.3 Request Flow (Frontend Perspective)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ FRONTEND                                                                │
│                                                                         │
│  1. User types/sends a message                                          │
│  2. Frontend captures text                                              │
│  3. Prepares payload: { text, message_id, context, options }            │
│  4. Sends POST request to /api/v1/detect                                │
│  5. Waits for response (typically <10ms)                                │
│  6. Reads response:                                                     │
│     - summary.action == "block"   → show "Message blocked" UI           │
│     - summary.action == "warn"    → show warning, allow override        │
│     - summary.action == "flag"    → log for moderation panel            │
│     - summary.action == "log"     → allow through, log to analytics    │
│  7. Updates UI accordingly (blocked badge, warning toast, etc.)        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.4 Example Integration Code

**JavaScript (fetch):**
```javascript
async function checkMessage(text, userId) {
  const response = await fetch('http://localhost:8080/api/v1/detect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: text,
      message_id: `msg-${Date.now()}`,
      context: {
        user_id: userId,
        channel: 'chat-room-1',
        message_type: 'text'
      },
      options: {
        fuzzy: true,
        leetspeak: true,
        separator_bypass: true,
        homoglyph: true,
        repetition: true
      }
    })
  });

  const report = await response.json();

  // Handle based on action
  switch (report.summary.action) {
    case 'block':
      showBlockedUI(report.summary.tier);
      blockMessage();
      break;
    case 'warn':
      showWarning(`Contains sensitive content (score: ${report.summary.highest_score})`);
      break;
    case 'flag':
      sendToModerationQueue(report);
      break;
    case 'log':
      // Allow through, log silently
      break;
  }

  return report;
}
```

**Python (requests):**
```python
import requests

response = requests.post(
    "http://localhost:8080/api/v1/detect",
    json={
        "text": "check this a-n-a-l text",
        "message_id": "msg-001",
        "context": {"user_id": "user-42", "channel": "general"},
        "options": {"fuzzy": True, "leetspeak": True, "separator_bypass": True}
    }
)
report = response.json()

if report["summary"]["action"] == "block":
    print("Message blocked")
elif report["summary"]["action"] == "warn":
    print(f"Warning: {report['summary']['highest_score']}")
```

**cURL:**
```bash
curl -X POST http://localhost:8080/api/v1/detect \
  -H "Content-Type: application/json" \
  -d '{
    "text": "check this a-n-a-l text",
    "message_id": "msg-001",
    "options": {"fuzzy": true, "leetspeak": true, "separator_bypass": true}
  }'
```

### 6.5 Batch Flow

For processing multiple messages efficiently (e.g., bulk import, re-checking chat history):

```javascript
async function batchCheck(messages) {
  const batch = messages.map((msg, i) => ({
    text: msg,
    message_id: `batch-${i}-${Date.now()}`
  }));

  const response = await fetch('http://localhost:8080/api/v1/detect/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: batch })
  });

  const { results, count } = await response.json();
  return results;  // Array of reports in the same order
}
```

### 6.6 Word List Management Flow

```
Frontend                                 Backend
   │                                        │
   │  POST /api/v1/words                    │
   │  [{"word": "custom", "base_score": 0.9 │
   │    "tags": ["custom"], "enabled": true}]│
   │───────────────────────────────────────▶│
   │                                        │  Store words
   │                                        │  Rebuild AC automatons
   │                                        │  Return {"added": 1, "total": N}
   │◀───────────────────────────────────────│
   │                                        │
   │  POST /api/v1/detect                    │
   │  {"text": "test custom word"}           │
   │───────────────────────────────────────▶│
   │                                        │  Now detects "custom"
   │◀───────────────────────────────────────│
```

**Word list upload via HTML form:**
```html
<form action="http://localhost:8080/api/v1/words/upload" method="POST" enctype="multipart/form-data">
  <input type="file" name="file" accept=".txt,.csv,.json">
  <button type="submit">Upload</button>
</form>
```

### 6.7 Report Retrieval Flow

```
Frontend                                  Backend
   │                                        │
   │  GET /api/v1/reports?page=1&page_size=50│
   │───────────────────────────────────────▶│
   │                                        │  Return paginated reports
   │◀───────────────────────────────────────│
   │                                        │
   │  GET /api/v1/reports/stats?hours=24    │
   │───────────────────────────────────────▶│
   │                                        │  Return aggregate stats
   │◀───────────────────────────────────────│
   │                                        │
   │  GET /api/v1/reports/export            │
   │───────────────────────────────────────▶│
   │                                        │  Return full JSON download
   │◀───────────────────────────────────────│
```

---

## 7. API Contracts — Complete Reference

### 7.1 Detection

#### `POST /api/v1/detect`

Scan a single message for sensitive words.

**Request:**
```json
{
  "text": "check this a-n-a-l text",
  "message_id": "msg-001",
  "context": {
    "user_id": "user-42",
    "channel": "chat-room-1",
    "message_type": "text"
  },
  "options": {
    "fuzzy": true,
    "leetspeak": true,
    "homoglyph": true,
    "separator_bypass": true,
    "repetition": true,
    "max_distance": 2
  }
}
```

**Optional fields:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `message_id` | string | auto-generated | Unique identifier for dedup |
| `context` | object | `null` | Arbitrary metadata (user_id, channel, etc.) |
| `options` | object | all enabled | Per-request detection toggles |

**Response (200):**
```json
{
  "message_id": "msg-001",
  "timestamp": "2026-06-03T12:00:00.000000",
  "text": "check this a-n-a-l text",
  "normalized_text": "check this a-n-a-l text",
  "detections": [
    {
      "word": "anal",
      "matched_form": "a-n-a-l",
      "start": 11,
      "end": 18,
      "base_score": 0.8,
      "final_score": 0.88,
      "method": "separator_bypass",
      "sub_methods": ["separator_bypass"],
      "homoglyphs_detected": [],
      "distance": null,
      "tags": [],
      "tier": "critical"
    }
  ],
  "summary": {
    "total_detections": 1,
    "distinct_words": 1,
    "highest_score": 0.88,
    "average_score": 0.88,
    "tier": "critical",
    "action": "block",
    "processing_time_ms": 0.42
  }
}
```

**Error responses:**
| Status | Condition |
|--------|-----------|
| 422 | Empty text or text exceeds max_message_length (10K) |
| 500 | Internal engine error (bug in pipeline) |

---

#### `POST /api/v1/detect/batch`

Scan up to 1000 messages in a single request.

**Request:**
```json
{
  "messages": [
    {
      "text": "check this a-n-a-l",
      "message_id": "batch-0",
      "context": null,
      "options": {"fuzzy": true}
    },
    {
      "text": "hello world",
      "message_id": "batch-1"
    }
  ]
}
```

**Response (200):**
```json
{
  "results": [
    { /* full DetectionReport for batch-0 */ },
    { /* full DetectionReport for batch-1 */ }
  ],
  "count": 2
}
```

**Error handling:** Each message is processed independently. If one fails, its result contains an `"error"` field instead of a full report. Other messages are unaffected.

---

### 7.2 Word List Management

#### `POST /api/v1/words`

Upload a word list as JSON array.

**Request body:**
```json
[
  {"word": "anal", "base_score": 0.8, "tags": ["sexual"], "enabled": true},
  {"word": "drugs", "base_score": 0.7, "tags": ["illegal"], "enabled": true}
]
```

**Response (200):**
```json
{
  "added": 2,
  "total": 27,
  "words": [
    {"id": 1, "word": "anal", "base_score": 0.8, "tags": ["sexual"], "enabled": true, "created_at": "...", "updated_at": "..."},
    ...
  ]
}
```

---

#### `POST /api/v1/words/upload`

Upload a file (TXT, CSV, or JSON).

- **TXT** — one word per line, lines starting with `#` are comments. Default base_score=0.5.
- **CSV** — columns: `word`, `base_score`, `tags` (comma-separated tags in quotes).
- **JSON** — array of `{word, base_score, tags, enabled}` objects.

**Example:** `curl -F "file=@words.txt" http://localhost:8080/api/v1/words/upload`

**Response (200):**
```json
{
  "added": 15,
  "total": 42,
  "filename": "words.txt"
}
```

---

#### `GET /api/v1/words`

List all words (paginated).

**Query params:** `page` (default 1), `page_size` (default 100)

**Response (200):**
```json
{
  "total": 100,
  "page": 1,
  "page_size": 100,
  "words": [
    {"id": 1, "word": "anal", "base_score": 0.8, ...}
  ]
}
```

---

#### `GET /api/v1/words/{word}`

Get a single word by its text.

**Response (200):**
```json
{
  "id": 1,
  "word": "anal",
  "base_score": 0.8,
  "tags": ["sexual"],
  "enabled": true
}
```

**Response (404):** `{"detail": "Word not found"}`

---

#### `POST /api/v1/words/{word}`

Add a single word.

**Request body:**
```json
{
  "word": "new-word",
  "base_score": 0.6,
  "tags": ["custom"],
  "enabled": true
}
```

---

#### `PUT /api/v1/words/{word}`

Update an existing word.

**Request body (all fields optional):**
```json
{
  "base_score": 0.9,
  "tags": ["updated"],
  "enabled": false
}
```

---

#### `DELETE /api/v1/words`

Clear ALL words.

**Response (200):** `{"cleared": true, "total": 0}`

---

#### `DELETE /api/v1/words/{word}`

Delete a single word.

**Response (200):** `{"deleted": "anal", "total": 26}`

---

#### `POST /api/v1/words/reload`

Reload the default word list from the configured file path.

**Response (200):** `{"reloaded": true, "total": 25}`

---

### 7.3 Reports

#### `GET /api/v1/reports`

List detection reports (paginated, optionally filtered by tier).

**Query params:** `page` (default 1), `page_size` (default 100), `tier` (optional: low/medium/high/critical)

**Response (200):**
```json
{
  "total": 150,
  "page": 1,
  "page_size": 100,
  "reports": [
    {
      "message_id": "msg-001",
      "timestamp": "2026-06-03T12:00:00",
      "text": "a-n-a-l",
      "detections": [...],
      "summary": {...}
    }
  ]
}
```

---

#### `GET /api/v1/reports/export`

Download ALL reports as JSON.

**Response (200):** `Content-Type: application/json`, `Content-Disposition: attachment; filename=reports.json`

---

#### `GET /api/v1/reports/stats`

Aggregate statistics for the last N hours.

**Query params:** `hours` (default 24)

**Response (200):**
```json
{
  "total": 120,
  "detections": 42,
  "blocked": 5,
  "flagged": 12,
  "average_processing_time_ms": 0.38,
  "top_words": [
    {"word": "anal", "count": 15},
    {"word": "fuck", "count": 8}
  ]
}
```

---

#### `GET /api/v1/reports/{message_id}`

Get a single report by ID.

**Response (200):** Full DetectionReport JSON.

**Response (404):** `{"error": "Report not found"}`

---

#### `DELETE /api/v1/reports/older-than/{days}`

Purge reports older than N days.

**Response (200):** `{"purged_older_than_days": 90}`

---

### 7.4 Health

#### `GET /health`

**Response (200):**
```json
{
  "status": "ok",
  "words_loaded": 25,
  "config": {
    "server": "0.0.0.0:8080",
    "detection": {
      "leetspeak": true,
      "homoglyph": true,
      "separator_bypass": true,
      "repetition": true,
      "fuzzy": true
    }
  }
}
```

#### `POST /api/v1/detect/health`

Quick pipeline health check. Scans a test message and reports processing time.

**Response (200):**
```json
{
  "status": "ok",
  "patterns_loaded": 25,
  "processing_time_ms": 0.12
}
```

---

### 7.5 Complete Endpoint Summary

| Method | Path | Description | Request body | Response |
|--------|------|-------------|-------------|----------|
| POST | `/api/v1/detect` | Scan single message | DetectionRequest | DetectionReport |
| POST | `/api/v1/detect/batch` | Scan multiple messages | BatchDetectionRequest | `{results, count}` |
| POST | `/api/v1/detect/health` | Pipeline health check | — | health status |
| GET | `/health` | Server health | — | server status |
| POST | `/api/v1/words` | Upload word list JSON | `[WordRequest]` | `{added, total, words}` |
| POST | `/api/v1/words/upload` | Upload file (TXT/CSV/JSON) | multipart file | `{added, total, filename}` |
| GET | `/api/v1/words` | List words | `?page=&page_size=` | paginated word list |
| GET | `/api/v1/words/{word}` | Get single word | — | WordEntry |
| POST | `/api/v1/words/{word}` | Add single word | WordRequest | `{added, total}` |
| PUT | `/api/v1/words/{word}` | Update word | WordUpdateRequest | updated WordEntry |
| DELETE | `/api/v1/words` | Clear all words | — | `{cleared, total}` |
| DELETE | `/api/v1/words/{word}` | Delete single word | — | `{deleted, total}` |
| POST | `/api/v1/words/reload` | Reload from file | — | `{reloaded, total}` |
| GET | `/api/v1/reports` | List reports | `?page=&tier=` | paginated reports |
| GET | `/api/v1/reports/export` | Download reports | `?format=json` | JSON file |
| GET | `/api/v1/reports/stats` | Aggregate stats | `?hours=24` | statistics |
| GET | `/api/v1/reports/{id}` | Get single report | — | DetectionReport |
| DELETE | `/api/v1/reports/older-than/{days}` | Purge old reports | — | confirmation |

---

## 8. Server Management

### 8.1 Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | ≥ 3.10 | Tested on 3.13 |
| pip | latest | |
| Docker | ≥ 20.10 | Optional, for containerized deployment |
| Port | 8080 or 9090 | Ensure not already in use |

### 8.2 Without Docker (Direct)

#### Installation

```bash
# Navigate to project
cd "Sensitive words filteration"

# (Recommended) Create virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**`requirements.txt` contents:**
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
pyyaml>=6.0
```

#### Starting the Server

```bash
# Standard start (single worker)
python -m uvicorn main:app --host 0.0.0.0 --port 8080

# With hot-reload for development
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# With multiple workers (production)
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --workers 4

# Using gunicorn (Linux, production)
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080
```

**Startup output (normal):**
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Loading default word list from data/sensitive_words.txt
INFO:     Loaded 25 words into pipeline
INFO:     Server starting on 0.0.0.0:8080 with 25 words loaded
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

**Troubleshooting:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Address already in use` | Port taken | Change port: `--port 9090` or kill existing process |
| `ModuleNotFoundError` | Dependencies not installed | `pip install -r requirements.txt` |
| `No words loaded` | `data/sensitive_words.txt` missing | Create the file with one word per line |
| Slow first request | Python bytecode compilation | Normal; subsequent requests are faster |

#### Stopping the Server

```bash
# Method 1: Keyboard interrupt
Press CTRL+C in the terminal

# Method 2: Find and kill process (Windows)
netstat -ano | findstr :8080
taskkill /PID <PID> /F

# Method 3: Find and kill process (Linux/Mac)
lsof -i :8080
kill -9 <PID>
```

#### Verifying the Server is Running

```bash
# Health check
curl http://localhost:8080/health
# Expected: {"status": "ok", "words_loaded": 25, ...}

# Quick detection test
curl -X POST http://localhost:8080/api/v1/detect \
  -H "Content-Type: application/json" \
  -d '{"text": "test anal", "message_id": "verify"}'
# Expected: 1 detection for "anal"
```

### 8.3 With Docker

#### Dockerfile

Create a `Dockerfile` in the project root:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

#### Docker Compose (Optional)

Create a `docker-compose.yml`:

```yaml
version: '3.8'
services:
  filter-api:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data
      - ./config.yaml:/app/config.yaml
    environment:
      - CONFIG_PATH=/app/config.yaml
    restart: unless-stopped
```

#### Building and Starting

```bash
# Build image
docker build -t sensitive-words-filter .

# Run container
docker run -d \
  --name sw-filter \
  -p 8080:8080 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/config.yaml:/app/config.yaml" \
  -e CONFIG_PATH=/app/config.yaml \
  sensitive-words-filter

# Or using docker-compose
docker-compose up -d
```

**Startup output:**
```
# docker logs sw-filter
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Loading default word list from data/sensitive_words.txt
INFO:     Loaded 25 words into pipeline
INFO:     Server starting on 0.0.0.0:8080 with 25 words loaded
INFO:     Uvicorn running on http://0.0.0.0:8080
```

#### Stopping Docker

```bash
# Stop container
docker stop sw-filter

# Remove container
docker rm sw-filter

# Or using docker-compose
docker-compose down

# Remove image
docker rmi sensitive-words-filter
```

#### Docker Volume Mapping

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `./data` | `/app/data` | Persist word_list.json and reports.jsonl |
| `./config.yaml` | `/app/config.yaml` | Custom configuration |
| `./data/sensitive_words.txt` | `/app/data/sensitive_words.txt` | Default word list |

**Without volume mapping:** All data resets when the container restarts.

### 8.4 Using `config.yaml`

The server auto-loads `config.yaml` from the project root. Customize:

```yaml
server:
  port: 8080            # Change if port conflict
  workers: 1            # Increase for multi-core

detection:
  leetspeak:
    enabled: true       # Set false to disable leetspeak detection
  separator_bypass:
    enabled: true
  repetition:
    enabled: true
  fuzzy:
    max_distance: 2     # Lower = stricter, higher = more permissive
    min_word_length: 4  # Skip fuzzy for words shorter than this

reporting:
  webhook_url: "https://hooks.example.com/report"  # Set to enable webhook

logging:
  level: "info"         # debug, info, warn, error
  format: "text"        # text or json
```

**Environment variable overrides:**

| Variable | Overrides | Example |
|----------|-----------|---------|
| `CONFIG_PATH` | Config file path | `CONFIG_PATH=/etc/sw-filter/config.yaml` |
| `WORD_LIST_PATH` | Word list persistence file | `WORD_LIST_PATH=/data/my-words.json` |
| `REPORT_PATH` | Report persistence file | `REPORT_PATH=/data/reports.jsonl` |

### 8.5 Performance Tuning

| Setting | Effect | Recommended value |
|---------|--------|-------------------|
| `server.workers` | Parallel request handling | 1–4 (match CPU cores) |
| `detection.fuzzy.max_checks_per_message` | CPU budget for fuzzy | 500 (default) |
| `detection.fuzzy.max_distance` | Fuzzy sensitivity | 2 (default) |
| `detection.max_message_length` | Input size limit | 10000 (default) |
| `detection.leetspeak.max_expansions` | BFS budget | 1024 (default) |

**For high throughput (2,000+ msg/sec):**
- Set `workers=number_of_cpu_cores`
- Disable fuzzy if not needed: `fuzzy.enabled: false`
- Use a production ASGI server: `gunicorn -w 4 -k uvicorn.workers.UvicornWorker`
- Consider disabling leetspeak BFS: reduce `max_expansions: 128`

### 8.6 Endpoint Testing Cheat Sheet

```bash
# Health
curl http://localhost:8080/health

# Detect single
curl -X POST http://localhost:8080/api/v1/detect \
  -H "Content-Type: application/json" \
  -d '{"text":"a-n-a-l test"}'

# Detect batch
curl -X POST http://localhost:8080/api/v1/detect/batch \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"text":"clean","message_id":"1"},{"text":"4n4l","message_id":"2"}]}'

# List words
curl http://localhost:8080/api/v1/words

# Add word
curl -X POST http://localhost:8080/api/v1/words \
  -H "Content-Type: application/json" \
  -d '[{"word":"custom","base_score":0.8,"tags":["custom"]}]'

# Upload file
curl -F "file=@data/sensitive_words.txt" http://localhost:8080/api/v1/words/upload

# Delete word
curl -X DELETE http://localhost:8080/api/v1/words/anal

# List reports
curl http://localhost:8080/api/v1/reports?page=1&page_size=10

# Export reports
curl http://localhost:8080/api/v1/reports/export -o reports.json

# Stats
curl "http://localhost:8080/api/v1/reports/stats?hours=24"

# Purge old reports
curl -X DELETE http://localhost:8080/api/v1/reports/older-than/90
```

### 8.7 Log File Locations

| File | Purpose | Persistence |
|------|---------|-------------|
| `data/word_list.json` | Word list persistence | Survives restarts |
| `data/reports.jsonl` | Detection report log (append-only) | Survives restarts |
| `config.yaml` | Server configuration | Manual edits |
| `data/sensitive_words.txt` | Default word list source | Manual edits |

---

## 9. Appendix — Edge Cases & Behavior

### 9.1 Empty & Edge Inputs

| Input | Behavior |
|-------|----------|
| Empty string `""` | Rejected by API (422 Unprocessable Entity) |
| Single character `"a"` | No match (all detectors require patterns >= 1 char) |
| Whitespace only `"   "` | Returns clean report (0 detections) |
| Maximum length (10K chars) | Truncated at 10K, then scanned |
| Only numbers `"12345"` | No match (unless numbers are in word list) |
| Mixed scripts `"abcαβγ"` | Homoglyph stage replaces Greek → Latin |

### 9.2 False Positive Prevention

| Scenario | Prevention |
|----------|------------|
| Word as substring of normal word | AC detects at exact positions; fuzzy has distance_ratio limit |
| Common abbreviation | Only matches words in the word list; no auto-guessing |
| URL containing sensitive word | AC finds it; URL protocol/domain irrelevant |
| Unicode confusables in benign text | Only replaced if they map to different characters |
| Single char repeats | Repetition requires threshold=2 |
| Leet in numbers like `80085` | Only detected if BFS finds a dictionary word in the word list |

### 9.3 Race Condition & Concurrency Safety

| Scenario | Handling |
|----------|----------|
| Word list update during detection | Pipeline holds reference to immutable AC; new upload creates new AC, old one is GC'd after in-flight requests complete |
| Concurrent word list uploads | Last write wins (crude but safe) |
| Multiple requests simultaneously | Uvicorn handles with async workers; each request gets its own pipeline state |

### 9.4 Persistence Guarantees

| Scenario | Data loss risk |
|----------|---------------|
| Server crash | Reports in memory are lost (up to last JSONL sync) |
| Graceful shutdown | Word list and reports are synced to disk |
| Docker restart without volumes | ALL data lost |
| Word list cleared via API | JSON file immediately synced |

### 9.5 Detection Method Priority

When multiple methods could detect the same word, the first one wins (lower method ordinal):

1. **Exact** (highest priority)
2. **Homoglyph**
3. **Separator Bypass**
4. **Leetspeak**
5. **Repetition**
6. **Fuzzy** (lowest priority)

If `anal` is found via both separator_bypass and leetspeak, only the separator_bypass detection is reported. This prevents duplicate entries in the detections array.
