"""Model adapters. An agent only needs `answer(question, context) -> str`.

* `StubModel`: deterministic, offline, used in CI. It reads the context the way a
  literal-minded reader would: from structured JSON it takes the `value` of the asked
  field, and from raw text it takes the first matching value in the highest-ranked
  chunk. It measures what the *retrieved context* supports, not model reasoning.
* `ClaudeModel`: the same interface over the Anthropic Messages API (optional
  `claude` extra; needs credentials).
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from canon.evals.scoring import classify
from canon.ingest.common import find_phones, normalize_phone, parse_date, parse_money

SYSTEM_PROMPT = (
    "You answer questions about a company's customers using only the provided context. "
    "Reply with only the answer value: an amount with currency, a date (YYYY-MM-DD), a "
    "person's name, a phone number or an address. If the context does not contain the "
    "answer, reply exactly: unknown. When the context marks values as superseded, archived, "
    "or alternatives, or gives confidence scores, answer with the current value."
)

FIELD_FOR_TYPE = {
    "contract_value": "contract_value",
    "renewal_date": "renewal_date",
    "owner": "owner",
    "phone": "phone",
    "address": "address",
}

# Raw-text extraction patterns per question type, tried in order inside each chunk.
RAW_PATTERNS = {
    "contract_value": (
        r'"Annual Contract Value":\s*"?([^",\n}]+)',
        r"montant annuel est fix[ée] [àa]\s*([\d ., ]+\s*MAD)",
        r"annual fee is\s*([\d,. ]+\s*MAD)",
        r"(\d[\d .,]*\s*k?\s*(?:MAD|DH))",
    ),
    "renewal_date": (
        r'"Renewal Date":\s*"([^"]+)"',
        r"(?:renouvellement|Renewal)[^\n]*?(\d{1,2}/\d{1,2}/\d{4})",
    ),
    "owner": (r'"Owner":\s*"([^"]+)"',),
    "phone": (r'"Phone":\s*"([^"]+)"', r"T[ée]l\s*:\s*([+\d][\d ()\-.]{7,})"),
    "address": (
        r'"Billing Street":\s*"([^"]+)"',
        r"^(?:Siège social|Registered office)\s*:\s*([^,\n]+)",
    ),
}


class Model(Protocol):
    name: str

    def answer(self, question: str, context: str) -> str: ...


def _find_field(obj, field: str):
    if isinstance(obj, dict):
        if obj.get("field") == field and "value" in obj:
            return obj["value"]
        for v in obj.values():
            found = _find_field(v, field)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_field(v, field)
            if found is not None:
                return found
    return None


def _clean(qtype: str, raw: str) -> str | None:
    raw = raw.strip()
    if qtype == "contract_value":
        value = parse_money(raw)
        return f"{value:.0f} MAD" if value else None
    if qtype == "renewal_date":
        d = parse_date(raw)
        return d.isoformat() if d else None
    if qtype == "phone":
        return normalize_phone(raw) or (find_phones(raw) or [None])[0]
    return raw or None


class StubModel:
    name = "stub"

    def answer(self, question: str, context: str) -> str:
        qtype = classify(question)
        try:
            data = json.loads(context)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            value = _find_field(data, FIELD_FOR_TYPE[qtype])
            return "unknown" if value is None else str(value)
        for chunk in context.split("\n---\n"):  # chunks arrive in rank order
            for pattern in RAW_PATTERNS[qtype]:
                m = re.search(pattern, chunk, re.MULTILINE | re.IGNORECASE)
                if m:
                    cleaned = _clean(qtype, m.group(1))
                    if cleaned:
                        return cleaned
        return "unknown"


class ClaudeModel:
    """Claude via the Anthropic SDK (`uv sync --extra claude`; credentials from env/profile)."""

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "low", client=None) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover - depends on the optional extra
                raise RuntimeError("Install the optional extra: uv sync --extra claude") from e
            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.name = model

    def answer(self, question: str, context: str) -> str:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # re-run a refused request on a fallback model
            output_config={"effort": self.effort},
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"<context>\n{context}\n</context>\n\nQuestion: {question}",
                }
            ],
        )
        if response.stop_reason == "refusal":
            return "unknown"
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or "unknown"
