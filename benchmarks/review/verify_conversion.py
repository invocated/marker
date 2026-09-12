"""Record bounded, local conversion evidence without changing source PDFs."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import runpy
import sys
import threading
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlparse


CHECKER_REVISION = "f7cfe4c22098b154c76b6ec950d1c0a464eecf8d"
CHECKER_HASHES = {
    "olmocr/bench/tests.py": "ff36b3cdf81c4a94f3e43cb78de8a31607eb6a0d140d0bfbfb2fe44122b55727",
    "olmocr/bench/table_parsing.py": "f120f7a207f2f9ff99b7a5d7cc8b144250b60f4ce9bb160405228866d93dbb79",
    "olmocr/bench/katex/render.py": "7e04305b57255013362ecc43e183ccd319fb187d1b900c941df575b871c9df0b",
    "olmocr/repeatdetect.py": "29d7ef1fc2a2fa7259eba40a00fa7eca355634f8f4f1af6c086682c8164ae317",
}
TABLE_HASH = "7a509c59f5fabf77b4e1f45b87619dfb76773836b0e0d521d9e495cca1cd4084"
RULES_HASH = "e37a99bd60de56c62cd3f4c1b7910b603641901c15ae119f849ffefa86cde120"
TABLE_NAME = "tables/b5c5b8661b5a272e7a175cdb20d49e67ba0d_pg4.pdf"
MULTI_HASH = "3ab9f78fb3cd0b0f869a919b1157d44ce1073c51852bff4d11068ce1769cd491"
VENDORED_RULES_HASH = "77656afd77c387221754b4ef742d3507090489bbdc7c94a9040a328b3368a23f"
VENDORED_RULES_LF_HASH = "eb069771c2e6f5b3820ca82b0879ecb5fbb403312b08eac9d0bbbce72a5351da"
EXPECTED = [["Item", "Count", "Note"], ["Alpha", "12", "Blue"],
            ["Beta", "34", "Green"], ["Gamma", "56", "Amber"]]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked(path, expected):
    if digest(path) != expected:
        raise ValueError(f"Input hash mismatch: {Path(path).name}")
    return Path(path)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


def check_endpoint(endpoint):
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.query:
            raise ValueError("Use a loopback inference endpoint without embedded credentials or query")


def synthetic(out):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1200, 1000), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=32)
    draw.text((80, 80), "Inventory", font=font, fill="black")
    for row, cells in enumerate(EXPECTED):
        for col, text in enumerate(cells):
            x, y = 80 + col * 340, 200 + row * 130
            draw.rectangle((x, y, x + 340, y + 130), outline="black", width=3)
            draw.text((x + 25, y + 40), text, font=font, fill="black")
    image.save(out / "synthetic.png")
    image.save(out / "synthetic.pdf", resolution=150)
    write_json(out / "expected.json", EXPECTED)
    return out / "synthetic.pdf"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", choices=["table", "multi", "synthetic"], required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--source-sha256")
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--checker-root", type=Path)
    parser.add_argument("--mode", choices=["fast", "balanced"], default="balanced")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--disable-ocr", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--model-revision", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.model_revision):
        raise ValueError("Use an immutable 40-character model revision")
    repo = args.repo.resolve()
    # A fresh directory prevents accidental replacement of earlier evidence.
    args.out.mkdir(parents=True, exist_ok=False)
    out = args.out.resolve()
    sys.path.insert(0, str(repo))
    rules = []
    rule_path = None
    if args.case == "table":
        source = checked(args.source, TABLE_HASH)
        checked(args.rules, RULES_HASH)
        rule_path = args.rules
        rules = [json.loads(x) for x in args.rules.read_text().splitlines()
                 if json.loads(x)["pdf"] == TABLE_NAME]
        if len(rules) != 7:
            raise ValueError("Expected seven official table rules")
    elif args.case == "multi":
        source = checked(repo / "tests/data/olmocr_bench/pdfs/multi_column_page1.pdf", MULTI_HASH)
        rule_path = repo / "tests/data/olmocr_bench/tests.jsonl"
        if digest(rule_path) not in {VENDORED_RULES_HASH, VENDORED_RULES_LF_HASH}:
            raise ValueError("Vendored rules do not match the reviewed LF or CRLF bytes")
        rules = [json.loads(x) for x in rule_path.read_text().splitlines()
                 if json.loads(x)["pdf"] == "multi_column_page1.pdf"]
    else:
        source = checked(args.source, args.source_sha256) if args.source else synthetic(out)
    source = source.resolve()
    source_hash = digest(source)
    code = {str(p.relative_to(repo)): digest(p) for p in sorted((repo / "marker").rglob("*.py"))}
    config = dict(mode=args.mode, page_range=[0], disable_tqdm=True,
                  extract_images=True, pdftext_workers=1, use_llm=False,
                  disable_ocr=args.disable_ocr, collect_table_diagnostics=args.diagnostics)
    record = dict(case=args.case, source_sha256=source_hash, code_hashes=code,
                  rules_sha256=digest(rule_path) if rule_path else None,
                  settings=config, python=sys.version, os=platform.platform(),
                  model_revision_requested=args.model_revision,
                  model_revision_verification="caller must retain server revision evidence",
                  helper_sha256=digest(__file__), status="prepared")
    write_json(out / "record.json", record)
    if args.prepare_only:
        return 0
    endpoint = os.environ.get("SURYA_INFERENCE_URL")
    check_endpoint(endpoint)
    if not endpoint:
        os.environ["SURYA_INFERENCE_BACKEND"] = "vllm"
        extra = os.environ.get("VLLM_EXTRA_ARGS", "").split()
        if "--revision" in extra:
            if extra[extra.index("--revision") + 1] != args.model_revision:
                raise ValueError("Conflicting model revision")
        else:
            os.environ["VLLM_EXTRA_ARGS"] = " ".join(extra + ["--revision", args.model_revision])
        record["model_revision_verification"] = "revision passed to owned vLLM launch; retain startup log"
    record["inference_settings"] = {k: os.environ.get(k) for k in (
        "SURYA_INFERENCE_BACKEND", "SURYA_INFERENCE_URL", "SURYA_MODEL_CHECKPOINT",
        "VLLM_DOCKER_IMAGE", "VLLM_GPU_MEMORY_UTILIZATION", "VLLM_DTYPE",
        "VLLM_MAX_MODEL_LEN", "VLLM_ENABLE_MTP")}
    if not args.checker_root:
        raise ValueError("--checker-root is required for conversion scoring")
    for name, expected in CHECKER_HASHES.items():
        checked(args.checker_root / name, expected)
    sys.path.insert(0, str(args.checker_root.resolve()))
    from olmocr.bench.tests import load_single_test
    from olmocr.bench.table_parsing import parse_html_tables, parse_markdown_tables
    import psutil
    import pypdfium2
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict, shutdown_models
    from marker.output import convert_if_not_rgb, text_from_rendered
    from marker.processors.table import TableProcessor
    from marker.schema import BlockTypes

    if not Path(sys.modules["marker.converters.pdf"].__file__).resolve().is_relative_to(repo):
        raise RuntimeError("Converter imported from another checkout")
    record["packages"] = {p: importlib.metadata.version(p) for p in
                          ["marker-pdf", "surya-ocr", "torch", "pytest", "Pillow", "psutil"]}
    record["checker_revision"] = CHECKER_REVISION
    # Render the original page for side-by-side inspection; do not alter it.
    with pypdfium2.PdfDocument(str(source)) as pdf:
        if len(pdf) != 1:
            raise ValueError("This helper accepts one-page PDFs only")
        page = pdf[0]
        bitmap = page.render(scale=2)
        bitmap.to_pil().save(out / "source-page.png")
        bitmap.close()
        page.close()
    stop = threading.Event()
    peaks = {"parent_rss_bytes": 0, "process_tree_rss_sum_bytes": 0}
    process = psutil.Process()

    def sample():
        while not stop.wait(0.1):
            total = 0
            for p in [process, *process.children(recursive=True)]:
                try:
                    rss = p.memory_info().rss
                    total += rss
                    if p.pid == process.pid:
                        peaks["parent_rss_bytes"] = max(peaks["parent_rss_bytes"], rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peaks["process_tree_rss_sum_bytes"] = max(peaks["process_tree_rss_sum_bytes"], total)

    snapshots, calls = [], []
    original_table_call = TableProcessor.__call__

    def table_call(processor, document):
        before = {str(b.id): bool(b.html) for b in document.contained_blocks(processor.block_types)}
        result = original_table_call(processor, document)
        for b in document.contained_blocks(processor.block_types):
            path = "existing_html" if before.get(str(b.id)) else b.text_extraction_method or "unresolved"
            snapshots.append(dict(id=str(b.id), path=path, bbox=b.polygon.bbox,
                                  html=b.html, html_sha256=hashlib.sha256((b.html or "").encode()).hexdigest()))
        return result

    models = None
    started = time.monotonic()
    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        from surya.settings import settings as surya_settings
        check_endpoint(surya_settings.SURYA_INFERENCE_URL)
        if surya_settings.SURYA_INFERENCE_URL:
            record["model_revision_verification"] = "existing loopback endpoint; caller must retain server revision evidence"
        models = create_model_dict()
        record["diagnostics_supported"] = hasattr(TableProcessor, "collect_table_diagnostics")
        record["effective_inference_settings"] = {k: getattr(surya_settings, k, None) for k in (
            "SURYA_MODEL_CHECKPOINT", "VLLM_DOCKER_IMAGE", "VLLM_GPU_MEMORY_UTILIZATION",
            "VLLM_DTYPE", "VLLM_MAX_MODEL_LEN", "VLLM_ENABLE_MTP", "VLLM_MTP_TOKENS",
            "VLLM_GPU_TYPE",
            "SURYA_INFERENCE_STARTUP_TIMEOUT", "SURYA_INFERENCE_TIMEOUT_SECONDS")}
        from surya.inference.backends.vllm import _gpu_settings
        batched_tokens, sequences = _gpu_settings(surya_settings.VLLM_GPU_TYPE)
        extra = (surya_settings.VLLM_EXTRA_ARGS or "").split()
        allowed = {"--revision", "--max-num-batched-tokens", "--max-num-seqs",
                   "--safetensors-load-strategy", "--max-model-len", "--gpu-memory-utilization"}
        recorded_args = {}
        while extra:
            key = extra.pop(0)
            if key == "--enforce-eager":
                recorded_args[key] = True
            elif key in allowed and extra:
                recorded_args[key] = extra.pop(0)
            else:
                raise ValueError("Unrecorded extra inference argument; extend the reviewed allowlist first")
        record["effective_inference_settings"].update(
            max_num_batched_tokens=int(recorded_args.get("--max-num-batched-tokens", batched_tokens)),
            max_num_seqs=int(recorded_args.get("--max-num-seqs", sequences)),
            extra_launch_args=recorded_args,
            authority="local configured launch; existing endpoint requires matching server evidence")
        recognition_type = type(models["recognition_model"])
        original_recognition = recognition_type.__call__

        def recognition_call(predictor, *pos, **kw):
            images = kw.get("images", pos[0] if pos else [])
            calls.append(dict(images=len(images), full_page=kw.get("full_page")))
            return original_recognition(predictor, *pos, **kw)

        with patch.object(TableProcessor, "__call__", table_call), patch.object(recognition_type, "__call__", recognition_call):
            converter = PdfConverter(artifact_dict=models, config=config)
            document = converter.build_document(str(source))
            rendered = converter.resolve_dependencies(converter.renderer)(document)
        text, _, images = text_from_rendered(rendered)
        (out / "output.md").write_text(text, encoding="utf-8")
        write_json(out / "metadata.json", rendered.metadata)
        image_inventory = {}
        for name, image in images.items():
            destination = (out / name).resolve()
            if not destination.is_relative_to(out) or destination.exists():
                raise ValueError("Image reference escapes or overwrites the result directory")
            destination.parent.mkdir(parents=True, exist_ok=True)
            convert_if_not_rgb(image).save(destination)
            image_inventory[name] = digest(destination)
        record["images"] = image_inventory
        final = [dict(id=str(b.id), bbox=b.polygon.bbox, html=b.html,
                      html_sha256=hashlib.sha256((b.html or "").encode()).hexdigest())
                 for b in document.contained_blocks(TableProcessor.block_types)]
        write_json(out / "tables.json", dict(after_table_processor=snapshots, final=final,
                   diagnostics=getattr(document, "table_diagnostics", None)))
        if args.case == "multi":
            checker = runpy.run_path(str(repo / "tests/converters/test_olmocr_bench.py"))["_check"]
            checks = [dict(id=r["id"], result=checker(r, text)) for r in rules]
            record["vendored_checker_sha256"] = digest(repo / "tests/converters/test_olmocr_bench.py")
        else:
            checks = [dict(id=r["id"], result=load_single_test(r).run(text)) for r in rules]
        if args.case == "table":
            tables = parse_markdown_tables(text) + parse_html_tables(text)
            shapes = [[max((r for r, c in t.cell_text), default=-1) + 1,
                       max((c for r, c in t.cell_text), default=-1) + 1] for t in tables]
            record["visual_expectations"] = {
                "source_sha256": TABLE_HASH,
                "basis": "Human-visible source page inspection, separate from official rules",
                "expected_shapes_in_order": [[5, 7], [6, 5]],
                "first_header": ["Variable", "Mean", "JS", "BO", "IBE", "MI", "S.D."],
                "scope": "Dimensions and first header only, not complete cell correctness",
            }
            expected_header = record["visual_expectations"]["first_header"]
            header = [tables[0].cell_text.get((0, c), "").strip() for c in range(7)] if tables else []
            record["supplementary_checks"] = [
                dict(id="public_table_shapes", result=[shapes == [[5, 7], [6, 5]], f"Observed {shapes}"]),
                dict(id="public_first_table_header", result=[header == expected_header, f"Observed {header}"]),
            ]
        if args.case == "synthetic":
            tables = parse_markdown_tables(text) + parse_html_tables(text)
            expected = {(r, c): value for r, row in enumerate(EXPECTED) for c, value in enumerate(row)}
            exact = len(tables) == 1 and {position: value.strip() for position, value in tables[0].cell_text.items()} == expected
            checks = [dict(id="synthetic_exact_cells", result=[exact, "Exactly one table and the exact expected cell map; no extra cells"])]
        record.update(status="converted", checks=checks, output_sha256=digest(out / "output.md"),
                      effective_extract_images=converter.resolve_dependencies(converter.renderer).extract_images)
        if digest(source) != source_hash:
            raise RuntimeError("Source changed during verification")
        if code != {str(p.relative_to(repo)): digest(p) for p in sorted((repo / "marker").rglob("*.py"))}:
            raise RuntimeError("Repository code changed during verification")
    except Exception:
        record.update(status="error", error=traceback.format_exc())
    finally:
        record["seconds_including_startup"] = time.monotonic() - started
        stop.set()
        thread.join()
        record.update(memory=peaks, memory_scope="100ms sampled parent/process-tree RSS sum; shared pages may double-count; excludes Docker/GPU/external servers", recognition_calls=calls)
        if models:
            shutdown_models(models)
        write_json(out / "record.json", record)
    return 0 if record["status"] == "converted" and all(x["result"][0] for x in record["checks"] + record.get("supplementary_checks", [])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
