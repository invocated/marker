# Table preservation review

## Summary

The repair for `marker-ubv.3` preserves wide text and joins staggered fragments in the tested tables. It rejects unresolved placement and keeps overlapping source text when a table does not represent that text. The reviewer inspected the production diff, synthetic failures, original page images, and matched conversion outputs.

## Action Items

None. Review findings about transitive row overlap, column overlap, boundary rounding, blank-key rows, placeholder columns, and cleanup across different rows have tests and corrections in the reviewed implementation.

## Evidence

- Commit `e088a82` contains failing regression tests before the production fix. The unchanged implementation failed 13 of 25 initial cases. Later tests cover additional findings from review.
- The final focused suite passed 101 tests on Windows and Linux: 54 preservation tests, 27 diagnostic tests, and 20 heading tests. Tests exercise both converters and all four renderers through controlled inputs, existing OCR HTML, failed fallback, fast/balanced settings, disabled OCR, forms, contents blocks, and processor configuration.
- The reviewer compared each cell in the authorized private original with the reconstructed table. The header and eight data rows retain three columns, including the reported missing and truncated text. This uses a controlled rectangle, not a replay of the unavailable original detector bounds. Private assets remain outside the repository.
- A matched public-page conversion changes Table 1 from seven rows and six columns to the original's five rows and seven columns. It preserves missing-value underscores and separates the IBE and MI columns. Table 2 and surrounding prose remain identical.
- The official public checker remains at six of seven passing rules. The remaining rule expects `0.31*`; both old and new output contain `0.31 *`. The new output places that value in the correct row. This existing superscript-spacing error remains unresolved; the checker result must not be reported as seven passes.
- Multi-column prose and an image-only synthetic table produce identical Markdown before and after the changes. Their five order checks and twelve expected cells pass.
- Recognition calls remain one table crop for the public page, zero for the multi-column page, and one full-page call for the synthetic image. Converter times change from 5.648 to 6.138 seconds, 3.780 to 3.271 seconds, and 2.674 to 2.844 seconds. Process-tree peak memory remains about 1.09, 1.07, and 1.06 GB. These are single warmed runs on a shared GPU, not a throughput estimate.
- In 100 direct extraction-and-reconstruction runs with diagnostics enabled, median private-case time changes from 1.744 to 2.025 ms and public-case time from 0.773 to 1.302 ms. Peak Python allocations change from 35,989 to 41,773 bytes and 25,231 to 36,809 bytes. These measurements exclude model inference and whole-book memory.

## Development intent and tradeoffs

The implementation retains the HTML representation introduced by upstream `5f63811`, the mode thresholds and disabled-OCR behavior from `a86bee6`, and disjoint-line filtering from `2173678`. It does not raise reconstruction scores. Every selected occurrence needs a candidate assignment before the existing score threshold applies.

The checks can reject valid ambiguous layouts and cause additional OCR on documents outside this sample. Source-line bounds can exceed selected character bounds. Conservative cleanup can retain duplicate text when one source block spans several cells. These costs preserve evidence for review instead of deleting unrepresented text. The tests demonstrate scoped behavior; they do not establish reliable table classification or semantic completeness across documents.

OCR reference comparison counts case-sensitive whitespace tokens. Typography, punctuation, hyphenation, and corrupt PDF text can cause false alarms. Existing OCR has no independent completeness guarantee. Later rewrites can invalidate candidate diagnostics, so the external worker must bind validation to final output.

## Suggestions

Use the recorded comparison procedure when adding representative documents. Keep exact cell assertions and prose comparisons separate from the official benchmark score.

## Recommendation

Approve the scoped table repair. The unavailable private upstream fixture suite, broad document coverage, and the existing superscript-spacing error remain limits on confidence. No percentage can summarize those gaps as a probability of correctness.
