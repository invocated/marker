# Bounded conversion comparisons

`verify_conversion.py` records one-page conversion evidence for the reviewed baseline and a candidate checkout. It accepts the pinned public table PDF, the repository's multi-column control, or a generated image-only table PDF. It does not fetch documents or modify an existing output directory.

Use the same script, interpreter, settings, model revision and source bytes for both checkouts. Each invocation requires a new output directory. Keep the unchanged archive intact. `--prepare-only` validates inputs and generates synthetic assets without constructing models.

The public table and rule hashes come from dataset revision `54a96a6fb6a2bd3b297e59869491db4d3625b711`; see [the baseline report](../../docs/reviews/marker-baseline.md) for provenance and coverage limits. The checker root must contain the four unmodified modules listed in `CHECKER_HASHES`, from official olmOCR revision `f7cfe4c22098b154c76b6ec950d1c0a464eecf8d`. Its imports require fuzzysearch, rapidfuzz, tqdm, BeautifulSoup and Playwright; no browser or math check runs for these cases. Keep additional checker dependencies outside the frozen Marker environment.

Example with local public assets:

```sh
python benchmarks/review/verify_conversion.py --repo /path/to/unchanged-marker \
  --out /path/to/new-baseline-result --case table \
  --source /path/to/table.pdf --rules /path/to/table_tests.jsonl \
  --checker-root /path/to/official-checker \
  --model-revision 3b3d4cdf88d6928b0acdc75181b13206ea67c4a3
```

Use `--case multi` without `--source` or `--rules` for the five vendored reading-order checks, evaluated by the repository's existing `_check` function with its hash recorded. Use `--case synthetic --prepare-only` to create a raster table with known text. Reuse that PDF for before/after inference with `--source` and its `--source-sha256`; generating it again can change PDF metadata. The synthetic check requires the expected cells at their exact coordinates, including the header.

The default is balanced mode with `extract_images=True`, matching the effective direct-constructor baseline setting. `--mode fast`, `--disable-ocr`, and `--diagnostics` are explicit variations, not equivalent baseline runs. `use_llm=False` excludes optional enhancement. Inference accepts a loopback endpoint or launches local vLLM with the supplied model revision; it does not call Ollama. Preserve server logs to verify an existing endpoint's model revision and the launched backend's effective defaults. Set the same resource environment variables on both runs.

Outputs include source-page PNG, raw Markdown, metadata, per-table HTML/path snapshots, final table hashes, diagnostics when the candidate provides them, source/code/settings hashes, rule results, elapsed time and sampled memory. The helper tolerates a baseline without diagnostic fields. Table path snapshots distinguish existing HTML from pdftext reconstruction and Surya fallback; existing HTML is not assumed to be OCR. Compare the page image with both raw outputs and exact table cells. A PNG alone is not a visual comparison verdict.

RSS measures the parent and its operating-system children at 100 ms intervals. The process-tree sum can count shared pages more than once and excludes Docker processes, GPU memory and external servers. Recognition counts cover calls to Marker’s recognition predictor, not layout calls, HTTP requests or backend retries. Elapsed time includes cold startup. Instrumentation runs on both versions; these measurements are not exclusive-GPU throughput or exact peak memory.

An exit status of 1 can mean a recorded conversion error or a failed quality check. Consult `record.json`. The public baseline already fails one of its seven table rules. Do not suppress that result, treat missing diagnostics as a completeness pass, or infer whole-library quality from these controls.

## Share one owned local test server

`serve_local.py` uses the installed Surya API to start a test server, verifies that this process created it, records the immutable Docker container ID, and waits for a line of input. Run it in a PTY session that keeps stdin open; a closed input pipe would stop it before comparisons finish. A newline, EOF or the lifetime limit stops only that verified container ID. It refuses an already-running shared server. Startup failure cleanup remains Surya's responsibility. Preserve `server.json` and `server.log` with the comparison results. Ownership and cleanup have code review and compilation checks; the first controlled launch must verify their behavior before claiming runtime coverage.

Example in the established Linux environment, with the cached model path configured for the host:

```sh
DOCKER_HF_CACHE_PATH=/path/to/existing/huggingface/cache \
  /tmp/marker-baseline-20260912/repo/.venv/bin/python \
  /path/to/Marker/benchmarks/review/serve_local.py \
  --out /tmp/marker-shared-review-server \
  --model-revision 3b3d4cdf88d6928b0acdc75181b13206ea67c4a3
```

In the comparison process, set `SURYA_INFERENCE_URL` to the exact loopback `base_url` in `server.json`. Use that endpoint for the unchanged and candidate runs. Match `VLLM_GPU_TYPE=4090`, `VLLM_DTYPE=bfloat16`, `VLLM_MAX_MODEL_LEN=18000`, `VLLM_GPU_MEMORY_UTILIZATION=0.80`, `VLLM_ENABLE_MTP=True` and `VLLM_MTP_TOKENS=2` to the guardian settings; the server's recorded launch command is the authority. The GPU name here controls Surya's budgeting and does not claim that the physical GPU is a 4090.

Run the table command above once for `--repo /tmp/marker-baseline-20260912/repo` and once for a separate candidate copy, with distinct output directories. Repeat for `--case multi` and for the same prepared synthetic PDF and hash. Use `--diagnostics` on both runs if collecting provenance; the unchanged code records unsupported diagnostics rather than pretending they exist. The guardian records cold startup separately. Each attached conversion's elapsed time includes request processing but not server startup; the helper's field name retains `seconds_including_startup` because it also supports owned startup.

Keep the guardian alive until all bounded cases finish, then send a newline. Verify its final status and Docker container absence. Do not stop other services or present shared-GPU timings as throughput benchmarks.
