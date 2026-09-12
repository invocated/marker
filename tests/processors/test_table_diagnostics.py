from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from marker.processors.table import TableProcessor
from marker.processors.table_recon import (
    reconstruct_table_html,
    table_lines_from_pdftext,
)
from marker.renderers.markdown import MarkdownRenderer
from marker.schema.blocks import Form, Table, TableOfContents, Text
from marker.schema.document import Document
from marker.schema.groups.page import PageGroup
from marker.schema.polygon import PolygonBox

pytestmark = pytest.mark.cpu


def lines():
    return [([("ID", 0, 10), ("Cost", 50, 60), ("Effect", 100, 140)], 0, 8)] + [
        ([(str(i), 0, 10), (str(i + 10), 50, 60), ("Same", 100, 140)], y, y + 8)
        for i, y in [(1, 20), (2, 40), (3, 60)]
    ]


def page_data(source):
    return {
        "blocks": [
            {
                "lines": [
                    {
                        "bbox": [0, y0, 450, y1],
                        "spans": [
                            {"text": text, "bbox": [x0, y0, x1, y1]}
                            for text, x0, x1 in spans
                        ],
                    }
                    for spans, y0, y1 in source
                ]
            }
        ]
    }


def document(source=None, existing_html=None):
    table = Table(
        polygon=PolygonBox.from_bbox([0, 0, 450, 100]),
        page_id=0,
        block_id=0,
        html=existing_html,
    )
    prose = Text(
        polygon=PolygonBox.from_bbox([0, 110, 450, 130]), page_id=0, block_id=1
    )
    page = PageGroup(
        polygon=PolygonBox.from_bbox([0, 0, 500, 500]),
        page_id=0,
        children=[table, prose],
        structure=[table.id, prose.id],
        pdftext_page=page_data(source) if source is not None else None,
        highres_image=Image.new("RGB", (500, 500)),
    )
    return Document(filepath="synthetic.pdf", pages=[page])


@pytest.mark.parametrize(
    "width,reason", [(300, "merge_previous_row"), (60, "merge_previous_row")]
)
def test_occurrence_assignments_preserve_existing_output(width, reason):
    source = lines()
    source.insert(2, ([("continuation", 100, 100 + width)], 30, 38))
    trace = {}
    assert reconstruct_table_html(source, trace) == reconstruct_table_html(source)
    occurrence = next(r for r in trace["spans"] if r["text"] == "continuation")
    assert occurrence["reason"] == reason
    assert occurrence["bbox"] == [100, 30, 100 + width, 38]
    assert occurrence["status"] == "emitted"
    if width == 300:
        assert trace["reconstruction_score"] == 1.0
    repeated = [r for r in trace["spans"] if r["text"] == "Same"]
    assert len({r["occurrence"] for r in repeated}) == 3
    assert [r["row"] for r in repeated] == [0, 1, 2]


def test_absorbed_prose_is_not_certified_as_table_content():
    source = lines() + [([("unrelated prose", 100, 160)], 95, 99)]
    trace = {}
    assert reconstruct_table_html(source, trace) is None
    assert trace["reconstruction_score"] == 1.0
    assert trace["completeness"] == "unknown"
    assert trace["spans"][-1]["reason"] == "continuation_gap"


def test_leader_exclusion_and_corrupt_reference():
    trace = {}
    source = lines() + [([("....", 100, 120)], 80, 88)]
    extracted = table_lines_from_pdftext(page_data(source), [0, 0, 450, 100], trace)
    reconstruct_table_html(extracted, trace)
    assert trace["excluded_spans"][0]["reason"] == "leader_only"
    assert trace["excluded_spans"][0]["status"] == "excluded"
    corrupt = {}
    assert reconstruct_table_html([([("\ufffd\ufffd", 0, 20)], 0, 8)], corrupt) is None
    assert corrupt["source_kind"] == "corrupt_or_empty_text"
    assert corrupt["spans"][0]["status"] == "unresolved"


@pytest.mark.parametrize("mode", ["fast", "balanced"])
@pytest.mark.parametrize("disable_ocr", [True, False])
@pytest.mark.parametrize("source", [lines(), [], None])
def test_processor_diagnostics_preserve_decisions(mode, disable_ocr, source):
    original = document(source)
    enabled = deepcopy(original)
    result = [
        SimpleNamespace(
            blocks=[
                SimpleNamespace(
                    html="<table><tr><td>OCR</td></tr></table>", error=False
                )
            ]
        )
    ]
    off_model, on_model = Mock(return_value=result), Mock(return_value=result)
    config = dict(mode=mode, disable_ocr=disable_ocr)
    off = TableProcessor(off_model, config)
    on = TableProcessor(on_model, {**config, "collect_table_diagnostics": True})
    off(original)
    on(enabled)
    assert on_model.call_count == off_model.call_count
    assert original.pages[0].children[0].html == enabled.pages[0].children[0].html
    assert original.pages[0].structure == enabled.pages[0].structure
    assert off.table_stats == on.table_stats
    assert enabled.pages[0].pdftext_page is None
    assert original.table_diagnostics is None
    trace = enabled.table_diagnostics[0]
    assert trace["semantic_ownership"] == "unknown"
    assert trace["neighbors"][0]["bbox"] == [0, 110, 450, 130]
    assert "chars" not in str(trace)
    renderer = MarkdownRenderer()
    assert "table_diagnostics" not in renderer.generate_document_metadata(
        original, None
    )
    assert (
        renderer.generate_document_metadata(enabled, None)["table_diagnostics"]
        == enabled.table_diagnostics
    )


@pytest.mark.parametrize("block_cls", [Table, Form, TableOfContents])
@pytest.mark.parametrize("method", [None, "surya"])
def test_existing_ocr_html_remains_unknown_and_untouched(block_cls, method):
    doc = document(existing_html="<table><tr><td>Existing</td></tr></table>")
    old = doc.pages[0].children[0]
    replacement = block_cls(
        polygon=old.polygon,
        page_id=0,
        block_id=0,
        html=old.html,
        text_extraction_method=method,
    )
    doc.pages[0].children[0] = replacement
    doc.pages[0].structure[0] = replacement.id
    model = Mock()
    TableProcessor(model, {"collect_table_diagnostics": True})(doc)
    model.assert_not_called()
    assert doc.table_diagnostics[0]["source_kind"] == (
        "existing_ocr_html" if method == "surya" else "existing_html"
    )
    assert doc.table_diagnostics[0]["completeness"] == "unknown"
    assert doc.table_diagnostics[0]["later_processors_may_change_output"] is True


def test_header_and_symbol_column_provenance():
    source = lines()
    source.insert(1, ([("wide header", 100, 400)], 10, 18))
    trace = {}
    result = reconstruct_table_html(source, trace)
    assert result == reconstruct_table_html(source)
    header = next(r for r in trace["spans"] if r["text"] == "wide header")
    assert header["status"] == "emitted"
    assert header["reason"] == "header_center"
    source = [([("Item", 50, 80), ("Count", 100, 130)], 0, 8)] + [
        ([("\u2611", 0, 10), ("Same", 50, 80), (str(i), 100, 110)], y, y + 8)
        for i, y in [(1, 20), (2, 40), (3, 60)]
    ]
    trace = {}
    assert reconstruct_table_html(source, trace) == reconstruct_table_html(source)
    assert [r["column"] for r in trace["spans"] if r["text"] in ("Same", "\u2611")] == [
        0
    ] * 6
    assert [r["row"] for r in trace["spans"] if r["text"] == "Same"] == [0, 1, 2]


def test_char_boundary_filter_does_not_expand_region():
    raw = page_data(lines())
    outside = {
        "bbox": [470, 20, 490, 28],
        "spans": [
            {
                "chars": [{"char": "X", "bbox": [470, 20, 478, 28]}],
                "bbox": [470, 20, 490, 28],
            }
        ],
    }
    raw["blocks"][0]["lines"].append(outside)
    trace = {}
    a = table_lines_from_pdftext(raw, [0, 0, 450, 100], trace)
    b = table_lines_from_pdftext(raw, [0, 0, 450, 100])
    assert a == b
    assert all(t != "X" for spans, _, _ in a for t, _, _ in spans)


def test_numeric_continuation_remains_unresolved_not_a_quality_failure():
    source = lines() + [([("42", 100, 120)], 70, 78)]
    trace = {}
    reconstruct_table_html(source, trace)
    assert trace["spans"][-1]["reason"] == "continuation_not_text_column"
    assert trace["spans"][-1]["status"] == "unresolved"
    assert trace["completeness"] == "unknown"


def test_rejected_candidate_is_not_final_ocr_provenance():
    doc = document(lines())
    model = Mock(
        return_value=[
            SimpleNamespace(
                blocks=[
                    SimpleNamespace(
                        html="<table><tr><td>Different OCR text</td></tr></table>",
                        error=False,
                    )
                ]
            )
        ]
    )
    TableProcessor(model, {"collect_table_diagnostics": True, "min_recon_score": 1.1})(
        doc
    )
    trace = doc.table_diagnostics[0]
    assert trace["reconstruction_accepted"] is False
    assert trace["assignment_stage"] == "reconstruction_candidate"
    assert trace["output_text_extraction_method"] == "surya"
    assert trace["completeness"] == "unknown"
    assert any(r["text"] == "Same" for r in trace["spans"])
    assert "Different OCR text" in doc.pages[0].children[0].html
    assert not any(r["text"] == "Different OCR text" for r in trace["spans"])


def test_disabled_diagnostics_preserves_reconstruction_override():
    class CustomProcessor(TableProcessor):
        def reconstruct_digital_table(self, page, block):
            return "<table><tr><td>Custom</td></tr></table>"

    doc = document(lines())
    model = Mock()
    CustomProcessor(model)(doc)
    model.assert_not_called()
    assert doc.table_diagnostics is None
    assert "Custom" in doc.pages[0].children[0].html
