"""Lightweight lexicon sentiment analysis for product comments.

Comments on this platform arrive in Tetum, Portuguese, and English (often
mixed), so off-the-shelf English-only analyzers misread most of them. This
module scores text against a trilingual lexicon with simple negation
handling ("la diak", "not good", "não gosto") and emoji support.

Labels: "positive" | "neutral" | "negative".
"""

import re

POSITIVE = {
    # English
    "good", "great", "excellent", "amazing", "awesome", "love", "like",
    "nice", "perfect", "best", "beautiful", "fantastic", "wonderful", "cool",
    "cheap", "fast", "recommend", "recommended", "quality", "happy",
    "thanks", "thank",
    # Tetum
    "diak", "di'ak", "furak", "kapas", "gosta", "baratu", "lalais",
    "kontente", "obrigadu", "obrigada", "kmanek",
    # Portuguese
    "bom", "boa", "otimo", "ótimo", "excelente", "lindo", "linda", "barato",
    "barata", "rapido", "rápido", "perfeito", "perfeita", "recomendo",
    "gostei", "maravilhoso",
}

NEGATIVE = {
    # English
    "bad", "poor", "terrible", "awful", "horrible", "hate", "worst",
    "broken", "fake", "scam", "slow", "expensive", "damaged", "disappointed",
    "disappointing", "problem", "wrong", "ugly", "rude", "late",
    # Tetum
    "aat", "ladiak", "ladi'ak", "karun", "bosok", "estraga", "estragadu",
    "susar", "triste", "tarde",
    # Portuguese
    "mau", "ma", "má", "ruim", "pessimo", "péssimo", "caro", "cara", "lento",
    "lenta", "partido", "estragado", "falso", "falsa", "problema", "nunca",
}

# Negation words flip the polarity of a sentiment word appearing within the
# next two tokens: "la diak" (Tetum: not good) → negative.
NEGATIONS = {
    "not", "no", "never", "dont", "don't", "isnt", "isn't", "wasnt", "wasn't",
    "la", "lae", "la'os", "laos", "seidauk",
    "nao", "não", "nem",
}

POSITIVE_EMOJI = set("👍😊😍❤🥰🙂😀😃😄💯🔥✨🌟⭐👌🎉")
NEGATIVE_EMOJI = set("👎😞😡🤬😠☹🙁😢😭💔🤮")

_TOKEN_RE = re.compile(r"[a-zà-ÿ']+", re.IGNORECASE)


def analyze(text):
    """Return (label, score) for the given text.

    Score is the signed count of sentiment hits (negations flip the sign of
    the word they precede); label is positive/negative when the score is
    non-zero, neutral otherwise.
    """
    if not text:
        return "neutral", 0.0

    score = 0.0
    for ch in text:
        if ch in POSITIVE_EMOJI:
            score += 1
        elif ch in NEGATIVE_EMOJI:
            score -= 1

    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    pending_negation = 0  # tokens remaining in which a negation can still act
    for token in tokens:
        if token in NEGATIONS:
            pending_negation = 3  # flips the next sentiment word within 2 tokens
            continue
        if pending_negation:
            pending_negation -= 1

        polarity = 0
        if token in POSITIVE:
            polarity = 1
        elif token in NEGATIVE:
            polarity = -1
        if not polarity:
            continue
        if pending_negation:
            polarity = -polarity
            pending_negation = 0  # a negation is consumed by the word it flips
        score += polarity

    if score > 0:
        return "positive", score
    if score < 0:
        return "negative", score
    return "neutral", 0.0
