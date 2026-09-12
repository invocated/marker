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
    page.block_id = max(block.block_id for block in page.children)
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


def test_sparse_then_full_header_line_is_one_header():
    source = [([('Choose', 0, 20)], 0, 8),
              ([('ID', 0, 10), ('Name', 30, 70), ('Effect', 90, 130)], 10, 18)]
    source += [([(str(i), 0, 10), ('Name'+str(i), 30, 70), ('Effect'+str(i), 90, 200)], y, y+8)
               for i,y in [(1,30),(2,50),(3,70)]]
    result = reconstruct_table_html(source)
    assert result is not None
    assert cells(result[0]) == [['Choose ID','Name','Effect']] + [
        [str(i),'Name'+str(i),'Effect'+str(i)] for i in range(1,4)]


@pytest.mark.parametrize('table_html,prose', [
    ('<table><tr><td>alpha beta</td></tr></table>', 'beta alpha'),
    ('<table><tr><td>alpha</td></tr><tr><td>beta</td></tr></table>', 'alpha beta'),
])
def test_cleanup_does_not_match_words_out_of_order_or_across_rows(table_html,prose):
    doc=document(existing_html=table_html)
    child=doc.pages[0].children[1]
    child.polygon=PolygonBox.from_bbox([10,10,200,25])
    child.html='<p>'+prose+'</p>'
    TableProcessor(Mock())(doc)
    assert child.id in doc.pages[0].structure


def test_cleanup_consumes_one_represented_occurrence():
    doc=document(existing_html='<table><tr><td>same text</td></tr></table>')
    page=doc.pages[0]
    first=page.children[1]
    first.polygon=PolygonBox.from_bbox([10,10,200,25]);first.html='<p>same text</p>'
    page.block_id=max(b.block_id for b in page.children)
    second=page.add_block(Text,PolygonBox.from_bbox([10,30,200,45]));second.html='<p>same text</p>';page.add_structure(second)
    TableProcessor(Mock())(doc)
    assert first.id not in page.structure and second.id in page.structure


def test_transitive_vertical_overlap_is_not_one_physical_row():
    source=lines()+[([('a',0,10)],80,90),([('b',50,60)],84,94),([('c',100,110)],88,98)]
    trace={}
    assert reconstruct_table_html(source,trace) is None
    assert trace.get('requires_review')


def test_fragment_with_two_possible_rows_requires_review():
    source=lines()+[([('a',0,10)],80,92),([('b',0,10)],84,96),([('c',100,110)],82,94)]
    trace={}
    assert reconstruct_table_html(source,trace) is None
    assert trace.get('requires_review')


def test_near_trailing_text_without_wrap_evidence_requires_review():
    source=lines()+[([('near trailing prose',100,140)],70,78)]
    trace={}
    assert reconstruct_table_html(source,trace) is None
    assert trace.get('requires_review')
    assert trace['spans'][-1]['status']=='unresolved'


def test_processor_rejects_raw_span_crossing_detected_boundary():
    source=lines()
    source[1][0][0]=('1',-10,30)
    doc=document(source)
    TableProcessor(Mock(),{'disable_ocr':True,'collect_table_diagnostics':True})(doc)
    trace=doc.table_diagnostics[0]
    assert not doc.pages[0].children[0].html
    assert trace['requires_review'] and trace['source_coverage']=='unresolved'
    assert trace['bbox']==[0,0,450,100]


def test_header_can_be_wider_than_numeric_column_without_crossing_neighbor():
    source=[([('Choose ID',0,28),('Name',30,70),('Effect',90,130)],0,8)]
    source += [([(str(i),0,10),('Name'+str(i),30,70),('Effect'+str(i),90,180)],y,y+8)
               for i,y in [(1,20),(2,40),(3,60)]]
    result=reconstruct_table_html(source)
    assert result is not None
    assert cells(result[0])[0]==['Choose ID','Name','Effect']


def test_named_dash_column_is_a_real_column():
    source=[([('ID',0,10),('Missing',50,80),('Value',100,130)],0,8)]
    source += [([(str(i),0,10),('-' if i!=2 else '--',50,60),(str(i+10),100,110)],y,y+8)
               for i,y in [(1,20),(2,40),(3,60)]]
    from tests.processors.test_table_diagnostics import page_data
    from marker.processors.table_recon import table_lines_from_pdftext
    result=reconstruct_table_html(table_lines_from_pdftext(page_data(source),[0,0,450,100]))
    assert result is not None
    assert cells(result[0])==[['ID','Missing','Value'],['1','-','11'],['2','--','12'],['3','-','13']]


@pytest.mark.parametrize('preserve', [True,False])
def test_underscore_placeholder_policy_is_explicit(preserve):
    from tests.processors.test_table_diagnostics import page_data
    from marker.processors.table_recon import table_lines_from_pdftext
    source=lines()
    source[1][0][1]=('_____',50,60)
    selected=table_lines_from_pdftext(page_data(source),[0,0,450,100],preserve_placeholders=preserve)
    assert any(text=='_____' for spans,_,_ in selected for text,_,_ in spans)==preserve


@pytest.mark.parametrize('converter_name', ['pdf','table'])
@pytest.mark.parametrize('renderer_cls', [HTMLRenderer,MarkdownRenderer,JSONRenderer,ChunkRenderer])
def test_converter_table_path_uses_real_processor_and_renderer(monkeypatch,converter_name,renderer_cls):
    from importlib import import_module
    module=import_module('marker.converters.'+converter_name)
    cls=getattr(module,'PdfConverter' if converter_name=='pdf' else 'TableConverter')
    doc=document(lines())
    duplicate=doc.pages[0].children[1]
    duplicate.polygon=PolygonBox.from_bbox([100,20,140,28])
    duplicate.html='<p>Same</p>'
    model=Mock()
    processor=TableProcessor(model,{'disable_ocr':True})
    converter=cls.__new__(cls)
    converter.config={}
    converter.processor_list=[processor]
    converter.renderer=renderer_cls
    converter.layout_builder_class=object
    converter.resolve_dependencies=lambda dependency: renderer_cls() if dependency is renderer_cls else Mock()
    monkeypatch.setattr(module,'provider_from_filepath',lambda _:lambda *args:object())
    monkeypatch.setattr(module,'DocumentBuilder',lambda config:Mock(return_value=doc))
    output=converter('synthetic.pdf')
    model.assert_not_called()
    assert converter.page_count==1
    assert doc.pages[0].children[0].html is not None
    assert output.model_dump_json().count('Same')==3
    assert duplicate.id not in doc.pages[0].structure
    assert cells(doc.pages[0].children[0].html)==[['ID','Cost','Effect'],['1','11','Same'],['2','12','Same'],['3','13','Same']]


@pytest.mark.parametrize('block_name,preserve', [('Table',True),('Form',False),('TableOfContents',False)])
def test_processor_placeholder_policy_matches_block_type(monkeypatch,block_name,preserve):
    from marker.schema import blocks
    from marker.processors import table as table_module
    original=table_module.table_lines_from_pdftext
    seen=[]
    def extract(*args,**kwargs):
        seen.append(kwargs.get('preserve_placeholders'))
        return original(*args,**kwargs)
    monkeypatch.setattr(table_module,'table_lines_from_pdftext',extract)
    doc=document(lines());old=doc.pages[0].children[0]
    replacement=getattr(blocks,block_name)(polygon=old.polygon,page_id=0,block_id=0)
    doc.pages[0].children[0]=replacement;doc.pages[0].structure[0]=replacement.id
    TableProcessor(Mock(),{'disable_ocr':True})(doc)
    assert seen==[preserve]


def test_boundary_rounding_tolerance_matches_extraction_precision():
    doc=document(lines());table=doc.pages[0].children[0]
    table.polygon=PolygonBox.from_bbox([0.04,0.04,450,100])
    TableProcessor(Mock(),{'disable_ocr':True,'collect_table_diagnostics':True})(doc)
    assert table.html is not None
    assert not doc.table_diagnostics[0].get('source_crosses_boundary')


def test_vertical_source_line_crossing_requires_review():
    source=lines();source[0]=(source[0][0],-2,8)
    doc=document(source)
    TableProcessor(Mock(),{'disable_ocr':True,'collect_table_diagnostics':True})(doc)
    assert not doc.pages[0].children[0].html
    assert doc.table_diagnostics[0]['requires_review']


def test_form_cleanup_preserves_unrelated_text():
    from marker.schema.blocks import Form
    doc=document();page=doc.pages[0]
    form=Form(polygon=page.children[0].polygon,page_id=0,block_id=0,
              html='<form><label>Name</label><input/></form>')
    page.children[0]=form;page.structure[0]=form.id
    child=page.children[1];child.polygon=PolygonBox.from_bbox([10,10,100,20]);child.html='<p>Name</p>'
    page.block_id=1
    unrelated=page.add_block(Text,PolygonBox.from_bbox([10,30,100,40]));unrelated.html='<p>Unrelated</p>';page.add_structure(unrelated)
    TableProcessor(Mock())(doc)
    assert child.id not in page.structure and unrelated.id in page.structure
    assert MarkdownRenderer()(doc).markdown.count('Name')==1


@pytest.mark.parametrize('ocr_word,missing', [('Same',False),('same',True)])
def test_ocr_reference_comparison_preserves_case_uncertainty(ocr_word,missing):
    html='<table><tr><th>ID</th><th>Cost</th><th>Effect</th></tr>'+''.join(
        '<tr><td>'+str(i)+'</td><td>'+str(i+10)+'</td><td>\u00a0'+ocr_word+'\u00a0</td></tr>' for i in range(1,4))+'</table>'
    model=Mock(return_value=[SimpleNamespace(blocks=[SimpleNamespace(html=html,error=False)])])
    doc=document(lines())
    TableProcessor(model,{'min_recon_score':1.1,'collect_table_diagnostics':True})(doc)
    trace=doc.table_diagnostics[0]
    assert bool(trace['ocr_reference_omissions'])==missing
    assert trace['source_coverage']=='unknown' and trace['completeness']=='unknown'


def test_overlapping_column_spans_require_review():
    source=[([('ID',0,10),('Cost',50,60),('Effect',100,140)],0,8)]
    source += [([(str(i),0,80),(str(i+10),50,90),('Effect'+str(i),100,140)],y,y+8)
               for i,y in [(1,20),(2,40),(3,60)]]
    trace={}
    assert reconstruct_table_html(source,trace) is None
    assert trace['requires_review'] and trace.get('ambiguous_column_intervals')
