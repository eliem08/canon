"""Build test documents (text PDFs, scanned PDFs, DOCX, XLSX) from plain text and rows.

Used by the tests and `scripts/ocr_benchmark.py` to exercise the documents connector on synthetic
contracts. Text PDFs and DOCX need only the standard library; scans need Pillow.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
)


def _pdf_string(line: str) -> bytes:
    raw = line.encode("cp1252", "replace")  # Helvetica + WinAnsi: Latin text only
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def text_pdf(pages: list[str]) -> bytes:
    """A minimal PDF with a real text layer (one Helvetica text block per page)."""
    objects: list[bytes] = []
    kids = []
    font_id = 3
    for i, page in enumerate(pages):
        content = (
            b"BT /F1 10 Tf 14 TL 40 800 Td "
            + b" ".join(_pdf_string(line) + b" Tj T*" for line in page.split("\n"))
            + b" ET"
        )
        page_id, content_id = 4 + 2 * i, 5 + 2 * i
        kids.append(page_id)
        objects.append(
            f"{page_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >> endobj\n".encode()
        )
        objects.append(
            f"{content_id} 0 obj << /Length {len(content)} >> stream\n".encode()
            + content
            + b"\nendstream endobj\n"
        )
    head = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        f"2 0 obj << /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
        f"/Count {len(kids)} >> endobj\n".encode(),
        b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >> endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in head + objects:
        offsets.append(len(out))
        out += obj
    xref = len(out)
    out += f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer << /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def find_font() -> str | None:
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


def render_page(text: str, font_path: str, size: int = 26, noise: float = 0.0, seed: int = 0):
    """Render text as a white A4-ish page image (about 200 dpi), like a clean scan."""
    import random

    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(font_path, size)
    img = Image.new("L", (1654, 2339), 255)
    draw = ImageDraw.Draw(img)
    y = 80
    for line in text.split("\n"):
        rtl = any("؀" <= c <= "ۿ" for c in line)
        if rtl:
            width = draw.textlength(line, font=font, direction="rtl")
            draw.text((1654 - 80 - width, y), line, font=font, fill=0, direction="rtl")
        else:
            draw.text((80, y), line, font=font, fill=0)
        y += int(size * 1.6)
    if noise:
        rng = random.Random(seed)
        px = img.load()
        for _ in range(int(noise * img.width * img.height)):
            px[rng.randrange(img.width), rng.randrange(img.height)] = rng.choice((0, 255))
    return img


def scanned_pdf(pages: list[str], path: Path, font_path: str, noise: float = 0.0) -> None:
    """An image-only PDF (no text layer), one rendered page image per page."""
    images = [render_page(p, font_path, noise=noise, seed=i) for i, p in enumerate(pages)]
    images[0].save(path, save_all=True, append_images=images[1:], resolution=200)


def docx(pages: list[str]) -> bytes:
    """A minimal DOCX; pages are separated by explicit page breaks."""
    body = []
    for i, page in enumerate(pages):
        if i:
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        body += [f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(line)}</w:t></w:r></w:p>"
                 for line in page.split("\n")]  # fmt: skip
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate: edit distance / reference length, whitespace-normalized."""
    from rapidfuzz.distance import Levenshtein

    ref, hyp = " ".join(reference.split()), " ".join(hypothesis.split())
    return Levenshtein.distance(ref, hyp) / max(len(ref), 1)


def xlsx(rows: list[dict], date_columns: tuple[str, ...] = ()) -> bytes:
    """A minimal XLSX workbook: strings shared, numbers as numbers, ISO dates in `date_columns`
    stored the way Excel does (day serials with a date number format)."""
    import io
    from datetime import date

    columns = list(dict.fromkeys(k for r in rows for k in r))
    strings: dict[str, int] = {}

    def ref(i: int, j: int) -> str:
        letters = ""
        j += 1
        while j:
            j, rem = divmod(j - 1, 26)
            letters = chr(65 + rem) + letters
        return f"{letters}{i + 1}"

    def cell(i: int, j: int, value, column: str) -> str:
        if value is None or value == "":
            return ""
        if column in date_columns and isinstance(value, str):
            try:
                serial = (date.fromisoformat(value[:10]) - date(1899, 12, 30)).days
                return f'<c r="{ref(i, j)}" s="1"><v>{serial}</v></c>'
            except ValueError:
                pass
        if isinstance(value, int | float) and not isinstance(value, bool):
            return f'<c r="{ref(i, j)}"><v>{value}</v></c>'
        idx = strings.setdefault(str(value), len(strings))
        return f'<c r="{ref(i, j)}" t="s"><v>{idx}</v></c>'

    body = [
        f'<row r="{i + 1}">' + "".join(cell(i, j, v, c) for j, (c, v) in enumerate(vals)) + "</row>"
        for i, vals in enumerate(
            [[(c, c) for c in columns]] + [[(c, r.get(c)) for c in columns] for r in rows]
        )
    ]
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    sst = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/></Types>'
        ),
        "xl/workbook.xml": (
            f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
            '<sheet name="Accounts" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/styles.xml": (
            f'<styleSheet xmlns="{main}"><cellXfs count="2"><xf numFmtId="0"/>'
            '<xf numFmtId="14" applyNumberFormat="1"/></cellXfs></styleSheet>'
        ),
        "xl/worksheets/sheet1.xml": (
            f'<worksheet xmlns="{main}"><sheetData>{"".join(body)}</sheetData></worksheet>'
        ),
        "xl/sharedStrings.xml": f'<sst xmlns="{main}">{sst}</sst>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()
