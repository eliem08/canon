"""Document text extraction: plain text, PDF (text layer, else OCR), DOCX, scanned images.

Every extractor returns pages joined by form feeds (`\\f`), the convention `pdftotext` uses, so the
contract parser can cite `file#p<page>:L<line>`. OCR runs the `tesseract` binary (fra+ara+eng by
default); when it is missing, or when a page has no text and no image, the document is reported as
a `ParseIssue` instead of being silently skipped or guessed.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

TEXT_SUFFIXES = {".txt"}
PDF_SUFFIXES = {".pdf"}
DOCX_SUFFIXES = {".docx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
DOCUMENT_SUFFIXES = TEXT_SUFFIXES | PDF_SUFFIXES | DOCX_SUFFIXES | IMAGE_SUFFIXES
ACL_SIDECAR = "_acl.json"
_BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")  # direction marks OCR emits
UNSURE = "[?]"  # stands for a word with digits that OCR was not sure of


@dataclass(frozen=True)
class OCRConfig:
    languages: str = "fra+ara+eng"
    min_text_chars: int = 20  # a PDF page with less text than this is treated as scanned
    low_confidence: float = 60.0  # mean tesseract word confidence below this is flagged
    median_filter: int = 3  # odd kernel size; 0 disables denoising
    denoise_below: float = 80.0  # retry with the median filter when confidence is below this
    # a word with digits read below this confidence is masked as "[?]": a misread 5/6 or 3/8 makes
    # a wrong date or amount that looks right (real receipts: 4 of 4 wrong dates were below 80)
    min_digit_confidence: float = 80.0
    # before withholding it, re-read such a word alone (cropped, enlarged, single-line mode) and
    # keep the re-read if tesseract is now at least this sure of it; 0 disables the second pass
    reread_min_confidence: float = 85.0
    # failing that, accept a word when two independent reads agree exactly (the page read, the 3x
    # re-read, a 2x and a black-and-white re-read), each at least this sure; 0 disables
    consensus_min_confidence: float = 0.0
    max_rereads: int = 40  # per page, to bound the cost on very poor scans
    binary: str = "tesseract"
    timeout_s: int = 120


@dataclass
class DocumentText:
    text: str  # pages joined by "\f"
    method: str  # text | pdf | docx | ocr | pdf+ocr | none
    issues: list[tuple[str, str]] = field(default_factory=list)  # (reason, detail)
    ocr_confidence: float | None = None
    denoised: bool = False  # the median filter was used: Arabic dots may be lost


def ocr_available(config: OCRConfig | None = None) -> bool:
    return shutil.which((config or OCRConfig()).binary) is not None


def _png(data: bytes, median: int = 0) -> bytes:
    """Grayscale PNG, optionally median-filtered (removes scanner/fax speckle)."""
    from PIL import Image, ImageFilter

    img = Image.open(io.BytesIO(data)).convert("L")
    if median:
        img = img.filter(ImageFilter.MedianFilter(median))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ocr_image(data: bytes, config: OCRConfig) -> tuple[str, float | None, bool]:
    """OCR one image. Returns (text, mean word confidence, whether it was denoised).

    The median filter removes speckle but also erases thin strokes and the dots of Arabic
    letters, so it is used only when the plain pass is unsure, and only if it does better."""
    text, conf = _tesseract(_png(data), config, _rereader(_png(data), config))
    if config.median_filter and (conf or 0) < config.denoise_below:
        png2 = _png(data, config.median_filter)
        text2, conf2 = _tesseract(png2, config, _rereader(png2, config))
        if (conf2 or 0) > (conf or 0):
            return text2, conf2, True
    return text, conf, False


def _run_tesseract(png: bytes, config: OCRConfig, psm: str) -> list[list[str]]:
    """TSV word rows (level 5) of one image."""
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "page.png"
        img.write_bytes(png)
        run = subprocess.run(
            [config.binary, str(img), "stdout", "-l", config.languages, "--psm", psm, "tsv"],
            capture_output=True,
            timeout=config.timeout_s,
            check=True,
            # one thread per page: tesseract's OpenMP threads thrash when several run at once
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    rows = [r.split("\t") for r in run.stdout.decode("utf-8", "replace").splitlines()[1:]]
    return [c for c in rows if len(c) >= 12 and c[0] == "5" and c[11].strip()]


def _rereader(png: bytes, config: OCRConfig):
    """Re-read one word box alone: crop with a margin, enlarge 3x, single-line mode. Returns the
    new reading only if tesseract is at least `reread_min_confidence` sure of every part of it."""
    if not config.reread_min_confidence:
        return None
    from PIL import Image, ImageOps

    page = Image.open(io.BytesIO(png))
    budget = [config.max_rereads]

    def read(crop, scale: int, bw: bool) -> tuple[str, float] | None:
        img = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS)
        if bw:
            gray = ImageOps.autocontrast(img.convert("L"))
            img = gray.point(lambda v: 255 if v > 128 else 0)
        buf = io.BytesIO()
        ImageOps.expand(img, border=20, fill=255).save(buf, format="PNG")
        rows = _run_tesseract(buf.getvalue(), config, "7")
        if not rows:
            return None
        return "".join(r[11] for r in rows), min(float(r[10]) for r in rows)

    def reread(left: int, top: int, width: int, height: int, first=None) -> str | None:
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        pad = max(2, height // 4)
        box = (max(0, left - pad), max(0, top - pad), left + width + pad, top + height + pad)
        crop = page.crop(box)
        main = read(crop, 3, False)
        if main and main[1] >= config.reread_min_confidence:
            return main[0]
        floor = config.consensus_min_confidence
        if not floor:
            return None
        votes = [r for r in (first, main) if r and r[1] >= floor]
        if len(votes) == 2 and votes[0][0] == votes[1][0]:
            return votes[0][0]
        for scale, bw in ((2, False), (3, True)):
            other = read(crop, scale, bw)
            if other and other[1] >= floor:
                if any(v[0] == other[0] for v in votes):
                    return other[0]
                votes.append(other)
        return None

    return reread


def _tesseract(png: bytes, config: OCRConfig, reread=None) -> tuple[str, float | None]:
    lines: dict[tuple[str, ...], list[str]] = {}
    confs = []
    for cols in _run_tesseract(png, config, "6"):
        word, conf = cols[11], float(cols[10])
        if 0 <= conf < config.min_digit_confidence and any(c.isdigit() for c in word):
            better = reread(*map(int, cols[6:10]), first=(word, conf)) if reread else None
            word = better if better and any(c.isdigit() for c in better) else UNSURE
        lines.setdefault(tuple(cols[1:5]), []).append(word)
        if conf >= 0:
            confs.append(conf)
    text = "\n".join(" ".join(words) for words in lines.values())
    return _BIDI.sub("", text), (sum(confs) / len(confs) if confs else None)


def _ocr_pages(images: list[bytes], config: OCRConfig, doc: DocumentText) -> list[str]:
    pages, confs = [], []
    for data in images:
        text, conf, denoised = ocr_image(data, config)
        pages.append(text)
        doc.denoised |= denoised
        if conf is not None:
            confs.append(conf)
    unsure = sum(p.count(UNSURE) for p in pages)
    if unsure:
        doc.issues.append(
            ("unsure_ocr_digits", f"{unsure} word(s) with digits below confidence "
             f"{config.min_digit_confidence:g} withheld")
        )  # fmt: skip
    if confs:
        doc.ocr_confidence = round(sum(confs) / len(confs), 1)
        if doc.ocr_confidence < config.low_confidence:
            doc.issues.append(("low_ocr_confidence", f"mean word confidence {doc.ocr_confidence}"))
    return pages


def _pdf(path: Path, config: OCRConfig) -> DocumentText:
    from pypdf import PdfReader

    doc = DocumentText("", "pdf")
    try:
        reader = PdfReader(str(path))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
    except Exception as exc:  # malformed or encrypted PDF: report, never crash the run
        doc.method = "none"
        doc.issues.append(("unreadable_pdf", type(exc).__name__))
        return doc
    scanned = [i for i, t in enumerate(pages) if len(re.sub(r"\s", "", t)) < config.min_text_chars]
    if scanned:
        if not ocr_available(config):
            doc.issues.append(("ocr_unavailable", f"{len(scanned)} page(s) without a text layer"))
        else:
            images = []
            for i in scanned:
                page_images = list(reader.pages[i].images)
                if not page_images:
                    doc.issues.append(("no_text_or_image", f"page {i + 1}"))
                    images.append(None)
                    continue
                images.append(max(page_images, key=lambda im: len(im.data)).data)
            texts = _ocr_pages([im for im in images if im], config, doc)
            it = iter(texts)
            for i, im in zip(scanned, images, strict=True):
                if im:
                    pages[i] = next(it)
            doc.method = "ocr" if len(scanned) == len(pages) else "pdf+ocr"
    doc.text = "\f".join(pages)
    if not doc.text.replace("\f", "").strip():
        doc.method = "none"
    return doc


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx(path: Path) -> DocumentText:
    from xml.etree import ElementTree

    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        return DocumentText("", "none", [("unreadable_docx", type(exc).__name__)])
    out: list[str] = []
    for para in root.iter(f"{_W}p"):
        parts = []
        for node in para.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag == f"{_W}br" and node.get(f"{_W}type") == "page":
                parts.append("\f")
        out.append("".join(parts))
    text = "\n".join(out).replace("\n\f", "\f").replace("\f\n", "\f")
    return DocumentText(text, "docx")


def extract_text(path: Path, config: OCRConfig | None = None) -> DocumentText:
    config = config or OCRConfig()
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return DocumentText(path.read_text(encoding="utf-8"), "text")
    if suffix in PDF_SUFFIXES:
        return _pdf(path, config)
    if suffix in DOCX_SUFFIXES:
        return _docx(path)
    if suffix in IMAGE_SUFFIXES:
        if not ocr_available(config):
            return DocumentText("", "none", [("ocr_unavailable", "image file")])
        doc = DocumentText("", "ocr")
        doc.text = "\f".join(_ocr_pages([path.read_bytes()], config, doc))
        return doc
    return DocumentText("", "none", [("unsupported_format", suffix)])


def folder_acl(path: Path, root: Path, default: tuple[str, ...]) -> list[str]:
    """ACL from the nearest `_acl.json` ({"acl": [...]}) between the file and `root`."""
    root = Path(root).resolve()
    folder = Path(path).resolve().parent
    while True:
        sidecar = folder / ACL_SIDECAR
        if sidecar.exists():
            return list(json.loads(sidecar.read_text(encoding="utf-8"))["acl"])
        if folder == root or root not in folder.parents:
            return list(default)
        folder = folder.parent


def iter_documents(root: Path) -> list[Path]:
    """Documents under `root`. Symlinks, and anything whose real location is outside `root`,
    are skipped: a link would take its access rules from wherever it points."""
    real_root = Path(root).resolve()
    return sorted(
        p
        for p in Path(root).rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and p.suffix.lower() in DOCUMENT_SUFFIXES
        and not p.name.startswith(".")
        and real_root in p.resolve().parents
    )
