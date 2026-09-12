# Bounded conversion comparison

The candidate fixes the selected public table's row and column placement. The seven official rules still pass six checks because the output retains an existing space before a significance star. No surrounding prose changes appeared in the three selected pages. These results do not establish correctness across Marker's supported documents or operating systems.

## Sources and execution

The unchanged source is revision `0248942517ab0953610e81b10d062016766572fe`. The candidate contains the reviewed heading and diagnostic changes plus the frozen table preservation changes. Its `marker/processors/table.py` SHA-256 is `07c36a2d93b7871cc92248bf111972a8aba0d14cf0e4cea704e14ad7287da124`; `marker/processors/table_recon.py` is `03827dae1314c1653d07d4a19ee0617a845bc0f8802eab5e3c69061ca67f3f36`. Each run records every package source hash. The archive uses LF and the Windows snapshot uses CRLF; after line-ending normalization, only the six intended product files differ: those two processors, `document_toc.py`, `converters/pdf.py`, `renderers/__init__.py`, and `schema/document.py`.

Both versions used the same `benchmarks/review/verify_conversion.py` from `c3e19eb`, Python 3.11.13 frozen environment, source files, checker files, settings, and warmed local inference server. The commands and hash requirements are documented in `benchmarks/review/README.md`. Per-run records preserve the exact settings and outputs. Original files and prior outputs were not overwritten.

The final table repair commit is `f25c328`. A source comparison against the tested candidate, normalizing line endings, found only a changed `_stitch_band_headers` docstring. The final docstring describes assignment to the unique containing column interval. The conversion results above belong to the recorded snapshot hashes; no behavior changed between that snapshot and this commit.

The public table source and seven official rules are pinned as described in [the baseline report](marker-baseline.md). The multicolumn control is the repository's `tests/data/olmocr_bench/pdfs/multi_column_page1.pdf`; its SHA-256 is `3ab9f78fb3cd0b0f869a919b1157d44ce1073c51852bff4d11068ce1769cd491`. The rasterized synthetic source has SHA-256 `39924615b93ee3db2596acc3e3b605050ad420c7cc3207c81554282c96251b74`. It contains an Inventory heading and a four-row, three-column table with twelve known cells. It has no embedded text. This synthetic page does not substitute for real scanned-document coverage.

Settings included balanced mode, page zero, one PDF text worker, image extraction enabled, diagnostics requested, and optional LLM processing disabled. The original baseline does not support diagnostic collection. Both versions used model `datalab-to/surya-ocr-2` revision `3b3d4cdf88d6928b0acdc75181b13206ea67c4a3`, vLLM 0.20.1, bfloat16, maximum model length 18000, 8192 batched tokens, 32 sequences, MTP 2 and GPU memory fraction 0.80. The owned server's image ID is `sha256:aef4ebc906574fa2e6e52079937b7d3a8735e218f6353b58667b215e4257a34b`. Its cold startup took 266.85 seconds. Container identity and launch arguments were verified before conversion; cleanup remains a separate required check while the server supports worker integration.

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

The frozen candidate passed 101 Linux tests across heading consistency, table diagnostics and table preservation. Those tests exercise fast/balanced settings with OCR enabled/disabled, Form and TableOfContents handling, existing OCR HTML, real table processors and four renderers with controlled inputs, boundary uncertainty and fallback preservation. Mocked recognition and supplied geometry do not validate detectors or inference quality across those combinations.

An isolated archive of `f25c328` also passed the seven original fixture-independent tests in 1.56 seconds. From that archive, the command used the existing frozen interpreter:

```sh
/tmp/marker-baseline-20260912/repo/.venv/bin/python -m pytest tests/config/test_config.py tests/builders/test_ocr_builder.py tests/services/test_service_init.py::test_llm_no_keys tests/providers/test_image_provider.py::test_image_provider -q -p no:cacheprovider --tb=short
```

These tests cover configuration, HTML cleanup, missing-key handling and image-provider behavior. They do not add converter or model-quality coverage.

The original private fixture suite remains unavailable. Its table processor and table merge tests require private fixtures and model-backed document construction. Real merged-cell, cross-page table, form and contents-page conversions remain unverified. So do the full operating-system/mode matrix, real scanned-document completeness, optional LLM rewrite behavior with a live service, and the full public benchmark. The owned server's cleanup must be recorded after the remaining integration work.
