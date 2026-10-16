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


# Providers that expose an OpenAI-compatible Chat Completions API:
# name -> (base URL, environment variable holding the key).
OPENAI_COMPATIBLE_PRESETS = {
    "baseten": ("https://inference.baseten.co/v1", "BASETEN_API_KEY"),
}
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _http_post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OpenAICompatibleModel:
    """Any OpenAI-compatible chat endpoint (e.g. Baseten Model APIs serving open models).

    The API key is read from an environment variable at call time and never stored
    in config, logs or reports.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        post=_http_post_json,
    ) -> None:
        if not model:
            raise ValueError("model id is required (e.g. --model-id <provider model slug>)")
        self.model = model
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._post = post

    @classmethod
    def preset(cls, provider: str, model: str, **kwargs) -> OpenAICompatibleModel:
        base_url, env = OPENAI_COMPATIBLE_PRESETS[provider]
        return cls(model, base_url, env, **kwargs)

    def answer(self, question: str, context: str) -> str:
        import os

        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"Set the {self.api_key_env} environment variable")
        data = self._post(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "temperature": 0,
                "max_tokens": self.max_tokens,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"<context>\n{context}\n</context>\n\nQuestion: {question}",
                    },
                ],
            },
            {"Authorization": f"Bearer {key}"},
            self.timeout,
        )
        text = (data["choices"][0]["message"].get("content") or "").strip()
        text = _THINK_RE.sub("", text).strip()  # reasoning models may inline their thinking
        return text or "unknown"
