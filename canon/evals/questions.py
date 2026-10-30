"""Eval questions: loaded from a file (`load_questions`), or the synthetic 40-question set derived
deterministically from the hidden ground truth (`build_questions`).

Questions mix English, French and Darija phrasing and refer to customers the way
people do: aliases, Arabic script, typos, legal suffixes, Darija "chrikat". The
customer mention always ends the question (agents may rely on that for entity
linking). Expected answers are the ground-truth *current* values.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from pydantic import BaseModel

from canon.synth.seeds import SEEDS

QUESTION_TYPES = {
    "contract_value": 10,
    "renewal_date": 10,
    "owner": 10,
    "phone": 5,
    "address": 5,
}

TEMPLATES = {
    "contract_value": [
        "What is the current annual contract value for {n}?",
        "Quel est le montant annuel actuel du contrat de {n} ?",
        "Ch7al kaykhalsou f l3am daba, {n}?",
    ],
    "renewal_date": [
        "When is the contract renewal date for {n}?",
        "Quelle est la date de renouvellement du contrat de {n} ?",
        "Imta ghadi ytjedded contrat dyal {n}?",
    ],
    "owner": [
        "Who is the account owner for {n}?",
        "Qui est le responsable du compte {n} ?",
        "Chkoun l'owner dyal {n}?",
    ],
    "phone": [
        "What is the main phone number of {n}?",
        "Quel est le numéro de téléphone de {n} ?",
    ],
    "address": [
        "What is the registered office address of {n}?",
        "Quelle est l'adresse du siège social de {n} ?",
    ],
}

ANSWER_FIELD = {
    "contract_value": "contract_value",
    "renewal_date": "renewal_date",
    "owner": "owner",
    "phone": "phone",
    "address": "address",
}


class Question(BaseModel):
    id: str
    type: str
    question: str
    entity_id: str | None = None  # needed only for the oracle agent and failure analysis
    mention: str = ""
    mention_style: str = "hand-written"
    expected: str | float | int


def load_questions(path: Path, truth: dict | None = None) -> list[Question]:
    """Questions from a file: a JSON list, or {"questions": [...]}. A question without
    `expected` takes it from the ground truth (`truth["entities"][entity_id]`). This is how a
    client's own question set plugs in: id, type, question, expected."""
    path = Path(path)
    if path.suffix.lower() in (".csv", ".xlsx"):
        rows = _spreadsheet_questions(path)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data["questions"] if isinstance(data, dict) else data
    out = []
    for row in rows:
        if "expected" not in row:
            if truth is None or not row.get("entity_id"):
                raise ValueError(f"{row.get('id')}: no expected answer and no ground truth")
            row = {
                **row,
                "expected": truth["entities"][row["entity_id"]][ANSWER_FIELD[row["type"]]],
            }
        out.append(Question.model_validate(row))
    return out


def _spreadsheet_questions(path: Path) -> list[dict]:
    """A client's question sheet: columns id (optional), type, question, expected.

    Expected answers are typed by people, so they are parsed like any other source value and
    refused (an error naming the row) rather than guessed: an amount must parse to one number,
    a date to one unambiguous calendar day."""
    from canon.ingest.crm import read_rows
    from canon.ingest.parsing import parse_amount, parse_date

    out = []
    for i, row in enumerate(read_rows(path), start=2):  # row 1 is the header
        row = {str(k).strip().lower(): v for k, v in row.items() if k}
        if not any(str(v).strip() for v in row.values() if v is not None):
            continue
        qid = str(row.get("id") or f"row{i}")
        qtype = str(row.get("type") or "").strip()
        if qtype not in QUESTION_TYPES:
            raise ValueError(f"{path.name} {qid}: type must be one of {sorted(QUESTION_TYPES)}")
        expected = row.get("expected")
        if expected in (None, ""):
            raise ValueError(f"{path.name} {qid}: no expected answer")
        if qtype == "contract_value":
            parsed = parse_amount(expected, expected_currency=None)
            if not parsed.ok:
                raise ValueError(f"{path.name} {qid}: expected amount refused ({parsed.reason})")
            expected = parsed.value.value
        elif qtype == "renewal_date":
            parsed = parse_date(expected)
            if not parsed.ok or "day_month_order_by_convention" in parsed.warnings:
                reason = parsed.reason or "ambiguous_day_month_order: write it as YYYY-MM-DD"
                raise ValueError(f"{path.name} {qid}: expected date refused ({reason})")
            expected = parsed.value.isoformat()
        else:
            expected = str(expected).strip()
        out.append(
            {"id": qid, "type": qtype, "question": str(row["question"]), "expected": expected}
        )
    return out


def _typo(rng: random.Random, text: str) -> str:
    words = text.split()
    i = max(range(len(words)), key=lambda k: len(words[k]))
    w = words[i]
    if len(w) >= 5:
        pos = rng.randint(1, len(w) - 3)
        words[i] = w[:pos] + w[pos + 1] + w[pos] + w[pos + 2 :]
    return " ".join(words)


def _mention(rng: random.Random, entity: dict) -> tuple[str, str]:
    from canon.synth.west import WEST_SEEDS  # local: west imports the generator, which imports us

    west = any(s.key == entity["key"] for s in WEST_SEEDS)
    seed = next(s for s in (*SEEDS, *WEST_SEEDS) if s.key == entity["key"])
    styles = ["canonical", "legal", "lower", "typo", "darija"]
    if seed.aliases:
        styles.append("alias")
    if seed.arabic:
        styles.append("arabic")
    style = rng.choice(styles)
    if style == "legal":
        forms = ["Inc", "LLC", "Corp.", "Inc."] if west else ["SARL", "S.A.", "Ltd", "S.A.R.L."]
        return f"{seed.name} {rng.choice(forms)}", style
    if style == "lower":
        return seed.name.lower(), style
    if style == "typo":
        return _typo(rng, seed.name), style
    if style == "darija":  # the informal way people name a company in chat
        return (f"the {seed.name} team" if west else f"chrikat {seed.name}"), style
    if style == "alias":
        return rng.choice(seed.aliases), style
    if style == "arabic":
        return seed.arabic, style
    return seed.name, style


def build_questions(truth: dict, seed: int = 4040) -> list[Question]:
    rng = random.Random(seed)
    entity_ids = sorted(truth["entities"])
    questions: list[Question] = []
    for qtype, count in QUESTION_TYPES.items():
        for eid in sorted(rng.sample(entity_ids, count)):
            entity = truth["entities"][eid]
            mention, style = _mention(rng, entity)
            text = rng.choice(TEMPLATES[qtype]).format(n=mention)
            questions.append(
                Question(
                    id=f"Q{len(questions) + 1:02d}",
                    type=qtype,
                    question=text,
                    entity_id=eid,
                    mention=mention,
                    mention_style=style,
                    expected=entity[ANSWER_FIELD[qtype]],
                )
            )
    return questions
