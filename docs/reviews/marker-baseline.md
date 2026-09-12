# Conversion baseline before changes

The reviewer accepted this alternative baseline for `marker-ubv.1` on 2026-09-12. It documents working controls and existing failures at commit `0248942517ab0953610e81b10d062016766572fe`. It does not establish general conversion correctness or parity with the unavailable `datalab-to/pdfs` fixtures.

## Environment and commands

An archive of that commit ran in an isolated WSL Ubuntu directory. Python was 3.11.13; uv was 0.8.13. Dependencies came from the unchanged lock with:

```sh
uv sync --python 3.11 --frozen --group dev --extra full
.venv/bin/python -m pytest tests/config/test_config.py tests/builders/test_ocr_builder.py tests/services/test_service_init.py::test_llm_no_keys tests/providers/test_image_provider.py::test_image_provider -q -p no:cacheprovider --tb=short
```

The seven tests passed in 2.77 seconds. Installed versions included Marker 2.0.0, Surya 0.22.1, Torch 2.13.0 and pytest 9.1.1. Imports came from the isolated source archive. These tests cover configuration, HTML cleanup, missing-key handling and the image provider, not complete conversion.

The existing Windows Python 3.13.5 CPU run produced four passes, six unavailable-dataset setup errors and one temporary-image reopening error. The image-provider test passed on Linux. No credentials or substitute fixture bytes were supplied to the original private suite.

## Characterization results

The temporary synthetic table harness exercised thirteen cases through unchanged reconstruction and, for boundary cases, character-level extraction. Ten matched desired cells. Wide continuation loss, wide header loss and prose included inside the supplied rectangle reproduced existing failures at score 1.0. Outside-rectangle prose exclusion, adjacent tables, row association, two columns, repeated/blank values, multiline headers, and intentional symbol-column merging had working controls. These supplied rectangles do not test detector judgments.

The heading harness used actual processors, schema blocks and JSON, HTML, Markdown and Chunk renderers. It asserted titles, order, page IDs, polygons and hierarchy. It reproduced early TOC collection and stale metadata after a mocked heading rewrite. It also recorded existing behavior for empty, ignored and malformed headings. Mocked responses did not involve a model service.

An authorized private original reproduced the reported empty cells with score `0.8703703703703703` using character-preserving extraction and a controlled rectangle. Original bytes and saved outputs remained unchanged. Private content, paths and extracted assets are excluded from this report.

## Public table page

The public [olmOCR-bench dataset](https://huggingface.co/datasets/allenai/olmOCR-bench/tree/54a96a6fb6a2bd3b297e59869491db4d3625b711) was pinned to revision `54a96a6fb6a2bd3b297e59869491db4d3625b711`. Its card declares `odc-by`; that differs from the repository's vendored-page README claim and must not be replaced with an assumed Apache license for the whole dataset.

Selected assets:

| Asset relative to dataset root | SHA-256 |
| --- | --- |
| `bench_data/pdfs/tables/b5c5b8661b5a272e7a175cdb20d49e67ba0d_pg4.pdf` | `7a509c59f5fabf77b4e1f45b87619dfb76773836b0e0d521d9e495cca1cd4084` |
| `bench_data/table_tests.jsonl` | `e37a99bd60de56c62cd3f4c1b7910b603641901c15ae119f849ffefa86cde120` |

The one-page conversion passed `mode="balanced"`, `page_range=[0]`, `disable_tqdm=True`, `disable_image_extraction=True`, and `pdftext_workers=1` to `PdfConverter`, followed by `text_from_rendered`. The image flag was a requested setting, not an effective one: `ConfigParser` translates that CLI flag to `extract_images=False`, but the direct constructor does not. The renderer therefore retained its default `extract_images=True`. Comparisons must preserve this effective setting or record the difference. Output remained raw Markdown without benchmark postprocessing. Its SHA-256 is `fbf77747b2b291b9df1333b96b26a99bfbd0697a5532bd28e1cdb7d923153303`.

Local inference used model `datalab-to/surya-ocr-2` revision `3b3d4cdf88d6928b0acdc75181b13206ea67c4a3`, Docker image `vllm/vllm-openai:v0.20.1`, bfloat16, maximum model length 18000, 8192 batched tokens, 32 sequences, MTP 2 and GPU memory fraction 0.80. A shortened 150-second startup deadline expired during compilation. The retry used Surya's 600-second startup allowance and completed in 270.25 seconds, including cold startup. The RTX 4080 SUPER already had other work, so this is not sustained or exclusive-GPU throughput. The test container was removed; unrelated services were preserved.

Marker logged `tables_pdftext=1`, `tables_ocr=1`, `tables_total=2`. The three headings exported null levels.

The unchanged [official checker](https://github.com/allenai/olmocr/tree/f7cfe4c22098b154c76b6ec950d1c0a464eecf8d/olmocr/bench) was pinned to `f7cfe4c22098b154c76b6ec950d1c0a464eecf8d`. Its `load_single_test(rule).run(markdown)` evaluated the seven matching records. Six passed. Rule `b5c5b8661b5a272e7a175cdb20d49e67ba0d_pg4_table_03` failed: it expects `0.31*` immediately right of `4.11`, but the output places the values on different rows. This is one selected page, not an overall benchmark score.

## Public wrong-row diagnosis

The failure occurs in Table 1, the means and correlation table. Independent PDF text extraction used `dictionary_output(..., page_range=[0], workers=1, flatten_pdf=True, keep_chars=True, quote_loosebox=False)`. Passing rectangle `[60,463,540,513]` through `table_lines_from_pdftext` and `reconstruct_table_html` reproduces the same seven rows and six columns as the conversion output at score `0.7870370370370371`, above the balanced acceptance threshold of 0.75.

The source extraction represents the correlation cells at y=473.77 and the row label and mean at y=475.18, despite their overlapping vertical extents. Reconstruction treats these as separate rows. The next data row has the same pattern. This reproduction locates a failure in PDF text reconstruction; it does not require OCR to explain the split. The original aggregate conversion statistics do not attribute individual tables, so they alone cannot prove which path produced Table 1.

## Required comparison after changes

- Repeat the fixture-independent tests and synthetic controls on unchanged and changed code with the same inputs. Existing desired failures should remain identified until a scoped fix addresses them.
- Repeat this public page with the recorded settings and official rules. Compare exact cells, headings, surrounding text and diagnostics; do not accept an aggregate score that hides a new failure.
- For table changes, include fast, balanced and disabled-OCR behavior, forms, contents pages, merged cells, nearby prose and OCR/rewrite paths. Do not infer these from heading tests.
- For heading changes, check custom processor lists and all four metadata renderers with mocked optional rewrites. Preserve titles, order, coordinates and documented ignored/malformed behavior.
- Validate the final output after optional rewrites. An earlier diagnostic cannot certify a later changed table.
- Measure recognition calls and resource costs on representative inputs. The startup timing here cannot establish a throughput baseline.

The original private suite, full public benchmark, scanned-page completeness, full OS/mode matrix and historical detector replay remain unverified. `marker-ubv.7` must distinguish executed checks, existing failures and remaining gaps before final acceptance.
