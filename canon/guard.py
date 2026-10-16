"""Prompt-injection guard for source text returned to agents.

Canon returns text written by third parties (chat messages, contract lines, CRM fields) to an LLM
agent. Text that reads like instructions to the model is withheld, and the response says so, so the
agent can still cite the source without reading the payload. Detection is a pattern list, not a
classifier: it catches the common phrasings in FR / EN / Darija and markup that imitates chat roles,
and is meant to be one layer, not the only one (the server instructions also tell the agent to treat
source text as data).
"""

from __future__ import annotations

import re
import unicodedata

PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "ignore_instructions",
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|prompts?|rules|guidelines)\b",
    ),
    (
        "ignore_instructions_fr",
        r"\b(ignore[rz]?|oublie[rz]?|ne tiens? pas compte)\b.{0,40}"
        r"\b(instructions?|consignes?|regles)\b",
    ),
    (
        "role_markup",
        r"<\|?(im_start|im_end|system|assistant)\|?>|^\s*(system|assistant)\s*:|\[/?inst\]",
    ),
    ("system_prompt", r"\b(system prompt|prompt systeme|developer message)\b"),
    ("persona_switch", r"\byou are now\b|\btu es maintenant\b|\bact as\b|\bpretend to be\b"),
    (
        "tool_hijack",
        r"\b(call|use|invoke|appelle|utilise)\b.{0,30}\b(tool|function|outil)\b.{0,40}"
        r"\b(with|avec|caller|admin)\b",
    ),
    (
        "exfiltration",
        r"\b(send|email|post|forward|envoie|transfere)\b.{0,60}"
        r"\b(https?://|www\.|@[\w-]+\.\w+|password|mot de passe|api key|token)",
    ),
    (
        "answer_override",
        r"\b(always|toujours)\b.{0,30}\b(answer|reply|respond|reponds?|dis)\b"
        r"|\b(tell the user|dis a l'utilisateur)\b",
    ),
    ("darija_ignore", r"\b(nsa|tnsa|matdirch)\b.{0,30}\b(instructions?|lqawa3id)\b"),
)
_COMPILED = [(name, re.compile(p, re.IGNORECASE | re.MULTILINE)) for name, p in PATTERNS]
WITHHELD = "[withheld: this source text looks like instructions to an AI model]"


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[​-‏‪-‮⁦-⁩]", "", text)  # zero-width/bidi tricks


def injection_rule(text: object) -> str | None:
    """Name of the first rule the text trips, or None."""
    if not isinstance(text, str) or len(text) < 12:
        return None
    folded = _fold(text)
    return next((name for name, rx in _COMPILED if rx.search(folded)), None)


def screen(text: str | None, max_chars: int = 300) -> tuple[str | None, str | None]:
    """(text safe to return, rule that fired). Long text is truncated, flagged text withheld."""
    if text is None:
        return None, None
    rule = injection_rule(text)
    if rule:
        return WITHHELD, rule
    return (text if len(text) <= max_chars else text[: max_chars - 1] + "…"), None
