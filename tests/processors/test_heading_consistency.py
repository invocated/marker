"""Heading consistency without model or private PDF fixtures."""
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from marker.converters import BaseConverter
from marker.converters.pdf import PdfConverter
from marker.converters.table import TableConverter
from marker.processors.document_toc import DocumentTOCProcessor
from marker.processors.sectionheader import SectionHeaderProcessor
from marker.processors.llm.llm_sectionheader import LLMSectionHeaderProcessor
from marker.processors.llm.llm_page_correction import LLMPageCorrectionProcessor
from marker.processors.llm.llm_meta import LLMSimpleBlockMetaProcessor
from marker.renderers.json import JSONRenderer
from marker.renderers.html import HTMLRenderer
from marker.renderers.markdown import MarkdownRenderer
from marker.renderers.chunk import ChunkRenderer
from marker.schema.document import Document
from marker.schema.groups.page import PageGroup
from marker.schema.blocks.sectionheader import SectionHeader
from marker.schema.polygon import PolygonBox
from marker.schema.text.line import Line
from marker.schema.text.span import Span

pytestmark = pytest.mark.cpu


def document_with_heading(html=None, empty=False, ignored=False):
    page = PageGroup(page_id=0, polygon=PolygonBox.from_bbox([0, 0, 600, 800]),
                     children=[], structure=[], lowres_image=Image.new('RGB', (600, 800)))
    heading = page.add_block(SectionHeader, PolygonBox.from_bbox([10, 10, 200, 30]))
    page.add_structure(heading)
    heading.html = html
    heading.ignore_for_output = ignored
    if html is None and not empty:
        line = page.add_block(Line, heading.polygon)
        heading.add_structure(line)
        span = page.add_full_block(Span(
            page_id=0, polygon=heading.polygon, text='Introduction', font='Arial',
            font_weight=400, font_size=20, minimum_position=0, maximum_position=12,
            formats=['plain']))
        line.add_structure(span)
    return Document(filepath='synthetic.pdf', pages=[page]), heading


def assert_rendered_heading(document, heading, level):
    toc = document.table_of_contents
    assert toc == [{'title': 'Introduction', 'heading_level': level, 'page_id': 0,
                    'polygon': heading.polygon.polygon}]
    assert heading.heading_level == level
    outputs = [renderer()(document) for renderer in
               (JSONRenderer, HTMLRenderer, MarkdownRenderer, ChunkRenderer)]
    for output in outputs:
        assert output.metadata['table_of_contents'] == toc
    json, html, markdown, chunks = outputs
    expected_hierarchy = {level: str(heading.id)}
    assert json.children[0].children[0].section_hierarchy == expected_hierarchy
    assert chunks.blocks[0].section_hierarchy == expected_hierarchy
    for content in (json.children[0].children[0].html, html.html, chunks.blocks[0].html):
        tag = BeautifulSoup(content, 'html.parser').find(f'h{level}')
        assert tag is not None and tag.get_text().strip() == 'Introduction'
    assert markdown.markdown == '#' * level + ' Introduction'


def test_digital_heading_toc_after_assignment():
    document, heading = document_with_heading()
    SectionHeaderProcessor()(document)
    DocumentTOCProcessor()(document)
    assert_rendered_heading(document, heading, 2)


@pytest.mark.parametrize('level', range(1, 7))
def test_ocr_heading_toc(level):
    document, heading = document_with_heading(f'<h{level}>Introduction</h{level}>')
    SectionHeaderProcessor()(document)
    DocumentTOCProcessor()(document)
    assert_rendered_heading(document, heading, level)


@pytest.mark.parametrize('processor_cls,correction_type', [
    (LLMSectionHeaderProcessor, 'corrections_needed'),
    (LLMPageCorrectionProcessor, 'rewrite'),
])
def test_optional_rewrite_synchronizes_final_level(processor_cls, correction_type):
    document, heading = document_with_heading()
    SectionHeaderProcessor()(document)
    service = Mock(return_value={'correction_type': correction_type, 'blocks': [
        {'id': str(heading.id), 'html': '<h4>Introduction</h4>'}]})
    processor = processor_cls(service, {'use_llm': True, 'disable_tqdm': True,
                                        'block_correction_prompt': 'Correct headings'})
    processor(document)
    service.assert_called_once()
    assert heading.html == '<h4>Introduction</h4>'
    DocumentTOCProcessor()(document)
    assert_rendered_heading(document, heading, 4)


@pytest.mark.parametrize('html', ['<p>Introduction</p>', '<h9>Introduction</h9>',
                                 '<h2>A</h2><h3>B</h3>', '<h2>A</h2><h9>B</h9>'])
def test_invalid_or_multiple_tags_keep_existing_level(html):
    document, heading = document_with_heading(html)
    heading.heading_level = 5
    DocumentTOCProcessor()(document)
    assert heading.heading_level == 5
    assert heading.html == html
    assert document.table_of_contents[0]['heading_level'] == 5


@pytest.mark.parametrize('kwargs', [{'empty': True}, {'html': '<h3>Introduction</h3>', 'ignored': True}])
def test_empty_and_ignored_membership_is_preserved(kwargs):
    document, heading = document_with_heading(**kwargs)
    SectionHeaderProcessor()(document)
    DocumentTOCProcessor()(document)
    assert len(document.table_of_contents) == 1
    output = JSONRenderer()(document).children[0].children[0]
    assert output.html == ''
    assert output.section_hierarchy == {heading.heading_level: str(heading.id)}


def test_toc_identity_and_order():
    document, first = document_with_heading('<h3>Introduction</h3>')
    second = document.pages[0].add_block(SectionHeader, PolygonBox.from_bbox([10, 50, 200, 70]))
    second.html = '<h1>Second</h1>'
    document.pages[0].add_structure(second)
    SectionHeaderProcessor()(document)
    DocumentTOCProcessor()(document)
    assert document.table_of_contents == [
        {'title': 'Introduction', 'heading_level': 3, 'page_id': 0, 'polygon': first.polygon.polygon},
        {'title': 'Second', 'heading_level': 1, 'page_id': 0, 'polygon': second.polygon.polygon},
    ]


def test_initialized_default_and_custom_processor_order(monkeypatch):
    monkeypatch.setattr('marker.converters.download_font', lambda: None)
    # Construct processors without model dependencies; use the real grouping logic.
    monkeypatch.setattr(BaseConverter, 'resolve_dependencies', lambda self, cls: cls.__new__(cls))
    converter = PdfConverter({}, config={'mode': 'fast'})
    types = [type(processor) for processor in converter.processor_list]
    assert types.index(SectionHeaderProcessor) < types.index(LLMSectionHeaderProcessor)
    assert types.index(LLMSimpleBlockMetaProcessor) < types.index(LLMSectionHeaderProcessor)
    assert types.index(LLMPageCorrectionProcessor) < types.index(DocumentTOCProcessor)
    custom = ['marker.processors.document_toc.DocumentTOCProcessor',
              'marker.processors.sectionheader.SectionHeaderProcessor']
    converter = PdfConverter({}, processor_list=custom, config={'mode': 'fast'})
    assert [type(p) for p in converter.processor_list] == [DocumentTOCProcessor, SectionHeaderProcessor]
    converter = PdfConverter({}, processor_list=[], config={'mode': 'fast'})
    assert converter.processor_list == []
    table = TableConverter({}, config={'mode': 'fast'})
    assert not any(isinstance(p, DocumentTOCProcessor) for p in table.processor_list)


def test_hierarchy_inherits_and_resets_across_pages():
    document, first = document_with_heading('<h1>Introduction</h1>')
    page = PageGroup(page_id=7, polygon=PolygonBox.from_bbox([0, 0, 600, 800]),
                     children=[], structure=[])
    document.pages.append(page)
    second = page.add_block(SectionHeader, PolygonBox.from_bbox([10, 10, 200, 30]))
    second.html = '<h3>Detail</h3>'
    page.add_structure(second)
    third = page.add_block(SectionHeader, PolygonBox.from_bbox([10, 50, 200, 70]))
    third.html = '<h2>Next</h2>'
    page.add_structure(third)
    SectionHeaderProcessor()(document)
    DocumentTOCProcessor()(document)
    expected_toc = [
        {'title': title, 'heading_level': level, 'page_id': heading.page_id,
         'polygon': heading.polygon.polygon}
        for title, level, heading in [('Introduction', 1, first), ('Detail', 3, second), ('Next', 2, third)]
    ]
    expected_hierarchies = [{1: str(first.id)}, {1: str(first.id), 3: str(second.id)},
                           {1: str(first.id), 2: str(third.id)}]
    for renderer in (JSONRenderer, HTMLRenderer, MarkdownRenderer, ChunkRenderer):
        assert renderer()(document).metadata['table_of_contents'] == expected_toc
    json = JSONRenderer()(document)
    assert [block.section_hierarchy for page_output in json.children for block in page_output.children] == expected_hierarchies
    assert [block.section_hierarchy for block in ChunkRenderer()(document).blocks] == expected_hierarchies


@pytest.mark.parametrize('original_type,response_type,html', [
    ('Text', 'SectionHeader', '<h1>Introduction</h1>'),
    ('SectionHeader', 'Text', '<p>Introduction</p>'),
])
def test_page_correction_does_not_relabel_blocks(original_type, response_type, html):
    from marker.schema.blocks.text import Text
    from marker.schema import BlockTypes

    document, heading = document_with_heading('<h2>Introduction</h2>')
    block = heading
    if original_type == 'Text':
        page = document.pages[0]
        block = page.add_block(Text, heading.polygon)
        block.html = '<p>Introduction</p>'
        page.structure = [block.id]
    SectionHeaderProcessor()(document)
    service = Mock(return_value={'correction_type': 'rewrite', 'blocks': [
        {'id': str(block.id), 'block_type': response_type, 'html': html}]})
    processor = LLMPageCorrectionProcessor(service, {
        'use_llm': True, 'disable_tqdm': True, 'block_correction_prompt': 'Correct headings'})
    processor(document)
    service.assert_called_once()
    DocumentTOCProcessor()(document)
    assert block.block_type == getattr(BlockTypes, original_type)
    assert block.html == html
    assert len(document.table_of_contents) == (1 if original_type == 'SectionHeader' else 0)
