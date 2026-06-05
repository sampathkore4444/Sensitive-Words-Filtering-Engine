# Sensitive Words Filteration — Specification

> Real-time sensitive word detection engine with obfuscation bypass, fuzzy matching, leetspeak, homoglyph, Unicode normalization, and risk scoring.

---

## 1. Project Overview

A high-performance, real-time text scanning system that detects sensitive/blocked words even when obfuscated. Designed for chat moderation, content filtering, DLP (Data Loss Prevention), and compliance monitoring.

**Primary goals:**
- Detect sensitive words with **zero false negatives** for exact matches
- Resist all common obfuscation techniques (spaces, separators, leetspeak, homoglyphs, repetition)
- Process **10,000+ messages/second** on commodity hardware
- Provide a **risk score** per detection to enable tiered response (warn → flag → block)

---

## 2. Feature Specification

### 2.1 Exact Matching

| Property | Value |
|----------|-------|
| Algorithm | Hash set lookup (O(1) per token) after tokenization |
| Case | Case-insensitive by default |
| Whitespace | Trimmed before matching |
| Edge cases | Empty string → no match; partial substring → no match (handled by Aho-Corasick) |

**Behavior:** The input text is split into tokens by whitespace/punctuation boundaries. Each token is lowercased and looked up in a `HashSet<String>`. If found → match.

---

### 2.2 Obfuscation Detection (Separator Bypass)

Detects words where characters are intentionally separated.

| Separator examples | Detected patterns |
|-------------------|-------------------|
| Spaces | `a n a l` |
| Hyphens | `a-n-a-l` |
| Dots | `a.n.a.l` |
| Underscores | `a_n_a_l` |
| Slashes | `a/n/a/l` |
| Mixed | `a -n . a_l` |

**Algorithm:**
1. Strip all characters that match `[^a-zA-Z0-9]` from the input span.
2. Run Aho-Corasick on the cleaned string.
3. If a match is found, record `original_text`, `cleaned_text`, and `method: "separator_bypass"`.

**Edge cases:** `a!!!n!!!a!!!l` (repeated punctuation), leading/trailing separators are ignored.

---

### 2.3 Leetspeak Detection

Converts common leet substitutions back to plain text and matches against the word list.

| Leet char | Plain |
|-----------|-------|
| `4`, `@` | `a` |
| `8` | `b` |
| `(`, `{`, `<` | `c` |
| `3` | `e` |
| `6`, `9` | `g` |
| `#`, `1`, `!`, `|` | `i` / `l` |
| `0` | `o` |
| `$`, `5` | `s` |
| `7`, `+` | `t` |
| `2` | `z` |
| `\|-\|` | `h` |
| `\|\|` | `n` |
| `\/\/` | `w` |

**Algorithm:**
1. Build a mapping from leet characters → possible plain characters.
2. For each span of text, generate candidate plaintext strings via BFS/DFS (bounded by max expansions, default 1024).
3. Match candidates against the word list.
4. Return the shortest Levenshtein match if multiple candidates.

**Performance constraint:** Only expand ambiguous leet characters; plain letters pass through at O(1).

---

### 2.4 Repeated Character Normalization

Detects words with repeated characters used to evade detection (e.g., `annnnal` → `anal`).

**Algorithm:**
1. Collapse runs of the same character > 2 repetitions down to 2 (`annnnal` → `annal`).
2. Also try collapsing to 1 (`annnnal` → `anal`).
3. Match both forms against the word list.
4. If the `collapsed-to-1` form matches, severity is higher (more intentional).

**Threshold:** Configurable — default collapse threshold = 2 repetitions.

---

### 2.5 Unicode Normalization

Normalizes Unicode text before detection to prevent homoglyph attacks through different Unicode representations.

| Normalization form | Description |
|--------------------|-------------|
| **NFC** (Normalization Form C) | Canonical decomposition followed by canonical composition |
| **NFD** (Normalization Form D) | Canonical decomposition |
| **NFKC** (Normalization Form KC) | Compatibility decomposition followed by canonical composition |
| **NFKD** (Normalization Form KD) | Compatibility decomposition |

**Default pipeline:** NFKC — aggressively converts compatibility characters (e.g., ﬁ → fi, ² → 2) while maintaining canonical equivalence.

**CJK handling:** No normalization of Han characters beyond what Unicode defines; uses NFKC for fullwidth/halfwidth conversion (e.g., `Ａ` → `A`).

---

### 2.6 Homoglyph Detection

Detects characters that look like Latin letters but are from different Unicode blocks.

| Target char | Common homoglyphs |
|-------------|-------------------|
| `a` | `а` (Cyrillic), `α` (Greek), `ａ` (fullwidth) |
| `c` | `с` (Cyrillic), `ⅽ` (Roman numeral) |
| `e` | `е` (Cyrillic), `ɛ` (Latin epsilon), `℮` (estimated) |
| `i` | `і` (Cyrillic), `ı` (dotless), `Ι` (Greek iota) |
| `o` | `о` (Cyrillic), `ο` (Greek omicron), `０` (fullwidth), `0` (digit) |
| `p` | `р` (Cyrillic), `ρ` (Greek rho) |
| `s` | `ѕ` (Cyrillic), `ѕ` (Greek final sigma) |
| `x` | `х` (Cyrillic), `χ` (Greek chi), `ⅹ` (Roman numeral) |

**Algorithm:**
1. Build a homoglyph map (Unicode codepoint → target ASCII char).
2. Replace each character in the span using the map, O(n).
3. Run Aho-Corasick on the de-homoglyphed string.
4. Record `detected_homoglyphs: [list of original chars]`.

**Source data:** Derived from [confusables.txt](https://www.unicode.org/Public/security/latest/confusables.txt) (Unicode Security Mechanisms).

---

### 2.7 Aho-Corasick High-Speed Scanning

The core matching engine. Builds a deterministic finite automaton (DFA) from the sensitive word list for O(n) multi-pattern matching.

**States:** N + 1 where N = total characters of all patterns (trie).

**Operations:**
- **Build:** O(K) where K = total characters across all patterns.
- **Scan:** O(n + m) where n = text length, m = total matches found.
- **Memory:** ~40–60 bytes per state (fail link, output list, transitions).

**Transition table optimization:**
- For dense alphabets (< 10,000 words): use a 2D array `states × alphabet_size` for constant-time lookups.
- For sparse alphabets: use a `HashMap<Char, StateId>` per state.

**Output handling:**
- Each state stores a `Vec<usize>` of pattern IDs that end at this state.
- Online matching: as we feed characters, we follow transitions; when we reach a state with outputs, emit all matches.

**Pipeline integration:**
```
Raw text → Unicode NFC normalize → (optional) homoglyph replace → Aho-Corasick scan → match list
```

---

### 2.8 Fuzzy Matching

Detects words that are approximately (but not exactly) equal to a sensitive word.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_distance` | 2 | Maximum Levenshtein (edit) distance |
| `min_word_length` | 4 | Only fuzzy-match words >= this length |
| `distance_ratio` | 0.25 | `distance / len(pattern)` — adaptive threshold |

**Algorithm (Damerau-Levenshtein):**
1. For each detected candidate word > `min_word_length`, compute edit distance against each sensitive word of similar length (`abs(len_a - len_b) <= max_distance`).
2. Bucket words by length to reduce comparisons: for a word of length L, only check sensitive words in range `[L - max_distance, L + max_distance]`.
3. If `distance <= max_distance` AND `distance / len(pattern) <= distance_ratio` → fuzzy match.

**Performance note:** Fuzzy matching is O(k × n × m) worst-case per message. Run after exact/AC matching (which filters out obvious non-matches) and apply a message-level budget (e.g., max 500 fuzzy checks per message).

**Edge case:** Word `abc` with max_distance=2 matches `xyz` but `3/3=1.0 > 0.25` — correctly rejected.

---

### 2.9 Risk Scoring

Assigns a severity score (0.0 → 1.0) per detection to enable tiered responses.

#### Scoring factors

| Factor | Weight | Description |
|--------|--------|-------------|
| `base_score` | 1.0 | Pre-assigned severity of the matched word (0.3–1.0) |
| `obfuscation_penalty` | +0.2 | If separator bypass or leetspeak was used |
| `homoglyph_penalty` | +0.1 | If homoglyphs were detected |
| `repetition_penalty` | +0.15 | If character repetition was detected |
| `distance_penalty` | +0.05 × distance | Per unit of Levenshtein distance |
| `frequency_bonus` | −0.1 | If word appears in repeated matches (reduce score) |
| `context_multiplier` | 1.0–1.5 | Number of distinct sensitive words / message length |

#### Final score calculation

```
raw_score = min(1.0, base_score + sum(penalties))
context_modifier = min(1.5, 1.0 + (distinct_matches / max(1, word_count)))
final_score = min(1.0, raw_score * context_modifier)
```

#### Score tiers

| Range | Label | Suggested action |
|-------|-------|------------------|
| 0.0 – 0.3 | Low | Log only |
| 0.3 – 0.6 | Medium | Flag for review |
| 0.6 – 0.8 | High | Warn user, notify moderator |
| 0.8 – 1.0 | Critical | Block message, auto-moderation |

---

### 2.10 Upload Custom Sensitive Word List

Allows users to manage their own word lists at runtime.

**API:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/words` | POST | Upload a new word list (JSON/CSV/TXT) |
| `/api/v1/words` | GET | List all active words |
| `/api/v1/words` | DELETE | Clear word list |
| `/api/v1/words/{id}` | PUT | Update a single word |
| `/api/v1/words/{id}` | DELETE | Remove a single word |
| `/api/v1/words/reload` | POST | Reload from file on disk |

**Upload format (JSON):**
```json
[
  {"word": "anal", "base_score": 0.8, "tags": ["sexual"], "enabled": true},
  {"word": "drugs", "base_score": 0.7, "tags": ["illegal"], "enabled": true}
]
```

**Upload format (CSV):**
```csv
word,base_score,tags
anal,0.8,"sexual"
drugs,0.7,"illegal"
```

**Upload format (TXT):**
```
anal
drugs
```
(Plain TXT assigns default base_score = 0.5, no tags.)

**Validation:**
- Max word length: 256 characters.
- Max list size: 100,000 words.
- Rebuilds Aho-Corasick automaton after upload.
- Rebuild wall time must not exceed 5 seconds (async rebuild for lists > 50,000 words).

---

### 2.11 Detection Report

Generates a structured report for every scanned message.

**Report structure:**
```json
{
  "message_id": "uuid",
  "timestamp": "2026-06-03T12:00:00Z",
  "text": "original input text",
  "normalized_text": "text after NFKC normalization and homoglyph replacement",
  "detections": [
    {
      "word": "anal",
      "matched_form": "a-n-a-l",
      "start": 0,
      "end": 7,
      "base_score": 0.8,
      "final_score": 0.95,
      "method": "separator_bypass",
      "sub_methods": ["leetspeak", "hyphen_separator"],
      "homoglyphs_detected": ["а"→"a"],
      "distance": null
    }
  ],
  "summary": {
    "total_detections": 1,
    "distinct_words": 1,
    "highest_score": 0.95,
    "average_score": 0.95,
    "tier": "critical",
    "processing_time_ms": 0.42
  }
}
```

**Output channels:**
1. **Inline** — returned in the API response for real-time consumers.
2. **Webhook** — POST report to a configurable URL for async processing.
3. **Log** — structured JSON to stdout / file / syslog.
4. **Stream** — Kafka / RabbitMQ / Redis pub/sub for downstream analytics.

---

## 3. System Architecture

```
┌─────────────┐     ┌─────────────────────────────────────┐     ┌──────────────┐
│   Client     │────▶│         Detection Engine            │────▶│   Response    │
│  (App/Chat)  │     │                                     │     │  (Block/Flag) │
└─────────────┘     │  ┌─────────┐  ┌──────────────────┐  │     └──────────────┘
                    │  │Pre-     │  │  Matcher Pipeline │  │
                    │  │processor│  │                    │  │
                    │  │         │  │  1. Unicode NFC    │  │
                    │  │Word     │  │  2. Homoglyph      │  │
                    │  │List     │  │  3. Aho-Corasick   │  │
                    │  │Manager  │  │  4. Separator      │  │
                    │  │         │  │  5. Leetspeak      │  │
                    │  │Automaton│  │  6. Repetition     │  │
                    │  │Builder  │  │  7. Fuzzy          │  │
                    │  │         │  │                    │  │
                    │  └─────────┘  └──────────────────┘  │
                    │                                     │
                    │  ┌──────────┐  ┌──────────────────┐  │
                    │  │ Scorer   │  │  Report Builder  │  │
                    │  └──────────┘  └──────────────────┘  │
                    └─────────────────────────────────────┘
```

### 3.1 Module responsibilities

| Module | Responsibility |
|--------|---------------|
| **Word List Manager** | Stores, validates, and indexes sensitive words. Triggers automaton rebuild on change. |
| **Automaton Builder** | Compiles word list into Aho-Corasick DFA. Supports incremental rebuild. |
| **Pre-processor** | Applies NFKC normalization and homoglyph replacement to raw text. |
| **Matcher Pipeline** | Runs each detection strategy in order (fast → slow), deduplicates results. |
| **Scorer** | Computes final risk score from raw detections and context. |
| **Report Builder** | Assembles the detection report JSON, handles output routing. |

---

## 4. Detection Pipeline (Execution Order)

Every message passes through these stages sequentially. Early stages are fast and filter obvious cases; later stages are more expensive but catch obfuscation.

```
         ┌──────────────────┐
         │  Raw text input  │
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  Stage 1: NFKC   │  O(n) — always runs
         │  Normalization   │
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  Stage 2: Aho-   │  O(n) — always runs first match pass
         │  Corasick (exact)│
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  Stage 3: Homo-  │  O(n) — only if Stage 2 has partial/zero matches
         │  glyph replace   │
         │  + AC rescan     │
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  Stage 4:        │  O(n) — for each span, strip separators
         │  Separator Bypass│  + AC scan on cleaned string
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  Stage 5:        │  O(b^n) bounded — only if Stages 2-4 miss
         │  Leetspeak       │
         │  Decoder         │
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  Stage 6:        │  O(n) — collapse and re-check
         │  Repetition      │
         │  Normalization   │
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  Stage 7:        │  O(k × n × m) bounded
         │  Fuzzy Matching  │  — only non-matched words
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │  Stage 8:        │
         │  Risk Scoring    │
         │  + Report        │
         └──────────────────┘
```

**Short-circuit:** If Stage 2 (AC exact) detects matches covering 100% of the message (after normalization), skip Stages 3–7.

---

## 5. API Design

### 5.1 Detection API

```
POST /api/v1/detect
```

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
    "include_raw": false,
    "fuzzy": true,
    "leetspeak": true,
    "homoglyph": true,
    "max_distance": 2
  }
}
```

**Response:**
```json
{
  "message_id": "msg-001",
  "detections": [
    {
      "word": "anal",
      "matched_form": "a-n-a-l",
      "start": 11,
      "end": 18,
      "base_score": 0.8,
      "final_score": 0.95,
      "method": "separator_bypass",
      "tier": "critical",
      "tags": ["sexual"]
    }
  ],
  "summary": {
    "total_detections": 1,
    "distinct_words": 1,
    "highest_score": 0.95,
    "average_score": 0.95,
    "tier": "critical",
    "processing_time_ms": 1.23,
    "action": "block"
  }
}
```

### 5.2 Batch Detection API

```
POST /api/v1/detect/batch
```

Accepts up to 1000 messages in a single request. Returns results in the same order.

### 5.3 Word List Management API

```
POST   /api/v1/words              Upload word list
GET    /api/v1/words              List words (paginated)
DELETE /api/v1/words              Clear all words
POST   /api/v1/words/{id}         Add single word
GET    /api/v1/words/{id}         Get single word
PUT    /api/v1/words/{id}         Update single word
DELETE /api/v1/words/{id}         Delete single word
POST   /api/v1/words/reload       Reload from configured file
```

### 5.4 Report / Export API

```
GET    /api/v1/reports            List detection reports (paginated, filterable)
GET    /api/v1/reports/{id}       Get single report
GET    /api/v1/reports/export     Export reports as CSV/JSON/Parquet
GET    /api/v1/reports/stats      Aggregate statistics (hourly/daily)
DELETE /api/v1/reports/older-than Purge reports older than N days
```

---

## 6. Performance Requirements

| Metric | Target | Measurement |
|--------|--------|-------------|
| Throughput | ≥ 10,000 messages/sec | Single-thread, 50-char avg message |
| P99 latency | ≤ 5 ms | From HTTP request to response |
| Automaton rebuild | ≤ 5 sec for 100K words | Wall clock, single-threaded |
| Homoglyph map | ≤ 200 μs per 100-char message | 95th percentile |
| Leetspeak decode | ≤ 1 ms per candidate word | 95th percentile |
| Memory (idle) | ≤ 200 MB | With 100K word list |
| Memory (peak) | ≤ 500 MB | Under load, 100 messages in flight |

---

## 7. Configuration

```yaml
# config.yaml
server:
  host: "0.0.0.0"
  port: 8080
  workers: 4  # for multi-threaded mode

detection:
  case_sensitive: false
  default_base_score: 0.5
  max_message_length: 10000  # characters; reject longer

  # Pipeline stages
  leetspeak:
    enabled: true
    max_expansions: 1024

  homoglyph:
    enabled: true
    use_unicode_confusables: true

  separator_bypass:
    enabled: true
    separator_chars: [' ', '-', '.', '_', '/', '|', '~', '*', '!']

  repetition:
    enabled: true
    collapse_threshold: 2

  fuzzy:
    enabled: true
    max_distance: 2
    min_word_length: 4
    distance_ratio: 0.25
    max_checks_per_message: 500

  scoring:
    tiers:
      - threshold: 0.3
        label: "low"
        action: "log"
      - threshold: 0.6
        label: "medium"
        action: "flag"
      - threshold: 0.8
        label: "high"
        action: "warn"
      - threshold: 1.0
        label: "critical"
        action: "block"

word_list:
  default_path: "./data/sensitive_words.txt"
  auto_reload: false
  max_words: 100000
  max_word_length: 256

reporting:
  storage: "postgresql://localhost:5432/words_filter"  # or "sqlite", "elasticsearch"
  retention_days: 90
  webhook_url: ""
  stream:
    enabled: false
    type: ""  # kafka, rabbitmq, redis
    url: ""

logging:
  level: "info"  # debug, info, warn, error
  format: "json" # json or text
```

---

## 8. Data Structures

### 8.1 Trie Node (Aho-Corasick)

```rust
struct AcNode {
    children: HashMap<char, usize>,   // or Vec<usize> for dense
    fail: usize,                       // failure link
    output: Vec<usize>,                // pattern IDs ending here
    depth: u16,                        // depth in trie (for diagnostics)
    is_end: bool,
}
```

### 8.2 Word Entry

```rust
struct WordEntry {
    id: usize,
    word: String,
    normalized: String,        // NFKC-normalized form
    base_score: f64,           // 0.0 – 1.0
    tags: Vec<String>,
    enabled: bool,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}
```

### 8.3 Detection Result

```rust
struct Detection {
    word: String,
    matched_form: String,      // the actual text that triggered the match
    start: usize,
    end: usize,
    base_score: f64,
    final_score: f64,
    method: DetectionMethod,   // exact, separator_bypass, leetspeak, etc.
    sub_methods: Vec<String>,
    homoglyphs_detected: Vec<(char, char)>,  // (original → replaced)
    distance: Option<u8>,      // Levenshtein distance, if fuzzy
}
```

### 8.4 Detection Report

```rust
struct DetectionReport {
    message_id: String,
    timestamp: DateTime<Utc>,
    text: String,
    normalized_text: Option<String>,
    detections: Vec<Detection>,
    summary: ReportSummary,
    context: Option<MessageContext>,
}
```

---

## 9. Testing Strategy

| Category | Approach | Coverage target |
|----------|----------|-----------------|
| Unit tests | Per-module tests for normalizer, AC builder, scorer | ≥ 90% line coverage |
| Obfuscation fuzz | Generate random separators/leet/homoglyph combos | 10,000+ random inputs |
| Regression | Known-bypass corpus (adversarial examples) | All known bypass techniques |
| Performance | Benchmarks for each pipeline stage | Regression check in CI |
| Integration | Upload word list → detect → report end-to-end | Full API flow |
| Concurrency | 64 parallel clients, random payloads | No deadlocks, no corrupt state |

### Adversarial test cases:

```
Input                             Expected match
──────────────────────────────────────────────────
a n a l                           anal (separator)
a-n-a-l                           anal (separator)
4n4l                              anal (leetspeak)
@n@l                              anal (leetspeak)
annnnal                           anal (repetition)
аnаl  (Cyrillic а)                anal (homoglyph)
ＡＮＡＬ (fullwidth)              anal (unicode norm)
a n n n a a l                     anal (separator + repetition)
4-n-4-l                           anal (separator + leetspeak)
@n@n@a@l (with @ → a)            anal (mixed)
```

---

## 10. Implementation Roadmap

| Phase | Features | Est. effort |
|-------|----------|-------------|
| **Phase 1** | Aho-Corasick engine, exact matching, NFKC normalization, basic API | 2 weeks |
| **Phase 2** | Separator bypass, repetition normalization, upload word list | 1 week |
| **Phase 3** | Leetspeak decoder, homoglyph detection | 1 week |
| **Phase 4** | Fuzzy matching, risk scoring engine, detection report | 1.5 weeks |
| **Phase 5** | Batch API, webhook output, storage backend, stats endpoints | 1 week |
| **Phase 6** | Performance tuning, adversarial fuzzing, production hardening | 1 week |

**Total estimated effort:** ~7.5 weeks for a single developer.

---

## 11. Glossary

| Term | Definition |
|------|------------|
| **Aho-Corasick** | A multi-pattern string-matching algorithm that builds a trie with failure links for O(n) time. |
| **Homoglyph** | Different Unicode characters that look visually identical or very similar (e.g., Latin `a` vs Cyrillic `а`). |
| **Leetspeak** | Substitution of letters with visually similar numbers/symbols (e.g., `e` → `3`, `a` → `4`). |
| **NFKC** | Unicode Normalization Form KC — compatibility decomposition + canonical composition. |
| **Levenshtein distance** | Minimum number of single-character edits (insert, delete, substitute) to transform one string into another. |
| **Damerau-Levenshtein** | Levenshtein + transpositions of two adjacent characters. |
| **Separator bypass** | Inserting non-alphanumeric characters between letters to evade pattern matching. |
| **Risk scoring** | A composite metric that quantifies how "severe" a detection is based on word score, obfuscation method, and context. |
