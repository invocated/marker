# Heading change review

## Summary

The default PDF pipeline now collects the table of contents after optional heading and page correction. `DocumentTOCProcessor` copies a single valid HTML h1-h6 level to the heading block before collecting metadata. This addresses early null levels and stale hierarchy after an HTML rewrite.

## Action items

None remain. Review added cross-page hierarchy checks and examined optional page correction responses that request a block-type change.

## Evidence

The final twenty tests pass on Windows Python 3.13.5 and Linux Python 3.11.13. On the unchanged baseline, three fail: the two optional rewrite cases and the initialized default processor order. The tests exercise actual processors with mocked services, JSON/HTML/Markdown/Chunk outputs, cross-page hierarchy, metadata identity, caller-supplied ordering and omission, and `TableConverter` isolation.

Upstream `3ccc195` preserves model heading levels for hierarchy; `d5f6ed7` introduced optional corrections after heading inference. The change preserves those choices and the existing processor grouping mechanism.

## Suggestions and limitations

Custom processor lists retain their supplied order. Ambiguous, absent, or invalid heading tags keep their previous level. Ignored and empty headings retain existing TOC membership. Page correction currently ignores requested block-type changes despite its prompt wording; this patch does not implement relabeling. The tests record that behavior.

## Recommendation

Approve this scoped change. Full conversion comparison remains required by the final verification Bead; unit tests do not establish overall OCR quality.
