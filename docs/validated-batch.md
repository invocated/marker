# Validated book conversion

Run the maintained external worker with the Marker Python environment:

```text
python -m marker.scripts.validated_batch --source-root <PDF-root> --output-root <output-root> --profile <local-profile.json> <PDF-or-directory>
```

The worker defaults to balanced mode with OCR available. It processes books in
sequence, continues after failures, and returns a nonzero exit status if any book
remains pending review. It preserves existing book outputs. The output root must
be outside the source root so that attempts cannot become new inputs.

The worker writes Markdown containing HTML tables. This fixed option allows the
validator to compare final table HTML with the saved output, including repeated
tables. Consumers that require pipe-table Markdown may need a separate conversion
step. Marker CLI/server defaults and RPG-RAG are unchanged.

## Local model configuration

Use a local Docker vLLM server for `datalab-to/surya-ocr-2` with an immutable
model revision. Other model names and local model directories are unsupported.
The worker checks the serving process working directory to reject a local
directory that could override Hugging Face revision handling. The worker
inspects the local Docker daemon, image content ID, actual serving arguments,
model revision, and published port. It derives the loopback URL from that
container. It rejects mutable model revisions, ambiguous services, remote Docker
contexts, and custom tokenizer/remote-code overrides it cannot verify.

A one-time local profile selects the maintained service and existing checkpoints:

```json
{
  "docker_container": "marker-validated-vllm",
  "fast_layout_checkpoint": "<local-layout-checkpoint-directory>",
  "ocr_error_checkpoint": "<local-ocr-error-checkpoint-directory>"
}
```

The serving command must include `--model <model>` and `--revision <immutable-HF-commit>`;
`--served-model-name` may provide the API name. Expose container port 8000 on the
local host. The worker does not launch Docker, download model weights, or accept
an asserted model revision as evidence. Start the pinned service before invoking the launcher, using the example below. If no container
selector is supplied, the worker requires exactly one running `surya-vllm`
container with verifiable identity. This discovery does not select a temporary
integration server for future use.

For the tested local NVIDIA Docker setup, the image and model revision were:

- Image: `sha256:aef4ebc906574fa2e6e52079937b7d3a8735e218f6353b58667b215e4257a34b`.
- Model: `datalab-to/surya-ocr-2`, revision `3b3d4cdf88d6928b0acdc75181b13206ea67c4a3`.

With that image and revision present locally, this PowerShell example starts a
named service. Replace the cache path with your existing Hugging Face cache.
`--pull never` and `HF_HUB_OFFLINE=1` prevent this example from downloading assets.
The cache must contain the stated model revision and its tokenizer files.

```powershell
docker run --detach --name marker-validated-vllm --gpus all --ipc host --pull never --publish 127.0.0.1:35820:8000 --mount "type=bind,source=<existing-HF-cache>,target=/root/.cache/huggingface,readonly" --env HF_HUB_OFFLINE=1 sha256:aef4ebc906574fa2e6e52079937b7d3a8735e218f6353b58667b215e4257a34b --model datalab-to/surya-ocr-2 --revision 3b3d4cdf88d6928b0acdc75181b13206ea67c4a3 --dtype bfloat16 --max-model-len 18000 --max-num-seqs 32 --max-num-batched-tokens 8192 --gpu-memory-utilization 0.8
```

Set `docker_container` to `marker-validated-vllm` in the profile and set
`MARKER_BATCH_PROFILE` to that JSON file for the maintained local launchers.
After a restart, use `docker start marker-validated-vllm`. Use
`docker stop marker-validated-vllm` when you want to release its GPU allocation.
The worker does not change that service. Different image or launch settings
produce a different model identity and prevent reuse of earlier completion
records. GPU capacity and vLLM startup must be checked on the local machine;
the worker leaves books pending if the service cannot provide verified evidence.

Checkpoint options can be omitted when the configured Surya checkpoints exist in
the local cache. Missing local checkpoints or unverifiable server evidence leave
the book pending review. Configuration is shared across books; no per-book manual
certification is required.

The worker copies lightweight checkpoints into a shared content-addressed cache
under `.marker-models`. It verifies their contents and injects the exact paths.
Lightweight servers use a separate worker namespace derived from runtime and
checkpoint identity, preserving pre-existing Surya services. These separate
services add startup time and memory use; old runtime cache versions also consume
disk space. Surya keeps these
servers alive for reuse. Their PIDs and creation times appear in runtime evidence;
owned integration servers require cleanup after testing. The worker does not stop
unrelated services or delete old cache versions.

`--mode fast --disable-ocr` supports a local digital-text compatibility path.
Balanced mode requires the VLM for layout even with `--disable-ocr`.

## Attempts and validation

Each source-relative directory contains a `.marker-attempts` directory. Every
attempt has a UUID directory containing its source snapshot, output, runtime
evidence, stdout/stderr, process exit records, and completion record. Prior book
outputs remain in place. Model data lives outside individual attempts.

The conversion subprocess derives its imported Marker/Surya source hashes,
dependency versions, effective setting fingerprints, and model evidence. The
worker hashes the source snapshot and rechecks the original source before
completion or skipping. Unsupported converter/renderer/LLM overrides are absent
from the fixed interface. Output is Markdown; mode, page selection, and OCR
selection are explicit configuration values in identity records.

Validation checks page coverage, heading metadata, required images, table
provenance, final rendered table content, the expected Markdown bytes, and output
inventory hashes. Table diagnostics must describe an accepted digital candidate
with accounted source occurrences and no review flags. Missing evidence, OCR
completeness uncertainty, and later table changes prevent a pass. A pass means
these checks succeeded; it does not certify every word or semantic row assignment.

Resume checks source/configuration/runtime/model identity, validation version,
artifact hashes, source snapshot, runtime evidence, and retained process
diagnostics. It rejects malformed or interrupted records. Legacy size-only output
never establishes completion. `--alternate-output-root` may identify another root
containing matching validated attempts; the worker leaves it unchanged.

Completion records are written last through flushed sibling-file replacement.
There is no shared mutable latest pointer. Concurrent invocations can create
separate attempts but cannot certify each other's files. Resume rechecks artifacts;
file replacement does not establish server power-loss durability.

The worker retains diagnostics for successful and failed processes, with credential
values redacted. It does not delete attempts or logs. Source snapshots and extracted
text remain local. A failed record write leaves the attempt pending and does not
stop other books.
