"""Verify every PDF page and render review images with Poppler.

Checks the final downloads against the immutable approved PDFs. The comparison
is independent of extracted text alone: original drawing operators, source image
streams, glyph coordinates, and all rendered pixels below the header must match.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFont
import pdfplumber
from pypdf import PdfReader

from build_pdf_logos import (
    BASELINE_REF, HEADER_HEIGHT, HEADER_TEXT_X, LOGO_FILE, LOGO_HEIGHT,
    LOGO_PADDING, LOGO_TOP, LOGO_X, PAGE_COUNTS, ROOT, baseline_file, filename, require,
)

DPI = 144
SCALE = DPI / 72
LOGO_KEY = "/CompanyLogoTechnoMetal"
EDIT_BOTTOM = LOGO_TOP + LOGO_HEIGHT + LOGO_PADDING


def stream_hashes(resources, prefix="") -> dict:
    hashes = {}
    for name, ref in resources.get("/XObject", {}).items():
        obj = ref.get_object()
        key = prefix + name
        hashes[key] = sha256(obj.get_data()).hexdigest()
        if "/Resources" in obj:
            hashes.update(stream_hashes(obj["/Resources"], key))
        if "/SMask" in obj:
            hashes[key + "/SMask"] = sha256(obj["/SMask"].get_data()).hexdigest()
    return hashes


def render(pdf: Path, folder: Path) -> tuple[list[Path], list[str]]:
    folder.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["pdftoppm", "-r", str(DPI), "-png", str(pdf), str(folder / "page")],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    diagnostics = [line.strip() for line in result.stderr.decode(errors="replace").splitlines() if line.strip()]
    # The Windows Poppler bundle reports these missing system aliases on startup.
    # Neither is used by this document. Keep the messages in the QA evidence;
    # reject any other diagnostic or a PDF that actually requests either font.
    startup_aliases = {"Syntax Error: No display font for 'Symbol'",
                       "Syntax Error: No display font for 'ArialUnicode'"}
    require(set(diagnostics) <= startup_aliases, f"Poppler diagnostics: {diagnostics}")
    fonts = {str(font.get_object().get("/BaseFont", ""))
             for page in PdfReader(pdf).pages
             for font in page["/Resources"]["/Font"].values()}
    require(not any("Symbol" in f or "ArialUnicode" in f for f in fonts),
            f"{pdf.name}: renderer is missing a requested font")
    return (sorted(folder.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1])), diagnostics)


def review_sheets(paths: list[Path], language: str, directory: Path) -> list[str]:
    """Full-page sheets plus header detail strips cover every numbered page."""
    directory.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=20)
    outputs = []
    for start in range(0, len(paths), 9):
        sheet = Image.new("RGB", (1800, 1395), "#e4e9ed")
        draw = ImageDraw.Draw(sheet)
        for offset, path in enumerate(paths[start:start + 9]):
            x, y = (offset % 3) * 600, (offset // 3) * 465
            im = Image.open(path).convert("RGB")
            im.thumbnail((580, 411), Image.Resampling.LANCZOS)
            draw.text((x + 10, y + 8), f"{language} / page {start + offset + 1}", fill="#17384f", font=font)
            sheet.paste(im, (x + 10, y + 38))
        name = f"{language}-pages-{start + 1:03}-{min(start + 9, len(paths)):03}.png"
        sheet.save(directory / name)
        outputs.append(name)
    for start in range(0, len(paths), 15):
        sheet = Image.new("RGB", (1740, 720), "#e4e9ed")
        draw = ImageDraw.Draw(sheet)
        for offset, path in enumerate(paths[start:start + 15]):
            x, y = (offset % 3) * 580, (offset // 3) * 144
            draw.text((x + 10, y + 6), f"{language} / page {start + offset + 1}", fill="#17384f", font=font)
            # Native 144 dpi pixels: shows the logo, running header and page-title gap.
            crop = Image.open(path).convert("RGB").crop((0, 0, 560, 108))
            sheet.paste(crop, (x + 10, y + 32))
        name = f"{language}-headers-{start + 1:03}-{min(start + 15, len(paths)):03}.png"
        sheet.save(directory / name)
        outputs.append(name)
    return outputs


def main(review_dir: Path) -> dict:
    require(shutil.which("pdftoppm") is not None, "Poppler pdftoppm is required")
    logo = Image.open(ROOT / LOGO_FILE).convert("RGBA")
    logo_width = LOGO_HEIGHT * logo.width / logo.height
    report = {"baseline_commit": BASELINE_REF, "render_dpi": DPI,
              "renderer": "Poppler pdftoppm", "page_count": 0, "passed": False,
              "logo_source": LOGO_FILE, "documents": []}
    for language, expected_pages in PAGE_COUNTS.items():
        print(f"{language}: checking structure and geometry", flush=True)
        name = filename(language)
        source_bytes = baseline_file(name)
        before_path = review_dir / "before" / name
        require(before_path.read_bytes() == source_bytes, f"{name}: baseline evidence changed")
        after_path = ROOT / name
        before = PdfReader(BytesIO(source_bytes))
        after = PdfReader(after_path)
        require(len(before.pages) == len(after.pages) == expected_pages, f"{name}: page count")
        require(dict(before.metadata) == dict(after.metadata), f"{name}: metadata")
        page_results = []
        with pdfplumber.open(before_path) as bgeo, pdfplumber.open(after_path) as ageo:
            for number, (bp, ap, bg, ag) in enumerate(zip(before.pages, after.pages, bgeo.pages, ageo.pages), 1):
                label = f"{language} page {number}"
                require(list(bp.mediabox) == list(ap.mediabox), f"{label}: media box")
                require(list(bp.cropbox) == list(ap.cropbox), f"{label}: crop box")
                require(bp.rotation == ap.rotation, f"{label}: rotation")
                require(bp.extract_text() == ap.extract_text(), f"{label}: exact text")
                require(len(bp.get("/Annots", [])) == len(ap.get("/Annots", [])), f"{label}: annotations")

                original_ops = bp.get_contents().operations
                restored_ops = deepcopy(ap.get_contents().operations)
                added_ops = restored_ops[9:16]
                require([op for _, op in added_ops] == [b"q", b"rg", b"re", b"f", b"cm", b"Do", b"Q"],
                        f"{label}: unexpected added operators")
                require(added_ops[5][0] == [LOGO_KEY], f"{label}: wrong logo resource")
                require(abs(float(added_ops[4][0][0]) - logo_width) < 1e-7,
                        f"{label}: logo width")
                require(list(added_ops[4][0][1:]) == [0, 0, -LOGO_HEIGHT, LOGO_X, LOGO_TOP + LOGO_HEIGHT],
                        f"{label}: logo transform")
                del restored_ops[9:16]
                require(restored_ops[7][0][3] == HEADER_HEIGHT, f"{label}: header height")
                require(restored_ops[12][0][4] == HEADER_TEXT_X, f"{label}: running header position")
                restored_ops[12][0][4] = original_ops[12][0][4]
                require(restored_ops == original_ops, f"{label}: original content operators changed")

                original_streams = stream_hashes(bp["/Resources"])
                final_streams = stream_hashes(ap["/Resources"])
                require(all(final_streams.get(k) == v for k, v in original_streams.items()),
                        f"{label}: source image or form changed")
                embedded = ap["/Resources"]["/XObject"][LOGO_KEY]
                require((int(embedded["/Width"]), int(embedded["/Height"])) == logo.size,
                        f"{label}: image dimensions")
                require(embedded.get_data() == logo.convert("RGB").tobytes(), f"{label}: logo pixels")
                require(embedded["/SMask"].get_data() == logo.getchannel("A").tobytes(),
                        f"{label}: logo transparency")
                require(len(bg.chars) == len(ag.chars), f"{label}: glyph count")
                for bc, ac in zip(bg.chars, ag.chars):
                    require(bc["text"] == ac["text"], f"{label}: glyph text")
                    dx = HEADER_TEXT_X - 28 if bc["top"] < 32 else 0
                    for key in ("x0", "x1", "top", "bottom", "size"):
                        expected = bc[key] + (dx if key in ("x0", "x1") else 0)
                        require(abs(ac[key] - expected) < 0.0001, f"{label}: glyph {key}")
                logos = [im for im in ag.images if im["name"] == LOGO_KEY[1:]]
                require(len(logos) == 1, f"{label}: logo occurrence count")
                placed = logos[0]
                for key, expected in {"x0": LOGO_X, "top": LOGO_TOP, "width": logo_width,
                                      "height": LOGO_HEIGHT}.items():
                    require(abs(placed[key] - expected) < 0.0001, f"{label}: image {key}")
                body_top = min(c["top"] for c in ag.chars if c["top"] >= 32 and c["text"].strip())
                require(body_top > EDIT_BOTTOM, f"{label}: content touches logo backing")
                require(LOGO_X - LOGO_PADDING > 0 and LOGO_TOP - LOGO_PADDING > 0,
                        f"{label}: page margin")
                require(LOGO_X + logo_width + LOGO_PADDING < HEADER_TEXT_X,
                        f"{label}: logo touches running header")
                page_results.append({"page": number, "exact_text_equal": True,
                    "original_operators_preserved": True, "original_image_streams_preserved": True,
                    "body_glyph_positions_unchanged": True, "logo_count": len(logos),
                    "logo_rect_pt": [placed["x0"], placed["top"], placed["x1"], placed["bottom"]],
                    "heading_bbox_gap_from_logo_backing_pt": round(body_top - EDIT_BOTTOM, 4)})

        print(f"{language}: rendering {expected_pages * 2} before/after pages at {DPI} dpi", flush=True)
        before_pngs, before_diagnostics = render(before_path, review_dir / "render-before" / language)
        after_pngs, after_diagnostics = render(after_path, review_dir / "render-after" / language)
        require(len(before_pngs) == len(after_pngs) == expected_pages, f"{name}: render count")
        body_pixel_top = math.ceil(EDIT_BOTTOM * SCALE) + 1
        logo_reference = None
        for row, bpath, apath in zip(page_results, before_pngs, after_pngs):
            bi, ai = Image.open(bpath).convert("RGB"), Image.open(apath).convert("RGB")
            require(bi.size == ai.size, f"{language} page {row['page']}: rendered size")
            body_bounds = (0, body_pixel_top, ai.width, ai.height)
            require(ImageChops.difference(bi.crop(body_bounds), ai.crop(body_bounds)).getbbox() is None,
                    f"{language} page {row['page']}: rendered body changed")
            original_margin = bi.crop((0, int(HEADER_HEIGHT * SCALE) + 1, bi.width, body_pixel_top))
            require(ImageChops.difference(original_margin, Image.new("RGB", original_margin.size, "white")).getbbox() is None,
                    f"{language} page {row['page']}: original ink enters logo backing area")
            original_title_region = bi.crop((0, int(HEADER_HEIGHT * SCALE) + 1, bi.width, 120))
            ink = ImageChops.difference(original_title_region, Image.new("RGB", original_title_region.size, "white")).getbbox()
            require(ink is not None, f"{language} page {row['page']}: page title missing")
            actual_ink_top = (int(HEADER_HEIGHT * SCALE) + 1 + ink[1]) / SCALE
            require(actual_ink_top > EDIT_BOTTOM, f"{language} page {row['page']}: heading ink touches backing")
            row["heading_ink_gap_from_logo_backing_pt"] = actual_ink_top - EDIT_BOTTOM
            logo_crop = ai.crop((int((LOGO_X - LOGO_PADDING) * SCALE), 0,
                                math.ceil((LOGO_X + logo_width + LOGO_PADDING) * SCALE), body_pixel_top))
            if logo_reference is None:
                logo_reference = logo_crop
            require(ImageChops.difference(logo_reference, logo_crop).getbbox() is None,
                    f"{language} page {row['page']}: inconsistent logo")
            old_header = bi.crop((56, 0, 400, 64))
            moved_header = ai.crop((172, 0, 516, 64))
            # Moving text can change pixel snapping inside a glyph even when its
            # font, text operators and measured coordinates are preserved. Keep
            # this diagnostic for visual review; body pixels still require exact
            # equality and header text/coordinates were checked above.
            header_difference = ImageChops.difference(old_header, moved_header)
            row["moved_header_pixel_difference_bbox"] = header_difference.getbbox()
            row["body_render_changed_pixels"] = 0
            row["logo_render_matches_every_page"] = True
            row["running_header_text_and_geometry_preserved"] = True
            row["render"] = str(apath.relative_to(review_dir))
        sheets = review_sheets(after_pngs, language, review_dir / "contact-sheets")
        report["documents"].append({"language": language, "file": name, "pages": expected_pages,
            "sha256": sha256(after_path.read_bytes()).hexdigest(), "all_checks_passed": True,
            "renderer_diagnostics": {"before": before_diagnostics, "after": after_diagnostics},
            "minimum_heading_ink_gap_from_logo_backing_pt": min(p["heading_ink_gap_from_logo_backing_pt"] for p in page_results),
            "review_sheets": sheets, "page_checks": page_results})
        report["page_count"] += expected_pages
        print(f"{language}: PASS for all {expected_pages} pages", flush=True)
    report["passed"] = True
    (review_dir / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=Path, default=ROOT.parent / "pdf-logo-review")
    args = parser.parse_args()
    report = main(args.review_dir.resolve())
    print(f"PASS: {report['page_count']} pages; see {args.review_dir / 'verification.json'}")
