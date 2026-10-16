"""The 40-question eval set, derived deterministically from the hidden ground truth.

Questions mix English, French and Darija phrasing and refer to customers the way
people do: aliases, Arabic script, typos, legal suffixes, Darija "chrikat". The
customer mention always ends the question (agents may rely on that for entity
linking). Expected answers are the ground-truth *current* values.
"""

from __future__ import annotations

import random

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
    entity_id: str
    mention: str
    mention_style: str
    expected: str | float | int


def _typo(rng: random.Random, text: str) -> str:
    words = text.split()
    i = max(range(len(words)), key=lambda k: len(words[k]))
    w = words[i]
    if len(w) >= 5:
        pos = rng.randint(1, len(w) - 3)
        words[i] = w[:pos] + w[pos + 1] + w[pos] + w[pos + 2 :]
    return " ".join(words)


def _mention(rng: random.Random, entity: dict) -> tuple[str, str]:
    seed = next(s for s in SEEDS if s.key == entity["key"])
    styles = ["canonical", "legal", "lower", "typo", "darija"]
    if seed.aliases:
        styles.append("alias")
    if seed.arabic:
        styles.append("arabic")
    style = rng.choice(styles)
    if style == "legal":
        return f"{seed.name} {rng.choice(['SARL', 'S.A.', 'Ltd', 'S.A.R.L.'])}", style
    if style == "lower":
        return seed.name.lower(), style
    if style == "typo":
        return _typo(rng, seed.name), style
    if style == "darija":
        return f"chrikat {seed.name}", style
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
