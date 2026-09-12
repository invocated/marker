# Batch worker review

## Summary

The maintained worker replaces filename/size acceptance in the local book workflow with source, runtime, model, and output checks. It preserves earlier outputs and continues other books when an attempt fails or needs review. The reviewer inspected the implementation and required corrections before acceptance.

## Action Items

None. Final integration achieved the expected outcomes, and the test operator verified cleanup of owned services while preserving existing services.

## Findings resolved

- Windows rooted paths could hang validation, and a directory junction could redirect it outside the attempt. The validator rejects links, junctions, traversal, and rooted artifact paths before resolving them.
- Missing final tables, changed table HTML, empty provenance, and nonempty truncated Markdown could pass early drafts. The worker binds diagnostics to final blocks, compares rendered HTML tables including duplicate counts, and verifies expected Markdown bytes. Valid controls and targeted mutations exercise each check.
- Malformed metadata and reference-style images escaped early checks. Validation parses rendered Markdown and rejects absent images or malformed evidence.
- A changed source could authorize a stale skip after a long probe. The worker rechecks the original before skipping and before completion. It verifies source snapshots, prior runtime evidence, process records, logs, and the complete output inventory on resume.
- Shared Surya services could conflict with the worker's checkpoint path or belong to an older environment. Worker services use a separate runtime/checkpoint namespace, inherited checkpoint settings, and verified interpreter/module/checkpoint arguments. Windows verification includes the virtual-environment launcher's child and parent process identities.
- Balanced layout still needs the VLM when OCR is disabled. The model requirement follows mode and OCR behavior, rather than OCR alone.
- A model label, mutable revision, or local directory with an arbitrary revision argument could masquerade as immutable model identity. The supported Docker route verifies the documented Hugging Face model, revision, image, serving arguments/process, local resolution, and port. It rejects unsupported local models and custom tokenizer/code overrides.
- Checkpoint cache locations changed identity across alternate output roots. Stable identity now uses model contents; runtime evidence retains the actual paths.

## Verification

The final focused Windows suite passed 155 tests: 54 worker tests and 101 table/heading tests. Linux passed those tests plus seven original fixture-independent tests, for 162 passes. Pinned Ruff 0.9.10 lint and formatting checks passed. The independent validator reviewer reran valid controls, all original negative cases, and altered record/source/log/process/output cases with no remaining reproduced blocker.

Tests cover record-write interruption, missing completion, changed source/configuration/runtime/model evidence, concurrent separate attempts, continued processing after failed conversion or record persistence, timeout diagnostics, credential redaction, alternate roots, and rendered-table loss. These tests use controlled failures; they do not simulate every storage or process failure.

The final worker completed the digital control on Windows and then skipped it after revalidation. The measured commands took 45.36 and 14.25 seconds. Editing the temporary output forced fresh conversion, which passed in 36.94 seconds. Linux completion, skip, and edited-output conversion passed in 36.63, 9.59, and 22.35 seconds. The public page completed conversion and remained unknown because its OCR table lacks independent completeness evidence (25.17 seconds). Linux fast mode with OCR disabled passed in 29.29 seconds. These are bounded shared-resource measurements, not whole-book throughput estimates.

Both existing local launchers now delegate to the maintained worker with their original targets, explicit balanced mode, and validated alternate-root search. They use the prepared environment without automatic dependency synchronization. The local procedure now describes validation and pending review. The reviewer checked installed hashes, exact backups, and command dispatch under mocked execution. No launcher initiated a book conversion during verification. The worker itself ran through its actual subprocess path on Windows and Linux as described above.

## Development intent and tradeoffs

Upstream `5f63811` established HTML reconstruction and recognition fallback, `a86bee6` established mode/OCR behavior, and `b831318` retained shared inference and explicit configuration values. The worker uses those converter interfaces without changing public CLI/server success semantics or Surya source. It runs books in sequence and isolates only the service identities needed for verification.

The worker exports HTML tables inside Markdown so it can compare final tables without a second pipe-table conversion. Consumers expecting pipe tables must account for this option. Verified model snapshots and separate lightweight services consume disk, memory, and startup time. A skip still hashes artifacts and probes the runtime. The procedure requires a pinned local Docker service; the worker does not deploy it or download weights.

OCR tables without independent completeness evidence remain pending review. A pass means the specified checks succeeded, not that every word or geometric assignment is correct. Coherent modification of local evidence and artifacts is outside the authentication scope; these records are not signed. Sibling-file replacement and resume checks do not prove power-loss durability on network storage.

## Recommendation

Approve the scoped implementation and local workflow updates. Keep the unavailable private fixture suite and broader document coverage limits visible in the final report.
