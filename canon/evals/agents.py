"""The two agents compared by the eval.

* `BaselineAgent`: naive RAG. BM25 keyword retrieval over the raw exports (CRM rows,
  Slack messages, contract texts), top-k chunks handed to the model.
* `CanonAgent`: links the customer mentioned in the question with the MCP
  `get_customer` tool, routes by question type to `find_contract_terms`, `who_owns`
  or `get_customer`, and hands the model the structured tool result.

Both use the same model and question router; only the context differs.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from mcp import Client

from canon.evals.models import Model
from canon.evals.scoring import classify
from canon.resolve.normalize import fold


@dataclass
class AgentResult:
    answer: str
    context: str
    trace: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- baseline


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", fold(text))


def raw_chunks(root: Path) -> list[tuple[str, str]]:
    """(locator, text) chunks from the raw sources. Never reads ground_truth/."""
    root = Path(root)
    chunks = []
    for row in json.loads((root / "crm" / "accounts.json").read_text(encoding="utf-8")):
        chunks.append((f"crm:{row['Id']}", json.dumps(row, ensure_ascii=False)))
    for day in sorted((root / "slack").glob("*/*.json")):
        for msg in json.loads(day.read_text(encoding="utf-8")):
            text = f"#{day.parent.name}: {msg['text']}"
            chunks.append((f"slack:{day.parent.name}/{day.stem}", text))
    for path in sorted((root / "contracts").glob("*.txt")):
        chunks.append((f"contract:{path.stem}", path.read_text(encoding="utf-8")))
    return chunks


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = [_tokens(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def search(self, query: str, k: int) -> list[int]:
        q = set(_tokens(query))
        scores = []
        for i, (tf, doc) in enumerate(zip(self.tf, self.docs, strict=True)):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += (
                        self.idf[t]
                        * f
                        * (self.k1 + 1)
                        / (f + self.k1 * (1 - self.b + self.b * len(doc) / self.avg))
                    )
            scores.append((s, i))
        scores.sort(reverse=True)
        return [i for s, i in scores[:k] if s > 0]


class BaselineAgent:
    name = "baseline"

    def __init__(self, model: Model, data_dir: Path, k: int = 5) -> None:
        self.model = model
        self.chunks = raw_chunks(data_dir)
        self.index = BM25([text for _, text in self.chunks])
        self.k = k

    async def run(self, question: str) -> AgentResult:
        hits = self.index.search(question, self.k)
        context = "\n---\n".join(self.chunks[i][1] for i in hits)
        trace = [f"retrieved {self.chunks[i][0]}" for i in hits]
        return AgentResult(self.model.answer(question, context), context, trace)


# ---------------------------------------------------------------- canon

TOOL_FOR_TYPE = {
    "contract_value": "find_contract_terms",
    "renewal_date": "find_contract_terms",
    "owner": "who_owns",
    "phone": "get_customer",
    "address": "get_customer",
}


class CanonAgent:
    name = "canon"

    def __init__(self, model: Model, client: Client, caller: str, max_span: int = 6) -> None:
        self.model = model
        self.client = client
        self.caller = caller
        self.max_span = max_span

    async def link(self, question: str, trace: list[str]) -> str | None:
        """Entity linking by probing: try the question's trailing spans with get_customer
        and keep the best match (the eval's questions end with the customer mention)."""
        words = question.strip().rstrip("?؟ ").replace(",", " ").split()
        best: tuple[float, int, str] | None = None
        for n in range(1, min(self.max_span, len(words)) + 1):
            span = " ".join(words[-n:])
            result = await self.client.call_tool(
                "get_customer", {"name": span, "caller": self.caller}
            )
            data = result.structured_content or {}
            if data.get("found"):
                score = data["customer"]["match_score"]
                cand = (score, n, data["customer"]["entity_id"])
                if best is None or cand[0] > best[0]:
                    best = cand
        if best:
            trace.append(f"linked to {best[2]} (score {best[0]:.2f}, span of {best[1]} words)")
            return best[2]
        trace.append("no customer linked")
        return None

    async def run(self, question: str) -> AgentResult:
        trace: list[str] = []
        entity_id = await self.link(question, trace)
        if entity_id is None:
            return AgentResult(self.model.answer(question, "{}"), "{}", trace)
        tool = TOOL_FOR_TYPE[classify(question)]
        arg = "name" if tool == "get_customer" else "customer"
        result = await self.client.call_tool(tool, {arg: entity_id, "caller": self.caller})
        trace.append(f"called {tool}({entity_id})")
        context = json.dumps(result.structured_content, ensure_ascii=False)
        return AgentResult(self.model.answer(question, context), context, trace)
