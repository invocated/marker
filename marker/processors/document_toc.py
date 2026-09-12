import re

from bs4 import BeautifulSoup

from marker.processors import BaseProcessor
from marker.schema import BlockTypes
from marker.schema.document import Document


class DocumentTOCProcessor(BaseProcessor):
    """
    A processor for generating a table of contents for the document.

    Run after heading corrections to capture their final levels. A single
    HTML h1-h6 heading supplies the block level. Other HTML retains the
    existing level; ignored and empty headings retain their TOC membership.
    Caller-supplied processor lists control when this processor runs.
    """
    block_types = (BlockTypes.SectionHeader, )

    def __call__(self, document: Document):
        toc = []
        for page in document.pages:
            for block in page.contained_blocks(document, self.block_types):
                # Final HTML can reflect corrections made after heading inference.
                # Leave ambiguous or invalid tags and TOC membership unchanged.
                if block.html:
                    headings = BeautifulSoup(block.html, "html.parser").find_all(
                        re.compile(r"^h\d+$", re.IGNORECASE)
                    )
                    if len(headings) == 1 and headings[0].name in (
                        "h1", "h2", "h3", "h4", "h5", "h6"
                    ):
                        block.heading_level = int(headings[0].name[1])
                toc.append({
                    "title": block.raw_text(document).strip(),
                    "heading_level": block.heading_level,
                    "page_id": page.page_id,
                    "polygon": block.polygon.polygon
                })
        document.table_of_contents = toc
