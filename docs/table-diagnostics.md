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
Do not use unresolved counts as an acceptance threshold.

Collection retains selected token text and compact block geometry in metadata;
it releases the raw page character cache through the existing cleanup. Metadata
size grows with selected table tokens across the document. Full-book memory and
later-processor behavior require separate measurement.
