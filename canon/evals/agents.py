"""The agents compared by the eval.

* `BaselineAgent`: naive RAG. BM25 keyword retrieval over the raw exports (CRM rows,
  Slack messages, contract texts), top-k chunks handed to the model.
* `HybridAgent`: a strong baseline without Canon: BM25 + fuzzy character n-gram retrieval,
  multi-query over every candidate customer span, rank fusion, Slack mentions resolved and
  messages dated.
* `OracleAgent`: perfect retrieval over the same raw exports: *every* raw chunk of the right
  customer (from the ground truth), nothing else. It separates "retrieval failed" from "the raw
  data itself is stale or contradictory". Harness-only, since it needs the answer key.
* `CanonAgent`: links the customer mentioned anywhere in the question with the MCP
  `get_customer` tool, routes by question type to `find_contract_terms`, `who_owns`
  or `get_customer`, and hands the model the structured tool result.

All use the same model; only the context differs.
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
from canon.evals.scoring import route
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


# ---------------------------------------------------------------- strong baseline


def readable_chunks(root: Path) -> list[tuple[str, str]]:
    """Raw chunks as a careful engineer would prepare them, without Canon: Slack user mentions
    replaced by names, and every Slack message stamped with its channel and date."""
    from datetime import UTC, datetime

    root = Path(root)
    users = {
        u["id"]: u.get("real_name") or u.get("name")
        for u in json.loads((root / "slack" / "users.json").read_text(encoding="utf-8"))
    }

    def names(text: str) -> str:
        return re.sub(r"<@(U\w+)>", lambda m: "@" + users.get(m.group(1), m.group(1)), text)

    chunks = [(loc, text) for loc, text in raw_chunks(root) if not loc.startswith("slack:")]
    for day in sorted((root / "slack").glob("*/*.json")):
        for msg in json.loads(day.read_text(encoding="utf-8")):
            when = datetime.fromtimestamp(float(msg["ts"]), UTC).date().isoformat()
            chunks.append(
                (
                    f"slack:{day.parent.name}/{day.stem}",
                    f"#{day.parent.name} {when}: {names(msg['text'])}",
                )
            )
    return chunks


def _char_ngrams(text: str, n: int = 3) -> Counter:
    grams: Counter = Counter()
    for word in _tokens(text):
        padded = f" {word} "
        grams.update(padded[i : i + n] for i in range(max(len(padded) - n + 1, 1)))
    return grams


class CharNgramIndex:
    """TF-IDF cosine over character trigrams: tolerant of typos, case, suffixes and spacing."""

    def __init__(self, docs: list[str]) -> None:
        grams = [_char_ngrams(d) for d in docs]
        df = Counter(g for d in grams for g in d)
        n = len(docs)
        self.idf = {g: math.log((1 + n) / (1 + c)) + 1 for g, c in df.items()}
        self.vecs = [self._weigh(d) for d in grams]

    def _weigh(self, grams: Counter) -> dict[str, float]:
        vec = {g: (1 + math.log(c)) * self.idf.get(g, 1.0) for g, c in grams.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {g: v / norm for g, v in vec.items()}

    def search(self, query: str, k: int) -> list[int]:
        q = self._weigh(_char_ngrams(query))
        scores = [
            (sum(w * vec.get(g, 0.0) for g, w in q.items()), i) for i, vec in enumerate(self.vecs)
        ]
        scores.sort(reverse=True)
        return [i for s, i in scores[:k] if s > 0]


class HybridAgent:
    """The strongest baseline we could build without Canon: lexical BM25 + fuzzy character
    n-gram retrieval, queried with the whole question *and* every candidate customer span
    (the same span heuristic Canon's linker uses), fused by reciprocal rank, top k chunks;
    Slack mentions resolved to names and messages dated."""

    name = "hybrid"

    def __init__(self, model: Model, data_dir: Path, k: int = 10, per_query: int = 20) -> None:
        self.model = model
        self.chunks = readable_chunks(data_dir)
        texts = [text for _, text in self.chunks]
        self.bm25 = BM25(texts)
        self.fuzzy = CharNgramIndex(texts)
        self.k, self.per_query = k, per_query

    async def run(self, question: str) -> AgentResult:
        fused: Counter = Counter()
        queries = [question, *candidate_spans(question, 6)]
        for query in queries:
            for ranking in (
                self.bm25.search(query, self.per_query),
                self.fuzzy.search(query, self.per_query),
            ):
                for rank, i in enumerate(ranking):
                    fused[i] += 1 / (60 + rank)
        hits = [i for i, _ in fused.most_common(self.k)]
        context = "\n---\n".join(self.chunks[i][1] for i in hits)
        trace = [f"{len(queries)} queries; retrieved {self.chunks[i][0]}" for i in hits[:3]]
        return AgentResult(self.model.answer(question, context), context, trace)


class OracleAgent:
    """Perfect retrieval: all raw chunks of the question's true customer, in source order."""

    name = "oracle"

    def __init__(self, model: Model, data_dir: Path, record_entity: dict[str, str]) -> None:
        self.model = model
        root = Path(data_dir)
        channels = json.loads((root / "slack" / "channels.json").read_text(encoding="utf-8"))
        if (root / "slack" / "groups.json").exists():
            channels += json.loads((root / "slack" / "groups.json").read_text(encoding="utf-8"))
        channel_id = {c["name"]: c["id"] for c in channels}
        self.by_entity: dict[str, list[tuple[str, str]]] = {}
        for locator, text in raw_chunks(root):
            kind, _, rest = locator.partition(":")
            rid = f"slack:{channel_id[rest.split('/')[0]]}" if kind == "slack" else locator
            if rid in record_entity:
                self.by_entity.setdefault(record_entity[rid], []).append((locator, text))

    async def run(self, question: str, entity_id: str | None = None) -> AgentResult:
        chunks = self.by_entity.get(entity_id or "", [])
        context = "\n---\n".join(text for _, text in chunks)
        trace = [f"oracle: {len(chunks)} raw chunks of {entity_id}"]
        return AgentResult(self.model.answer(question, context), context, trace)


# ---------------------------------------------------------------- canon

# Function words (EN / FR / Darija) that never start or end a company mention.
_STOPWORDS = """a an the of for to on in at is are was be do does did
    what what's whats who whos who's
    which when where how much many per our us we i my me you your their them they it its this that
    with and or from about can could should would will right now these days there please tell
    give check know need dial reach call before after since still same up soon exactly
    le la les l de des du d un une et ou est sont pour par sur dans chez avec qui que quel quelle
    quels quelles quand combien c ce cet cette ses son sa leur leurs nous on moi stp svp donne
    doit doivent dois envoyer courrier contrat contract annual annuel annuelle actuel current
    owner account compte date renewal renouvellement number numero phone telephone address
    adresse siege office offices head registered main value montant worth paying signed sign
    chkoun chkon li dyal daba f l b m3a wach imta ch7al kaykhalsou kaytkellef ghadi"""
STOPWORDS = frozenset(_STOPWORDS.split())


def candidate_spans(question: str, max_span: int) -> list[str]:
    words = [re.sub(r"['’]s$", "", w.strip("?؟!.,;:()\"'«»-–—")) for w in question.split()]
    words = [w for w in words if w]
    spans, seen = [], set()
    for i in range(len(words)):
        for n in range(1, max_span + 1):
            chunk = words[i : i + n]
            if len(chunk) < n:
                break
            if fold(chunk[0]) in STOPWORDS or fold(chunk[-1]) in STOPWORDS:
                continue
            span = " ".join(chunk)
            if span not in seen and len(span) >= 3:
                seen.add(span)
                spans.append(span)
    return spans


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
        """Entity linking by probing: try every span of up to `max_span` words (spans that
        start or end with a function word are skipped) with get_customer and keep the best
        match; on a tie, the longer span wins."""
        best: tuple[float, int, str] | None = None
        for span in candidate_spans(question, self.max_span):
            result = await self.client.call_tool(
                "get_customer", {"name": span, "caller": self.caller}
            )
            data = result.structured_content or {}
            if data.get("found"):
                n = len(span.split())
                cand = (data["customer"]["match_score"], n, data["customer"]["entity_id"])
                if best is None or cand[:2] > best[:2]:
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
        qtype = route(question)  # unsure -> the full profile, which has every field
        tool = TOOL_FOR_TYPE[qtype] if qtype else "get_customer"
        arg = "name" if tool == "get_customer" else "customer"
        result = await self.client.call_tool(tool, {arg: entity_id, "caller": self.caller})
        trace.append(f"called {tool}({entity_id})")
        context = json.dumps(result.structured_content, ensure_ascii=False)
        return AgentResult(self.model.answer(question, context), context, trace)
