"""Add the site's verified TECHNO-METAL logo to the published PDF headers.

The approved PDFs are the source of truth. Their fonts, translations, images,
pagination, and body coordinates are preserved; no HTML layout is regenerated.
The immutable baseline makes reruns safe and avoids stamping a PDF twice.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE_REF = "a9cca786d9863e7a87e587d785fd985fe2534783"
LOGO_FILE = "brand-6797e0f64f068274.webp"
PAGE_COUNTS = {"TH": 43, "EN": 45, "JA": 44}
HEADER_TEXT = "HANDHELD ADJUSTMENT GUIDE"
HEADER_HEIGHT = 32
HEADER_TEXT_X = 86
LOGO_X = 28
LOGO_TOP = 7
LOGO_HEIGHT = 27
LOGO_PADDING = 3


def filename(language: str) -> str:
    return f"Handheld_Adjustment_Guide_R12_A4_{language}.pdf"


def baseline_file(name: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{BASELINE_REF}:{name}"],
        cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_header(page, label: str) -> None:
    """Fail closed if a new source layout needs a fresh placement review."""
    require(abs(float(page.mediabox.width) - 841.8898) < 0.001, f"{label}: width")
    require(abs(float(page.mediabox.height) - 595.2756) < 0.001, f"{label}: height")
    require(page.rotation == 0, f"{label}: rotated page")
    require(page.extract_text().startswith(HEADER_TEXT + "\n"), f"{label}: header text")
    ops = page.get_contents().operations
    require(ops[0] == ([], b"q"), f"{label}: graphics save")
    require(ops[1][1] == b"cm" and list(ops[1][0][:5]) == [1, 0, 0, -1, 0],
            f"{label}: page transform")
    require(ops[7][1] == b"re" and list(ops[7][0]) == [0, 0, 841.891, 32],
            f"{label}: original header rectangle")
    require(ops[12][1] == b"Tm" and list(ops[12][0][:5]) == [10, 0, 0, -10, 28]
            and 23 < float(ops[12][0][5]) < 25, f"{label}: header text position")
    require(ops[10][1] == b"BT" and ops[13][1] == b"TJ" and ops[14][1] == b"ET",
            f"{label}: header text block")


def embed_logo(writer: PdfWriter, logo: Image.Image):
    """Embed the exact decoded RGB and alpha pixels once per document."""
    def image_stream(mode: str, data: bytes):
        stream = DecodedStreamObject()
        stream.set_data(data)
        stream.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(logo.width),
            NameObject("/Height"): NumberObject(logo.height),
            NameObject("/ColorSpace"): NameObject(mode),
            NameObject("/BitsPerComponent"): NumberObject(8),
        })
        return stream.flate_encode()

    alpha = image_stream("/DeviceGray", logo.getchannel("A").tobytes())
    rgb = image_stream("/DeviceRGB", logo.convert("RGB").tobytes())
    rgb[NameObject("/SMask")] = writer._add_object(alpha)
    return writer._add_object(rgb)


def logo_operations(logo_width: float):
    """Draw inside the source page's existing top-left coordinate system."""
    def numbers(*values):
        return ArrayObject([FloatObject(v) for v in values])

    return [
        ([], b"q"),
        (numbers(1, 1, 1), b"rg"),
        (numbers(LOGO_X - LOGO_PADDING, LOGO_TOP - LOGO_PADDING,
                 logo_width + 2 * LOGO_PADDING, LOGO_HEIGHT + 2 * LOGO_PADDING), b"re"),
        ([], b"f"),
        (numbers(logo_width, 0, 0, -LOGO_HEIGHT, LOGO_X, LOGO_TOP + LOGO_HEIGHT), b"cm"),
        ([NameObject("/CompanyLogoTechnoMetal")], b"Do"),
        ([], b"Q"),
    ]


def build(output_dir: Path, review_dir: Path) -> dict:
    logo_bytes = (ROOT / LOGO_FILE).read_bytes()
    require(logo_bytes == baseline_file(LOGO_FILE), "The verified logo asset changed")
    require(f'<img class="company" src="./{LOGO_FILE}" alt="TECHNO-METAL">'
            in (ROOT / "index.html").read_text(encoding="utf-8"),
            "The site's company-logo identity changed")
    logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
    require(logo.size == (1602, 982), "The verified logo dimensions changed")
    logo_width = LOGO_HEIGHT * logo.width / logo.height
    require(LOGO_X + logo_width + LOGO_PADDING < HEADER_TEXT_X, "Header overlap")
    require(LOGO_TOP + LOGO_HEIGHT + LOGO_PADDING == 37, "Logo clearance changed")

    output_dir.mkdir(parents=True, exist_ok=True)
    before_dir = review_dir / "before"
    before_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "baseline_commit": BASELINE_REF,
        "logo": {"file": LOGO_FILE, "sha256": sha256(logo_bytes).hexdigest(),
                 "pixel_size": list(logo.size), "x_pt": LOGO_X, "top_pt": LOGO_TOP,
                 "width_pt": logo_width, "height_pt": LOGO_HEIGHT,
                 "white_padding_pt": LOGO_PADDING},
        "header_height_pt": HEADER_HEIGHT, "header_text_x_pt": HEADER_TEXT_X,
        "documents": [],
    }
    # Generate and check all documents in memory before replacing any download.
    pending = []
    for language, expected_pages in PAGE_COUNTS.items():
        name = filename(language)
        source = baseline_file(name)
        reader = PdfReader(BytesIO(source))
        require(len(reader.pages) == expected_pages, f"{name}: page count changed")
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        image_ref = embed_logo(writer, logo)
        for page_number, page in enumerate(writer.pages, 1):
            check_header(reader.pages[page_number - 1], f"{language} page {page_number}")
            contents = page.get_contents()
            contents.operations[12][0][4] = NumberObject(HEADER_TEXT_X)
            contents.operations[9:9] = logo_operations(logo_width)
            resources = page["/Resources"]
            if "/XObject" not in resources:
                resources[NameObject("/XObject")] = DictionaryObject()
            require("/CompanyLogoTechnoMetal" not in resources["/XObject"],
                    f"{language} page {page_number}: logo resource already exists")
            resources["/XObject"][NameObject("/CompanyLogoTechnoMetal")] = image_ref
            page.replace_contents(contents)
            page.compress_content_streams()
        result = BytesIO()
        writer.write(result)
        pdf_bytes = result.getvalue()
        reopened = PdfReader(BytesIO(pdf_bytes))
        require(len(reopened.pages) == expected_pages, f"{name}: output page count")
        for n, (before, after) in enumerate(zip(reader.pages, reopened.pages), 1):
            require(before.extract_text() == after.extract_text(), f"{name} page {n}: text")
            require(list(before.mediabox) == list(after.mediabox), f"{name} page {n}: size")
        pending.append((name, source, pdf_bytes))
        report["documents"].append({
            "language": language, "file": name, "pages": expected_pages,
            "before_sha256": sha256(source).hexdigest(),
            "after_sha256": sha256(pdf_bytes).hexdigest(),
            "bytes": len(pdf_bytes),
        })
    for name, source, pdf_bytes in pending:
        (before_dir / name).write_bytes(source)
        target = output_dir / name
        staging = target.with_suffix(".pdf.tmp")
        staging.write_bytes(pdf_bytes)
        staging.replace(target)
    (review_dir / "build-manifest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--review-dir", type=Path, default=ROOT.parent / "pdf-logo-review")
    args = parser.parse_args()
    manifest = build(args.output_dir.resolve(), args.review_dir.resolve())
    for doc in manifest["documents"]:
        print(f"{doc['language']}: {doc['pages']} pages, {doc['bytes']} bytes, {doc['after_sha256']}")
