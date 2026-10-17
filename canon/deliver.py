"""Client deliverables: the audit report as one printable HTML file, and an offline review page
where the client confirms or rejects borderline merges and downloads `overrides.json`.

Both are single self-contained files (inline CSS, no network, no server): they can be emailed,
opened from a USB key inside the client's network, and printed to PDF. All source text is
HTML-escaped, and data embedded for the review page is escaped for a `<script>` block.
"""

from __future__ import annotations

import html
import json
import re

from canon.audit import show_value
from canon.models import SourceRecord
from canon.resolve.pipeline import Overrides, ReviewItem

_CSS = """
:root { --fg:#1d2433; --muted:#5b6475; --line:#d9dee7; --bg:#ffffff; --head:#f3f5f9;
        --accent:#2457c5; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 15px/1.5 -apple-system, "Segoe UI", Roboto, "Noto Sans", "Noto Sans Arabic",
       sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 8px; }
h2 { font-size: 19px; margin: 36px 0 10px; padding-top: 12px; border-top: 1px solid var(--line); }
p, li { color: var(--fg); }
em { color: var(--muted); }
code { background: var(--head); padding: 1px 4px; border-radius: 3px; font-size: 13px; }
.table { overflow-x: auto; margin: 8px 0 16px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { border: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: var(--head); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.pair { border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin: 14px 0; }
.pair.done { border-color: var(--accent); }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 700px) { .cols { grid-template-columns: 1fr; } }
.rec { background: var(--head); border-radius: 6px; padding: 10px; font-size: 14px;
       overflow-wrap: anywhere; }
.rec b { display: block; font-size: 15px; margin-bottom: 4px; }
.meta { color: var(--muted); font-size: 13px; margin: 8px 0; }
.choices { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.choices label { border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px;
                 cursor: pointer; }
.choices input { margin-right: 6px; }
.bar { position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid var(--line);
       padding: 10px 0; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
       z-index: 1; }
button { font: inherit; padding: 8px 14px; border-radius: 6px; border: 1px solid var(--accent);
         background: var(--accent); color: #fff; cursor: pointer; }
@media print { .bar, .choices { display: none; } h2 { break-after: avoid; }
               tr { break-inside: avoid; } }
"""


def _page(title: str, body: str, script: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
        f"<body><main>{body}</main>{script}</body></html>\n"
    )


# ---------------------------------------------------------------- markdown subset -> HTML

_INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])"), r"<em>\1</em>"),
]


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    return out


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def markdown_to_html(md: str) -> str:
    """The subset `render_audit` writes: #/## headings, pipe tables, `-` lists, paragraphs,
    `code`, **bold**, *italics*. Everything is escaped before formatting is applied."""
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
            i += 1
        elif line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            head, body = _cells(rows[0]), [r for r in rows[1:] if not re.fullmatch(r"[|\-: ]+", r)]
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            trs = "".join(
                "<tr>"
                + "".join(
                    f'<td class="num">{_inline(c)}</td>'
                    if re.fullmatch(r"[\d.,% ]+", c)
                    else f"<td>{_inline(c)}</td>"
                    for c in _cells(r)
                )
                + "</tr>"
                for r in body
            )
            out.append(f'<div class="table"><table><thead><tr>{th}</tr></thead>{trs}</table></div>')
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append(f"<ul>{''.join(items)}</ul>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "- ")):
                para.append(lines[i])
                i += 1
            out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def render_audit_html(markdown_report: str) -> str:
    return _page("MCP Readiness Audit", markdown_to_html(markdown_report))


# ---------------------------------------------------------------- review page

_SHOWN = ("source", "locator", "city", "address", "phone", "email", "domain", "tax_id")


def _summary(rec: SourceRecord | None, rid: str) -> dict:
    if rec is None:
        return {"record_id": rid}
    out = {"record_id": rid, "name": rec.name, "other names": ", ".join(rec.alt_names) or None}
    out |= {k: getattr(rec, k) for k in _SHOWN}
    facts = {
        f.field: show_value(f.value) for f in rec.facts if f.field in ("owner", "contract_value")
    }
    return {k: v for k, v in (out | facts).items() if v not in (None, "")}


def _script_json(data) -> str:
    """JSON that cannot close or open tags inside a <script> block."""
    text = json.dumps(data, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_REVIEW_JS = """
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const KEY = "canon-review-" + DATA.run;
let answers = {};
try { answers = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
function save() { try { localStorage.setItem(KEY, JSON.stringify(answers)); } catch (e) {} }
function count() {
  const n = Object.values(answers).filter(v => v === "same" || v === "different").length;
  document.getElementById("count").textContent = n + " of " + DATA.items.length + " answered";
}
document.querySelectorAll("input[type=radio]").forEach(input => {
  if (answers[input.name] === input.value) {
    input.checked = true; input.closest(".pair").classList.add("done");
  }
  input.addEventListener("change", () => {
    answers[input.name] = input.value; save(); count();
    input.closest(".pair").classList.add("done");
  });
});
count();
document.getElementById("download").addEventListener("click", () => {
  const out = {must_link: DATA.existing.must_link.slice(),
               cannot_link: DATA.existing.cannot_link.slice()};
  DATA.items.forEach((item, i) => {
    const a = answers["p" + i];
    if (a === "same") out.must_link.push([item.left, item.right]);
    if (a === "different") out.cannot_link.push([item.left, item.right]);
  });
  const blob = new Blob([JSON.stringify(out, null, 2)], {type: "application/json"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob); link.download = "overrides.json"; link.click();
});
</script>
"""


def render_review_html(
    items: list[ReviewItem],
    records: dict[str, SourceRecord],
    existing: Overrides | None = None,
    run: str = "",
) -> str:
    existing = existing or Overrides()
    blocks = []
    for i, item in enumerate(items):
        cols = []
        for rid in (item.left, item.right):
            summary = _summary(records.get(rid), rid)
            title = html.escape(str(summary.pop("name", rid)))
            rows = "".join(
                f"<div>{html.escape(k.replace('_', ' '))}: {html.escape(str(v))}</div>"
                for k, v in summary.items()
            )
            cols.append(f'<div class="rec"><b>{title}</b>{rows}</div>')
        model = "merged" if item.decision == "merged" else "kept apart"
        choices = "".join(
            f'<label><input type="radio" name="p{i}" value="{v}">{label}</label>'
            for v, label in (
                ("same", "Same customer"),
                ("different", "Different customers"),
                ("unsure", "Not sure"),
            )
        )
        blocks.append(
            f'<section class="pair"><div class="cols">{"".join(cols)}</div>'
            f'<div class="meta">Canon {model} these ({item.probability:.0%} likely the same): '
            f"{html.escape(item.why)}</div>"
            f'<div class="choices">{choices}</div></section>'
        )
    data = {
        "run": run,
        "items": [{"left": i.left, "right": i.right} for i in items],
        "existing": existing.model_dump(mode="json"),
    }
    body = (
        "<h1>Confirm customer matches</h1>"
        "<p>Each card shows two records that may describe the same customer. Pick an answer "
        "for the ones you know, then download <code>overrides.json</code> and send it back. Your "
        "answers are applied on every later run. Nothing leaves this page until you download "
        "the file.</p>"
        '<div class="bar"><button id="download" type="button">Download overrides.json</button>'
        '<span id="count"></span></div>'
        + ("".join(blocks) or "<p>No borderline matches in this run.</p>")
        + f'<script type="application/json" id="data">{_script_json(data)}</script>'
    )
    return _page("Confirm customer matches", body, _REVIEW_JS)
