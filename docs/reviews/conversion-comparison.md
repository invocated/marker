# Bounded conversion comparison

The candidate fixes the selected public table's row and column placement. The seven official rules still pass six checks because the output retains an existing space before a significance star. No surrounding prose changes appeared in the three selected pages. These results do not establish correctness across Marker's supported documents or operating systems.

## Sources and execution

The unchanged source is revision `0248942517ab0953610e81b10d062016766572fe`. The candidate contains the reviewed heading and diagnostic changes plus the frozen table preservation changes. Its `marker/processors/table.py` SHA-256 is `07c36a2d93b7871cc92248bf111972a8aba0d14cf0e4cea704e14ad7287da124`; `marker/processors/table_recon.py` is `03827dae1314c1653d07d4a19ee0617a845bc0f8802eab5e3c69061ca67f3f36`. Each run records every package source hash. The archive uses LF and the Windows snapshot uses CRLF; after line-ending normalization, only the six intended product files differ: those two processors, `document_toc.py`, `converters/pdf.py`, `renderers/__init__.py`, and `schema/document.py`.

Both versions used the same `benchmarks/review/verify_conversion.py` from `c3e19eb`, Python 3.11.13 frozen environment, source files, checker files, settings, and warmed local inference server. The commands and hash requirements are documented in `benchmarks/review/README.md`. Per-run records preserve the exact settings and outputs. Original files and prior outputs were not overwritten.

The final table repair commit is `f25c328`. A source comparison against the tested candidate, normalizing line endings, found only a changed `_stitch_band_headers` docstring. The final docstring describes assignment to the unique containing column interval. The conversion results above belong to the recorded snapshot hashes; no behavior changed between that snapshot and this commit.

The public table source and seven official rules are pinned as described in [the baseline report](marker-baseline.md). The multicolumn control is the repository's `tests/data/olmocr_bench/pdfs/multi_column_page1.pdf`; its SHA-256 is `3ab9f78fb3cd0b0f869a919b1157d44ce1073c51852bff4d11068ce1769cd491`. The rasterized synthetic source has SHA-256 `39924615b93ee3db2596acc3e3b605050ad420c7cc3207c81554282c96251b74`. It contains an Inventory heading and a four-row, three-column table with twelve known cells. It has no embedded text. This synthetic page does not substitute for real scanned-document coverage.

Settings included balanced mode, page zero, one PDF text worker, image extraction enabled, diagnostics requested, and optional LLM processing disabled. The original baseline does not support diagnostic collection. Both versions used model `datalab-to/surya-ocr-2` revision `3b3d4cdf88d6928b0acdc75181b13206ea67c4a3`, vLLM 0.20.1, bfloat16, maximum model length 18000, 8192 batched tokens, 32 sequences, MTP 2 and GPU memory fraction 0.80. The owned server's image ID is `sha256:aef4ebc906574fa2e6e52079937b7d3a8735e218f6353b58667b215e4257a34b`. Its cold startup took 266.85 seconds. Container identity and launch arguments were verified before conversion. The cleanup checks below confirm that the owned server stopped after worker integration.

## Output findings

| Check | Unchanged | Candidate |
| --- | --- | --- |
| Seven official public table rules | 6/7 | 6/7 |
| Public Table 1 shape | 7 rows, 6 columns | Expected 5 rows, 7 columns |
| Public Table 2 shape | Expected 6 rows, 5 columns | Identical |
| Separate IBE and MI headers | No | Yes |
| Five multicolumn reading-order rules | 5/5 | 5/5 |
| Synthetic table, exactly twelve cells and no additional table | Pass | Pass |

The supplemental shape checks are separate from the seven official rules. Both public tables render as Markdown, so the helper's separate HTML/Markdown parsing cannot change their order in this comparison.

Official rule `b5c5b8661b5a272e7a175cdb20d49e67ba0d_pg4_table_03` requires `0.31*` immediately right of `4.11`, with zero allowed differences. In the unchanged output, the values occupy different rows. In the candidate, `/page/0/Table/11` places them in the correct IM row, but its JS cell contains `0.31 *`. The unchanged output already contained that space. The source image shows a superscript star adjacent to the number. The strict official rule remains failed; no normalization or changed denominator conceals it.

Removing only Markdown table lines leaves identical prose for every page. The multicolumn and synthetic Markdown files are identical in full. Public Table 2 is identical in full. TOC titles, order, page IDs and polygons remain identical; the seven observed null heading levels become level 2. Source images support the expected public table shapes and the synthetic cell matrix.

The public page uses PDF text reconstruction for Table 1 and recognition for Table 2 on both versions. The synthetic page uses existing OCR HTML after full-page recognition. Passing these cases does not prove that an OCR table is complete when no clean reference text exists.

## Runtime and memory

| Case | Converter seconds, unchanged → candidate | Peak process-tree RSS bytes, unchanged → candidate | Recognition calls on both |
| --- | --- | --- | --- |
| Public tables | 5.648 → 6.138 | 1,090,637,824 → 1,090,998,272 | 1 crop |
| Multicolumn | 3.780 → 3.271 | 1,077,354,496 → 1,073,664,000 | 0 |
| Raster synthetic | 2.674 → 2.844 | 1,062,191,104 → 1,064,894,464 | 1 full-page |

The timer covers model construction and conversion after imports and source-image rendering. It excludes the shared server's cold startup. RSS samples the Python process tree every 100 ms; it excludes the Docker server and GPU memory and can count shared pages more than once. These are single warmed runs on a shared GPU. They do not establish a throughput improvement or a statistically meaningful slowdown.

## Coverage limits

The repository's pinned Ruff 0.9.10 checks required formatting of the changed files and removal of one unused import in the comparison helper. The reviewer compared Python syntax trees before and after formatting: all six product files were identical. The focused Windows suite passed 101 tests after formatting, and lint passed. The recorded conversion hashes identify the tested snapshot rather than these later formatting bytes.

The frozen candidate passed 101 Linux tests across heading consistency, table diagnostics and table preservation. Those tests exercise fast/balanced settings with OCR enabled/disabled, Form and TableOfContents handling, existing OCR HTML, real table processors and four renderers with controlled inputs, boundary uncertainty and fallback preservation. Mocked recognition and supplied geometry do not validate detectors or inference quality across those combinations.

An isolated archive of `f25c328` also passed the seven original fixture-independent tests in 1.56 seconds. From that archive, the command used the existing frozen interpreter:

```sh
/tmp/marker-baseline-20260912/repo/.venv/bin/python -m pytest tests/config/test_config.py tests/builders/test_ocr_builder.py tests/services/test_service_init.py::test_llm_no_keys tests/providers/test_image_provider.py::test_image_provider -q -p no:cacheprovider --tb=short
```

These tests cover configuration, HTML cleanup, missing-key handling and image-provider behavior. They do not add converter or model-quality coverage.

The original private fixture suite remains unavailable. Its table processor and table merge tests require private fixtures and model-backed document construction. Real merged-cell, cross-page table, form and contents-page conversions remain unverified. So do the full operating-system/mode matrix, real scanned-document completeness, optional LLM rewrite behavior with a live service, and the full public benchmark.

## Actual batch worker verification

The final worker ran through `python -m marker.scripts.validated_batch` with separate temporary outputs on Windows Python 3.13.5 and Linux Python 3.11.13. Both used the existing local model checkpoints and owned vLLM server. No model downloads or remote inference were needed. The tested worker file hashes were:

- `marker/batch/runtime.py`: `ca7ab70724ad687a2dae89af63df65e735026cd2109c3be4415e739fd7fee9a0`
- `marker/batch/validation.py`: `f6f4ca7583c214008d46f8a0cbea371c05c479b63e0314b2a0afaf88c0d9f588`
- `marker/scripts/validated_batch.py`: `8194fa3b3c878bce9edee576eea47df4dfe22790dc8651cdb2338c777fa704eb`

Each invocation used the public multicolumn source, balanced mode and page zero unless specified below. The source, configuration and code identity stayed unchanged between each platform's pass, skip and edited-output checks. For the edited-output test, the reviewer appended a line to the newly generated temporary Markdown, keeping a copy of its original bytes. The worker produced a new successful attempt and preserved the altered prior attempt.

| Platform and case | Result | Whole command seconds |
| --- | --- | --- |
| Windows balanced first invocation | pass | 45.36 |
| Windows identical second invocation | skipped after validation | 14.25 |
| Windows edited prior output | new conversion, pass | 36.94 |
| Linux balanced first invocation | pass | 36.63 |
| Linux identical second invocation | skipped after validation | 9.59 |
| Linux edited prior output | new conversion, pass | 22.35 |
| Linux public table page | unknown, table requires review | 25.17 |
| Linux fast mode with OCR disabled | pass | 29.29 |

The public table page retained its review requirement because the OCR table lacks sufficient completeness evidence. The worker did not turn successful conversion into a validated pass. The multicolumn controls contain no tables, so their pass does not establish complete table extraction. The fast-mode check proves this selected embedded-text page can use the documented local path; it does not establish fast-mode quality across documents.

Whole-command timing includes identity checks, file hashing, model snapshots, subprocess startup and output validation. It differs from converter-only timing above. The first pass for a new code identity can start dedicated lightweight services. Single-page timings on shared hardware cannot establish batch throughput. The Windows edited-output check overlapped part of the Linux verification sequence.

The layout checkpoint snapshot occupies 142,008,126 bytes; the OCR-error snapshot occupies 274,584,088 bytes. Together they add 416,592,214 bytes (about 397.3 MiB) per distinct snapshot parent in the output root. The worker includes the ordering files in the layout snapshot even when balanced mode does not use them. Code/configuration changes can create additional snapshot parents, so these costs are not a one-time global cache estimate. The large vLLM weights remain in the existing shared cache and are not included in these counts.

Actual integration exposed and corrected three runtime issues before the final runs: a custom checkpoint conflicted with Surya's default lightweight-service identity; Surya's spawned server reported the default checkpoint name on subsequent attachment; and Windows' virtual-environment launcher delegated to a base-Python child that owned the socket. Final tests exercised reuse after these corrections. The Windows witness checks the exact launcher/child relationship, executable paths and checkpoint arguments.

The final Linux suite passed 162 tests in 2.72 seconds: 155 focused tests plus the seven original fixture-independent tests. The command was:

```sh
/tmp/marker-baseline-20260912/repo/.venv/bin/python -m pytest tests/processors/test_heading_consistency.py tests/processors/test_table_diagnostics.py tests/processors/test_table_preservation.py tests/batch/test_validated_batch.py tests/config/test_config.py tests/builders/test_ocr_builder.py tests/services/test_service_init.py::test_llm_no_keys tests/providers/test_image_provider.py::test_image_provider -q -p no:cacheprovider --tb=short
```

## Test service cleanup

The reviewer verified the exact owned vLLM container ID before stopping it. The guardian recorded stop exit code 0; a subsequent Docker inspection found no such container. Logs and ownership records were retained. This exercised the guardian's actual stop path after its prior code-only review.

The reviewer also stopped the four Linux and three Windows worker-specific lightweight services, including the three Windows launcher children. Before stopping them, the reviewer checked their recorded PIDs, module names and exact checkpoint arguments. Afterward their ports had no listeners, and only their matching service records were removed. The pre-existing OCR-error process remained alive on its original port. The five pre-existing RAGFlow containers remained running, with their health checks unchanged. No test conversion or owned inference process remains active.
