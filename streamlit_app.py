import streamlit as st
import re
import ollama
from collections import defaultdict

OLLAMA_MODEL = "qwen2.5:0.5b"

# -----------------------------
# EXTENDED WORD LIST (sample)
# -----------------------------
DEFAULT_WORDS = [
    "sex",
    "anal",
    "porn",
    "nude",
    "fuck",
    "bitch",
    "asshole",
    "boobs",
    "penis",
    "vagina",
    "dick",
    "cock",
    "pussy",
    "shit",
    "fuck",
    "motherfucker",
    "slut",
    "whore",
    "ass",
    "blowjob",
    "handjob",
    "orgasm",
    "cum",
    "naked",
]


# -----------------------------
# NORMALIZATION (anti-bypass)
# -----------------------------
def normalize(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    text = re.sub(r"(.)\1+", r"\1", text)
    return text


# -----------------------------
# RULE DETECTION
# -----------------------------
def rule_detect(text, words):
    norm_text = normalize(text)

    hits = []
    for w in words:
        if normalize(w) in norm_text:
            hits.append(w)

    return hits


# -----------------------------
# HIGHLIGHT MATCHES
# -----------------------------
def highlight_text(text, matches):
    def replacer(match):
        return f"🔴{match.group(0)}🔴"

    pattern = r"\b(" + "|".join(map(re.escape, matches)) + r")\b"

    try:
        return re.sub(pattern, replacer, text, flags=re.IGNORECASE)
    except:
        return text


# -----------------------------
# OLLAMA ANALYSIS
# -----------------------------
def ollama_check(text):

    prompt = f"""
You are a TikTok-style real-time content moderation system.

Detect:
- sexual content
- profanity
- harassment
- violence
- abuse

Even if words are disguised (f u c k, s@x, b r e a s t), detect them.

Return ONLY JSON:

{{
  "sensitive": true,
  "category": "sexual|abuse|profanity|violence|safe",
  "risk_score": 0-100,
  "reason": "short explanation"
}}

TEXT:
{text}
"""

    res = ollama.chat(
        model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}]
    )

    return res["message"]["content"]


# -----------------------------
# STREAMLIT UI (LIVE MODE)
# -----------------------------
st.set_page_config(page_title="TikTok Moderation", layout="wide")

st.title("🔴 TikTok-Style Live Moderation System")

st.markdown("Type below — moderation happens instantly like TikTok comments")

text = st.text_area("Live Input", height=150)

# Auto-run on typing (simulate live behavior)
if text:

    # ---------------- RULE CHECK ----------------
    rule_hits = rule_detect(text, DEFAULT_WORDS)

    risk_score = 0
    categories = defaultdict(int)

    if rule_hits:
        risk_score = 100
        categories["rule_based"] = len(rule_hits)

        st.error("🚨 Rule-Based Violation Detected")

        st.write("Matched Words:", rule_hits)

        st.markdown("### Highlighted Text")

        st.markdown(highlight_text(text, rule_hits))

        st.metric("Risk Score", "100")

    else:
        st.info("No rule match → AI moderation running...")

        try:
            result = ollama_check(text)

            st.subheader("🤖 Ollama Analysis")

            st.code(result, language="json")

            st.warning("AI moderation used (slower but smarter)")

        except Exception as e:
            st.error(f"Ollama error: {str(e)}")

# -----------------------------
# SIDEBAR CONFIG
# -----------------------------
st.sidebar.title("System Controls")

st.sidebar.write("Model:", OLLAMA_MODEL)
st.sidebar.write("Rule Words:", len(DEFAULT_WORDS))

st.sidebar.markdown("""
### Modes:
- 🔴 Rule Engine (instant block)
- 🤖 Ollama AI (context-aware)
""")
