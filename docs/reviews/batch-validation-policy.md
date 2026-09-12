# External batch validation

This policy applies to the external book conversion worker. Marker CLI file-existence skipping and server success semantics remain unchanged.

The user authorized matching source and configuration records, preservation of existing outputs, retained diagnostics, and continued processing of other books when a book requires review. The user selected the Marker repository as the maintained worker location, with the existing local worker becoming a thin launcher after review.

## Identity and resume

Each attempt records the SHA-256 of the source bytes, the source-relative path, explicit conversion mode, page selection, output format, converter revision, dependency identity, model revision, and validation version. Missing model identity prevents validated completion. Configuration records contain no credentials. The worker uses a fixed, explicit set of supported options; unsupported overrides require review rather than omission from the identity.

Identity also includes the configured source-root identity and a digest of the actual imported converter code. A revision alone cannot identify a dirty working tree or a different installed package. The worker serializes configuration in canonical JSON and includes effective defaults. It converts a private attempt-local source snapshot, verifies its hash, and rechecks the original source before completion. A source change leaves the attempt pending review.

Resume requires the same identity, a passing validation record, and matching hashes for every required output. Similar filenames, file size, process exit status, and historical progress strings do not establish completion. The worker treats legacy outputs without such evidence as pending review. It preserves those outputs and places new attempts in distinct directories.

## Validation

Validation has three results: pass means the required checks succeeded; fail means a check demonstrated a violation; unknown means evidence needed by a check is absent. Both fail and unknown leave the book pending review.

Required checks cover nonempty requested output, parseable metadata, expected page coverage, valid final heading levels, referenced image files, table diagnostics for the final applicable table output, and an intact artifact inventory. Table diagnostics must identify unresolved source text and unavailable OCR completeness evidence. A geometric table score is not proof of completeness. A scanned table without independent completeness evidence remains pending review.

The worker must detect diagnostics invalidated by subsequent optional processors. It cannot certify final output from a diagnostic recorded before a later rewrite. Tests must exercise a later rewrite and missing diagnostics.

Diagnostics bind the final table HTML hash to its block identity. The validation record binds the complete final output inventory. Image references must resolve inside the attempt output directory and appear in that inventory. Traversal outside the directory, missing referenced files, and conflicting table identities fail validation.

## Attempts and records

Conversion runs sequentially in an exclusive attempt directory. The worker never writes into an existing book output directory. It records started, failed, unknown, and passed outcomes separately from process exit status. It stores stdout and stderr for successful and failed attempts, with credential values redacted. It retains attempt records and diagnostics without automatic deletion; the user can apply a retention policy later.

Each attempt owns its records. Resume inspects completed attempt records rather than relying on a shared mutable latest pointer or progress file. Concurrent invocations may duplicate work in separate directories; they cannot overwrite another attempt or declare another attempt complete.

The worker writes completion last, after validation and output hashing. It writes replacement records to a sibling temporary file, flushes them, and replaces the destination. It validates records and artifact hashes again on resume. A truncated or missing record cannot establish completion. These checks protect resume after interrupted writes; an atomic rename alone does not establish power-loss durability on a remote filesystem.

The worker must test record replacement on the supported output storage. Competing attempts cannot share output files or certify one another's files. A failure to persist a record leaves that attempt pending review and does not stop unrelated books. The batch reports an aggregate nonzero result when any book remains pending review, after attempting the other books.

On 2026-09-12, a disposable synthetic probe on the user's SMB output storage passed sibling-file replacement after flush/fsync and confirmed that a truncated temporary file left the previous record parseable. The probe removed its own files. It did not test server power loss, disconnected clients, or simultaneous publishers. The implementation must still test interrupted records and competing attempts, and revalidate artifact hashes on resume.

Alternate output locations count only when a matching validation record and intact artifacts establish identity there. Filename matching across old output roots is insufficient. Existing alternate roots remain unchanged.

## Development context

Upstream commit `5f63811` replaced the dedicated table model with PDF text reconstruction and existing page OCR. Commit `a86bee6` established fast/balanced thresholds and disabled OCR behavior. Commit `b831318` preserved explicit configuration values and budgeted shared inference concurrency. The external worker therefore selects a mode explicitly and keeps sequential orchestration; it does not change inference defaults or introduce nested worker pools.

The inspected external workers accept normalized-title Markdown larger than 100 bytes, omit explicit mode, discard successful diagnostics, and replace progress in place. The revised worker replaces those checks within this external workflow. It does not change the meaning of success in `marker/output.py` or the public server.
