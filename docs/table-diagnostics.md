# Table diagnostics

Set `collect_table_diagnostics` to `true` in the Marker configuration to add
`table_diagnostics` to rendered metadata. The default is `false`; the metadata
key is absent when collection is disabled.

This option records evidence from `TableProcessor`. It does not change table
boundaries, reconstruction scores, OCR calls, conversion success, or skip rules.
It does not certify completeness or correct row placement.

Each table record contains:

- `block_id`, `block_type`, and `bbox`: the detected block and its existing region.
- `boundary_rule` and `semantic_ownership`: selection uses token centers inside
  the region; semantic ownership remains `unknown`.
- `neighbors`: up to eight nearby top-level blocks, with their types, regions,
  overlap, distance, and eligibility for the existing cleanup rule.
  `neighbors_omitted` reports the remaining count. No neighboring text is copied.
- `source_kind`: digital text, corrupt or empty text, unavailable text, existing
  OCR HTML, or existing HTML with no verified extraction origin. The existing
  corruption check examines private-use/replacement glyphs in the first 40 lines;
  it does not establish that other text is correct.
- `spans`: one entry per selected token occurrence, including its text and
  coordinates. Repeated text has separate occurrence IDs. Coordinates use token
  horizontal bounds and source-line vertical bounds, not individual character
  rectangles. `emitted` entries identify the candidate header/body row and column.
  `unresolved` entries give the reconstruction guard that left them unassigned.
- `excluded_spans`: selected leader-only tokens excluded by the existing tokenizer.
  This list does not inventory every character outside the selected region.
- `assignment_stage`: assignments refer to the `reconstruction_candidate`.
  `reconstruction_accepted` distinguishes an accepted candidate from one that
  triggered fallback. Candidate assignments do not describe replacement OCR HTML.
- `html_sha256_after_table_processor`: identifies HTML at this processing stage.
  Later processors can rewrite it; this is not a final-output validation record.

`completeness` remains `unknown`. Missing text can produce unresolved occurrences,
but the reconstruction can also assign every occurrence to the wrong row. Nearby
prose can receive an emitted assignment. Numeric continuation text and valid
private-use glyphs can produce unresolved evidence without establishing a defect.
An unresolved span now prevents reconstruction acceptance; the score is unchanged.
This does not establish whether fallback OCR resolves the uncertainty.

Collection retains selected token text and compact block geometry in metadata;
it releases the raw page character cache through the existing cleanup. Metadata
size grows with selected table tokens across the document. Full-book memory and
later-processor behavior require separate measurement.

## Reconstruction decisions

Reconstruction now requires an assignment for each selected source token. It merges
line fragments only when one group has sufficient shared vertical overlap and
nonoverlapping horizontal spans. Ambiguous groups require review. Continuations
must fit one column interval and satisfy a bounded line gap; final-row continuation
also requires earlier wrap-gap evidence in that column. These are geometric checks,
not a guarantee that prose and cells have different shapes.

The ordinary `Table` processor preserves underscore placeholders as cell values.
`Form` and `TableOfContents` retain leader filtering. Single and double hyphens remain
cell values. Named columns containing symbols remain columns; unnamed checkbox
columns retain the existing merge behavior.

`source_coverage` is `accounted` for an assigned reconstruction candidate,
`unresolved` for rejected span or row ambiguity, and `unknown` when a usable
reference or result is absent. `requires_review` identifies unresolved evidence.
Use these with `reconstruction_accepted` and the HTML hash. They do not describe
later rewritten output. Final OCR coverage remains `unknown`.

Selected token horizontal bounds or source-line vertical bounds crossing the
detected boundary prevent acceptance;
the processor does not enlarge that boundary. The tokenizer's default selection
still uses centers. `source_crosses_boundary` records this rejection.

OCR output missing a closing table tag no longer becomes a successful table through
HTML repair. When fallback OCR has a digital reference, `ocr_reference_omissions`
records missing case-sensitive whitespace-token occurrences. Whitespace differences
normalize; typography, punctuation, line-break hyphenation, and corrupt embedded
text can produce false alarms. Matching tokens does not establish correct rows.
`ocr_reference_comparison` records this limitation, and `completeness` remains
`unknown`. Existing full-page OCR output has no new completeness guarantee.

Cleanup removes an overlapping text block only when its token sequence occurs
within one table cell. It consumes each represented occurrence once. Text from
separate rows or in a different order cannot authorize removal. Unrepresented text
remains available; this conservative rule can retain duplicates when a source block
spans several cells. Failed or disabled OCR retains overlapping source text.

Boundary rejection permits 0.051 points for the tokenizer's one-decimal rounding.
Vertical evidence uses source-line bounds, which can exceed the extent of selected
characters. A crossing line therefore requires review without claiming that a
specific selected character crossed the boundary.

For forms, cleanup compares label, paragraph, and table-cell text segments. It
retains unrelated text and consumes a represented segment occurrence once.
