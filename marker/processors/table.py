from collections import Counter
import hashlib
import re
from typing import Annotated, List

from bs4 import BeautifulSoup
from surya.layout.schema import LayoutBox, LayoutResult
from surya.recognition import RecognitionPredictor, _detect_repeat_loop

from marker.processors import BaseProcessor
from marker.processors.table_recon import (
    reconstruct_table_html,
    table_lines_from_pdftext,
)
from marker.schema import BlockTypes
from marker.schema.document import Document
from marker.schema.labels import block_type_to_surya_label
from marker.util import matrix_intersection_area
from marker.logger import get_logger

logger = get_logger()


class TableProcessor(BaseProcessor):
    """Fills in table HTML.

    - Scanned/garbled pages are full-page OCR'd by the OcrBuilder, which already
      sets ``block.html`` on their Table blocks - those are left untouched.
    - Digital (pdftext) tables are reconstructed from the PDF text layer with
      CPU-only heuristics (see ``table_recon``), which emit the table HTML.
    - A digital table the heuristics can't resolve (sparse, vector-drawn, low
      score) falls back to OCRing the table crop with the recognition model.

    There is no dedicated table-structure model.
    """

    block_types = (BlockTypes.Table, BlockTypes.TableOfContents, BlockTypes.Form)
    mode: Annotated[str, "Conversion mode ('balanced' | 'fast')."] = "balanced"
    min_recon_score: Annotated[
        float,
        "Minimum pdftext reconstruction judge score to accept; below this a",
        "digital table falls back to recognition OCR. None = auto by mode:",
        "0.75 in balanced (spend VLM calls on low-confidence tables), 0.5 in",
        "fast (keep VLM fallback rare).",
    ] = None
    ocr_table_token_floor: Annotated[
        int,
        "Minimum token budget when OCRing a table crop to HTML.",
    ] = 2048
    contained_block_types: Annotated[
        List[BlockTypes],
        "Block types to remove if they're contained inside the tables.",
    ] = (BlockTypes.Text, BlockTypes.TextInlineMath)
    disable_tqdm: Annotated[
        bool,
        "Whether to disable the tqdm progress bar.",
    ] = False
    disable_ocr: Annotated[bool, "Disable OCR entirely."] = False
    collect_table_diagnostics: Annotated[
        bool, "Collect table provenance without changing conversion decisions."
    ] = False

    def __init__(
        self,
        recognition_model: RecognitionPredictor,
        config=None,
    ):
        super().__init__(config)

        self.recognition_model = recognition_model
        # Conversion stats, useful for monitoring table quality
        self.table_stats = Counter()

    def __call__(self, document: Document):
        tables_by_page = self.collect_tables(document)
        diagnostics = {}
        document.table_diagnostics = [] if self.collect_table_diagnostics else None
        total = sum(len(v) for v in tables_by_page.values())
        if not total:
            return

        ocr_fallback = []  # (page, block) digital tables the heuristics missed
        for page in document.pages:
            for block in tables_by_page.get(page.page_id, []):
                record = None
                if self.collect_table_diagnostics:
                    record = self.table_boundary_evidence(page, block)
                    diagnostics[str(block.id)] = record
                    document.table_diagnostics.append(record)
                # Scanned/garbled pages: the full-page OCR already produced the
                # table HTML - trust it, don't redo.
                if block.html:
                    self.table_stats["tables_ocr"] += 1
                    if record is not None:
                        is_ocr = block.text_extraction_method == "surya" or page.text_extraction_method == "surya"
                        record.update(
                            source_kind="existing_ocr_html" if is_ocr else "existing_html",
                            completeness="unknown", reason="no_verified_reference",
                        )
                    continue

                if record is not None:
                    html = self.reconstruct_digital_table(page, block, record)
                else:
                    html = self.reconstruct_digital_table(page, block)
                if html:
                    block.structure = []
                    block.html = html
                    block.text_extraction_method = "pdftext"
                    self.table_stats["tables_pdftext"] += 1
                else:
                    ocr_fallback.append((page, block))

        self.run_ocr_fallback(document, ocr_fallback)
        if self.collect_table_diagnostics:
            for page in document.pages:
                for block in tables_by_page.get(page.page_id, []):
                    record = diagnostics[str(block.id)]
                    record["html_sha256_after_table_processor"] = hashlib.sha256(
                        (block.html or "").encode()
                    ).hexdigest()
                    record["output_text_extraction_method"] = block.text_extraction_method
                    record["has_html"] = bool(block.html)
                    if block.text_extraction_method == "surya":
                        record["source_coverage"] = "unknown"
                    if block.text_extraction_method == "surya" and record.get("source_kind") == "digital_text":
                        source = Counter(token for span in record.get("spans", []) for token in span["text"].split())
                        output = Counter(BeautifulSoup(block.html or "", "html.parser").get_text(" ", strip=True).split())
                        missing = source - output
                        record["ocr_reference_omissions"] = dict(missing)
                        record["ocr_reference_comparison"] = "case_sensitive_whitespace_tokens; typography_and_hyphenation_may_differ"
                        if missing:
                            record["requires_review"] = True
                            record["completeness"] = "unknown"
                    record["later_processors_may_change_output"] = True
        self.cleanup_contained_blocks(document, tables_by_page)

        # Release the cached raw pdftext pages - they hold char-level data
        for page in document.pages:
            page.pdftext_page = None

        self.table_stats["tables_total"] = total
        logger.info(f"Table processing stats: {dict(self.table_stats)}")

    def collect_tables(self, document: Document) -> dict:
        return {
            page.page_id: page.contained_blocks(document, self.block_types)
            for page in document.pages
        }

    def table_boundary_evidence(self, page, block):
        bbox = list(block.polygon.bbox)
        neighbors = []
        for candidate in page.children or []:
            if candidate.id == block.id or candidate.id not in (page.structure or []):
                continue
            other = list(candidate.polygon.bbox)
            overlap = (
                max(0, min(bbox[2], other[2]) - max(bbox[0], other[0]))
                * max(0, min(bbox[3], other[3]) - max(bbox[1], other[1]))
            )
            distance = max(other[0] - bbox[2], bbox[0] - other[2], 0) + max(other[1] - bbox[3], bbox[1] - other[3], 0)
            neighbors.append(dict(
                block_id=str(candidate.id), block_type=str(candidate.block_type),
                bbox=other, overlap_area=overlap, distance=distance,
                cleanup_eligible=(candidate.block_type in self.contained_block_types
                                  and overlap / max(candidate.polygon.area, 1) > 0.95),
            ))
        neighbors.sort(key=lambda n: (n["distance"], -n["overlap_area"]))
        return dict(block_id=str(block.id), block_type=str(block.block_type), bbox=bbox,
                    boundary_rule="token_center_inside_detected_bbox", semantic_ownership="unknown",
                    neighbors=neighbors[:8], neighbors_omitted=max(0, len(neighbors) - 8))

    def reconstruct_digital_table(self, page, block, diagnostics=None) -> str | None:
        """Reconstruct a digital table's HTML from the cached pdftext page.
        Returns HTML, or None if there's no text layer or the heuristics can't
        resolve a confident grid."""
        pdftext_page = page.pdftext_page
        if diagnostics is not None:
            diagnostics["reconstruction_accepted"] = False
        if not pdftext_page:
            if diagnostics is not None:
                diagnostics.update(source_kind="unavailable", completeness="unknown", reason="no_pdftext_page")
            return None
        lines = table_lines_from_pdftext(pdftext_page, block.polygon.bbox, diagnostics,
                                         preserve_placeholders=block.block_type == BlockTypes.Table)
        result = reconstruct_table_html(lines, diagnostics)
        if diagnostics is not None:
            diagnostics["assignment_stage"] = "reconstruction_candidate"
        left, top, right, bottom = block.polygon.bbox
        tolerance = 0.051  # Extraction rounds coordinates to one decimal place.
        if any(x0 < left-tolerance or x1 > right+tolerance or y0 < top-tolerance or y1 > bottom+tolerance
               for spans, y0, y1 in lines for _, x0, x1 in spans):
            if diagnostics is not None:
                diagnostics.update(requires_review=True, source_coverage="unresolved", source_crosses_boundary=True,
                                   boundary_evidence="token_x_and_source_line_y; line_y_may_exceed_selected_char_extent")
                for span in diagnostics.get("spans", []):
                    if (span["bbox"][0] < left-tolerance or span["bbox"][2] > right+tolerance
                            or span["bbox"][1] < top-tolerance or span["bbox"][3] > bottom+tolerance):
                        span.update(status="unresolved", reason="source_crosses_detected_boundary")
            return None
        if not result:
            return None
        html, score = result
        min_score = self.min_recon_score
        if min_score is None:
            min_score = 0.75 if self.mode == "balanced" else 0.5
        if diagnostics is not None:
            diagnostics["reconstruction_accepted"] = score >= min_score
        if score < min_score:
            return None
        return html

    def run_ocr_fallback(self, document: Document, fallback: list):
        """OCR the crops of digital tables the pdftext heuristics couldn't
        resolve, with the recognition model (one box per table -> HTML)."""
        if not fallback or self.disable_ocr:
            return

        images, entries = [], []
        for page, block in fallback:
            highres = page.get_image(highres=True)
            image_poly = block.polygon.rescale(page.polygon.size, highres.size)
            images.append(highres.crop(image_poly.bbox))
            entries.append((block, block.layout_token_count or 0))

        layout_results = []
        for image, (block, token_count) in zip(images, entries):
            w, h = image.size
            label = block_type_to_surya_label(block.block_type) or "Table"
            box = LayoutBox(
                polygon=[[0, 0], [w, 0], [w, h], [0, h]],
                label=label,
                raw_label=label,
                position=0,
                count=max(token_count, self.ocr_table_token_floor),
            )
            layout_results.append(LayoutResult(bboxes=[box], image_bbox=[0, 0, w, h]))

        self.recognition_model.disable_tqdm = self.disable_tqdm
        results = self.recognition_model(
            images=images, layout_results=layout_results, full_page=False
        )
        for (block, _tc), page_result in zip(entries, results):
            block_result = page_result.blocks[0] if page_result.blocks else None
            raw = block_result.html if block_result and not block_result.error else ""
            if block.block_type == BlockTypes.Form:
                # Forms rarely OCR to <table> html - accept any cleaned output
                # (matches how full-page OCR sets form html unconditionally).
                html = self.clean_form_html(raw)
            else:
                html = self.clean_table_html(raw)
            if not html:
                self.table_stats["tables_ocr_failed"] += 1
                logger.warning(f"Table OCR failed for block {block.id}")
                continue
            block.structure = []
            block.html = html
            block.text_extraction_method = "surya"
            self.table_stats["tables_ocr"] += 1

    def clean_table_html(self, html: str | None) -> str:
        if not html:
            return ""
        if not re.search(r"</table\s*>", html, re.IGNORECASE):
            return ""
        if "<table" not in html:
            return ""
        if _detect_repeat_loop(html):
            return ""

        # Re-serialize to balance tags in case of token-budget truncation
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None or not table.find_all(["td", "th"]):
            return ""
        return str(soup).strip()

    def clean_form_html(self, html: str | None) -> str:
        if not html or _detect_repeat_loop(html):
            return ""
        # Balance any truncated tags; no <table> requirement for forms.
        return str(BeautifulSoup(html, "html.parser")).strip()

    def cleanup_contained_blocks(self, document: Document, tables_by_page: dict):
        # Clean out other blocks inside the table
        # This can happen with stray text blocks inside the table post-merging
        for page in document.pages:
            page_tables = tables_by_page.get(page.page_id, [])
            if not page_tables:
                continue
            available = []
            for block in page_tables:
                soup = BeautifulSoup(block.html or "", "html.parser")
                tags = ["td", "th", "label", "p"] if block.block_type == BlockTypes.Form else ["td", "th"]
                units = soup.find_all(tags)
                units = [unit for unit in units if not unit.find_parent(tags)]
                available.append([unit.get_text(" ", strip=True).split() for unit in units])
            child_contained_blocks = page.contained_blocks(
                document, self.contained_block_types
            )
            if not child_contained_blocks:
                continue

            intersections = matrix_intersection_area(
                [c.polygon.bbox for c in child_contained_blocks],
                [block.polygon.bbox for block in page_tables],
            )
            for child_idx, child in enumerate(child_contained_blocks):
                for table_idx in range(len(page_tables)):
                    intersection_pct = intersections[child_idx, table_idx] / max(
                        child.polygon.area, 1
                    )
                    source = child.raw_text(document).split()
                    if intersection_pct <= 0.95 or child.id not in page.structure or not source:
                        continue
                    matched = False
                    for cell in available[table_idx]:
                        for offset in range(len(cell)-len(source)+1):
                            if cell[offset:offset+len(source)] == source:
                                cell[offset:offset+len(source)] = [None] * len(source)
                                matched = True
                                break
                        if matched:
                            break
                    if matched:
                        page.structure.remove(child.id)
                        break
