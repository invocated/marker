"""Preservation regressions using synthetic text and supplied table regions."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from marker.processors.table import TableProcessor
from marker.processors.table_recon import reconstruct_table_html
from marker.renderers.html import HTMLRenderer
from marker.renderers.markdown import MarkdownRenderer
from marker.renderers.json import JSONRenderer
from marker.renderers.chunk import ChunkRenderer
from marker.schema.blocks import Text
from marker.schema.polygon import PolygonBox
from tests.processors.test_table_diagnostics import document, lines

pytestmark = pytest.mark.cpu
CASES = json.loads(Path(__file__).with_name('table_preservation_cases.json').read_text())


def cells(html):
    return [[cell.get_text() for cell in row.find_all(['th', 'td'])]
            for row in BeautifulSoup(html, 'html.parser').find_all('tr')]


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_preserve_exact_rows_and_cells(case):
    trace = {}
    result = reconstruct_table_html(case['lines'], trace)
    if case['name'] == 'surrounding_prose_inside_supplied_region' and result is None:
        assert any(span['status'] == 'unresolved' for span in trace['spans'])
        return
    assert result is not None
    assert cells(result[0]) == case['expected']


def test_overlapping_disjoint_fragments_do_not_become_false_rows():
    source = [([('Name', 0, 25), ('Value', 60, 85), ('Detail', 120, 155)], 0, 8)]
    for index, y in enumerate((20, 40, 60), 1):
        source += [([(str(index), 0, 10), (str(index+10), 60, 75)], y+2, y+10),
                   ([('detail '+str(index), 120, 160)], y, y+8)]
    trace = {}
    result = reconstruct_table_html(source, trace)
    if result is None:
        assert any(s['status'] == 'unresolved' for s in trace['spans'])
    else:
        assert cells(result[0]) == [['Name', 'Value', 'Detail']] + [
            [str(i), str(i+10), 'detail '+str(i)] for i in range(1, 4)]


def test_overlapping_true_rows_keep_separate_identifiers():
    source = [([('ID', 0, 10), ('Cost', 50, 60), ('Effect', 100, 140)], 0, 8)]
    source += [([(str(i), 0, 10), (str(i+10), 50, 60), ('Effect'+str(i), 100, 140)], y, y+12)
               for i,y in [(1,20),(2,30),(3,40)]]
    result = reconstruct_table_html(source)
    assert result is not None
    assert cells(result[0])[1:] == [[str(i),str(i+10),'Effect'+str(i)] for i in range(1,4)]


def test_cross_column_text_remains_unresolved():
    source = lines()
    source.insert(2, ([('text crossing columns', 45, 130)], 30, 38))
    trace = {}
    result = reconstruct_table_html(source, trace)
    span = next(s for s in trace['spans'] if s['text'] == 'text crossing columns')
    assert span['status'] == 'unresolved'
    assert result is None or 'text crossing columns' not in result[0]


@pytest.mark.parametrize('disable_ocr', [False, True])
@pytest.mark.parametrize('mode', ['fast', 'balanced'])
def test_failed_table_keeps_overlapping_source_text(disable_ocr, mode):
    doc = document([])
    page = doc.pages[0]
    text = page.children[1]
    text.polygon = PolygonBox.from_bbox([10, 10, 200, 25])
    text.html = '<p>Recoverable source text</p>'
    model = Mock(return_value=[SimpleNamespace(blocks=[SimpleNamespace(html='', error=True)])])
    TableProcessor(model, {'disable_ocr':disable_ocr,'mode':mode})(doc)
    assert text.id in page.structure
    for renderer in (HTMLRenderer,MarkdownRenderer,JSONRenderer,ChunkRenderer):
        output = renderer()(doc).model_dump_json()
        assert 'Recoverable source text' in output
    assert model.call_count == (0 if disable_ocr else 1)


def test_cleanup_removes_only_text_represented_by_table():
    doc = document(existing_html='<table><tr><td>Represented text</td></tr></table>')
    page=doc.pages[0]
    represented=page.children[1]
    represented.polygon=PolygonBox.from_bbox([10,10,200,25])
    represented.html='<p>Represented text</p>'
    missing=page.add_block(Text,PolygonBox.from_bbox([10,30,200,45]))
    missing.html='<p>Unrepresented prose</p>'
    page.add_structure(missing)
    TableProcessor(Mock())(doc)
    assert represented.id not in page.structure
    assert missing.id in page.structure
    markdown=MarkdownRenderer()(doc).markdown
    assert markdown.count('Represented text')==1
    assert markdown.count('Unrepresented prose')==1


def test_truncated_ocr_table_is_not_repaired_into_success():
    processor=TableProcessor(Mock())
    assert processor.clean_table_html('<table><tr><td>Truncated') == ''


def test_fallback_missing_clean_reference_is_not_accepted_as_complete():
    doc=document(lines())
    model=Mock(return_value=[SimpleNamespace(blocks=[SimpleNamespace(
        html='<table><tr><td>Only one cell</td></tr></table>',error=False)])])
    TableProcessor(model,{'min_recon_score':1.1,'collect_table_diagnostics':True})(doc)
    trace=doc.table_diagnostics[0]
    assert trace.get('completeness') != 'complete'
    assert not doc.pages[0].children[0].html or trace.get('ocr_reference_omissions')


def test_staggered_three_column_rows_and_multicolumn_continuations():
    source = [([('ID', 0, 10), ('Name', 30, 70), ('Description', 90, 150)], 0, 8),
              ([('1', 0, 10), ('Alpha', 30, 75), ('First effect', 90, 390)], 20, 28),
              ([('2', 0, 10), ('Beta', 30, 75)], 40, 48),
              ([('Second effect', 90, 390)], 40, 48),
              ([('continued name', 30, 76)], 50, 58),
              ([('continued effect', 90, 380)], 50, 58),
              ([('3', 0, 10), ('Gamma', 30, 75), ('Third effect', 90, 390)], 70, 78),
              ([('last continuation', 90, 370)], 80, 88)]
    result = reconstruct_table_html(source)
    assert result is not None
    assert cells(result[0]) == [['ID', 'Name', 'Description'],
                                ['1', 'Alpha', 'First effect'],
                                ['2', 'Beta continued name', 'Second effect continued effect'],
                                ['3', 'Gamma', 'Third effect last continuation']]


def test_blank_first_cell_remains_a_separate_row():
    source = [([('ID', 0, 10), ('Cost', 50, 60), ('Effect', 100, 150)], 0, 8),
              ([('1', 0, 10), ('11', 50, 60), ('Alpha', 100, 140)], 20, 28),
              ([('12', 50, 60), ('Blank identifier row', 100, 180)], 40, 48),
              ([('3', 0, 10), ('13', 50, 60), ('Gamma', 100, 140)], 60, 68),
              ([('4', 0, 10), ('14', 50, 60), ('Delta', 100, 140)], 80, 88)]
    result = reconstruct_table_html(source)
    assert result is not None
    assert cells(result[0])[1:] == [['1','11','Alpha'],['','12','Blank identifier row'],
                                  ['3','13','Gamma'],['4','14','Delta']]
