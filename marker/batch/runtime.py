"""Conversion subprocess with local runtime and model evidence."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import uuid

from marker.batch.validation import atomic_json, digest, file_hash


def tree_identity(root):
    root = Path(root)
    return digest(
        {
            p.relative_to(root).as_posix(): file_hash(p)
            for p in sorted(root.rglob("*.py"))
            if p.is_file()
        }
    )


def checkpoint_snapshot(source, cache):
    source, cache = Path(source).resolve(), Path(cache).resolve()
    files = {
        p.relative_to(source).as_posix(): file_hash(p)
        for p in sorted(source.rglob("*"))
        if p.is_file()
    }
    if not files or not (source / "config.json").is_file():
        raise ValueError("Local checkpoint is unavailable")
    key = digest(files)
    target = cache / key
    if not target.exists():
        temp = cache / ("pending-" + uuid.uuid4().hex)
        temp.mkdir(parents=True)
        for name in files:
            destination = temp / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
        try:
            temp.rename(target)
        except OSError:
            if not target.is_dir():
                raise
    actual = {
        p.relative_to(target).as_posix(): file_hash(p)
        for p in sorted(target.rglob("*"))
        if p.is_file()
    }
    if actual != files or any(p.is_symlink() for p in target.rglob("*")):
        raise ValueError("Checkpoint snapshot changed")
    return str(target), key


def option(argv, key):
    values = [argv[i + 1] for i, v in enumerate(argv[:-1]) if v == key]
    values += [v.split("=", 1)[1] for v in argv if v.startswith(key + "=")]
    if len(values) != 1:
        raise ValueError("Serving option missing or duplicated: " + key)
    return values[0]


def docker_evidence(container):
    def run(*args):
        return subprocess.check_output(["docker", *args], text=True, timeout=20)

    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise ValueError("Docker environment override is not supported")
    context = json.loads(run("context", "inspect"))[0]
    host = context["Endpoints"]["docker"]["Host"]
    if not host.startswith(("unix://", "npipe://")):
        raise ValueError("Docker daemon is not local")
    data = json.loads(run("inspect", container))[0]
    if not data["State"]["Running"]:
        raise ValueError("Inference container is not running")
    args = data["Config"].get("Cmd") or []
    model, revision = option(args, "--model"), option(args, "--revision")
    if model != "datalab-to/surya-ocr-2":
        raise ValueError("Only the documented Hugging Face Surya model is supported")
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ValueError("Inference revision is mutable")
    serving = run("top", container, "-eo", "pid,args")
    matched = []
    matched_pids = []
    for line in serving.splitlines()[1:]:
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        argv = shlex.split(fields[1])
        if not any(
            Path(v).name == "vllm" or v.startswith("vllm.entrypoints.") for v in argv
        ):
            continue
        try:
            if (
                option(argv, "--model") == model
                and option(argv, "--revision") == revision
            ):
                matched.append(argv)
                matched_pids.append(int(fields[0]))
        except ValueError:
            continue
    if len(matched) != 1:
        raise ValueError("Cannot bind exact revision to one serving process")
    for flag in ("--tokenizer-revision", "--code-revision"):
        if any(v == flag or v.startswith(flag + "=") for v in args):
            value = option(args, flag)
            if (
                not re.fullmatch(r"[0-9a-f]{40,64}", value)
                or option(matched[0], flag) != value
            ):
                raise ValueError("Mutable tokenizer or code revision")
    if any(
        v == flag or v.startswith(flag + "=")
        for flag in ("--tokenizer", "--trust-remote-code")
        for v in args + matched[0]
    ):
        raise ValueError("Custom tokenizer or remote model code is unsupported")
    expected_process_args = shlex.split(" ".join(args))
    actual_args = matched[0]
    if (
        len(actual_args) < len(expected_process_args)
        or actual_args[-len(expected_process_args) :] != expected_process_args
    ):
        raise ValueError("Serving process arguments differ from container command")
    resolution_check = """
import json, os, sys
model, revision = sys.argv[1:]
found = []
for name in os.listdir('/proc'):
    if not name.isdigit():
        continue
    try:
        args = open('/proc/' + name + '/cmdline', 'rb').read().decode().split('\\0')
        if '--model' not in args or '--revision' not in args:
            continue
        if args[args.index('--model') + 1] != model or args[args.index('--revision') + 1] != revision:
            continue
        if not any(os.path.basename(v) == 'vllm' or v.startswith('vllm.entrypoints.') for v in args):
            continue
        cwd = os.readlink('/proc/' + name + '/cwd')
        found.append(not os.path.exists(os.path.join(cwd, model)))
    except (OSError, ValueError, IndexError):
        continue
print(json.dumps(found))
"""
    resolution = json.loads(
        run("exec", container, "python3", "-c", resolution_check, model, revision)
    )
    if resolution != [True]:
        raise ValueError(
            "Cannot verify Hugging Face model resolution in serving process"
        )
    ports = data["NetworkSettings"]["Ports"].get("8000/tcp") or []
    port_numbers = {
        p["HostPort"] for p in ports if p["HostIp"] in ("127.0.0.1", "0.0.0.0", "::")
    }
    if len(port_numbers) != 1:
        raise ValueError("Ambiguous serving port")
    port = next(iter(port_numbers))
    if not port.isdigit():
        raise ValueError("Invalid serving port")
    served = (
        option(args, "--served-model-name") if "--served-model-name" in args else model
    )
    stable = {
        "image": data["Image"],
        "model": model,
        "served_model": served,
        "revision": revision,
        "arguments_sha256": digest(args),
        "serving_arguments_sha256": digest(matched[0]),
        "environment_sha256": digest(data["Config"].get("Env") or []),
        "mounts_sha256": digest(data.get("Mounts") or []),
    }
    if not stable["image"].startswith("sha256:"):
        raise ValueError("Missing image identity")
    witness = {
        "container": data["Id"],
        "started": data["State"]["StartedAt"],
        "pid": data["State"]["Pid"],
        "serving_pid": matched_pids[0],
    }
    return stable, witness, "http://127.0.0.1:" + port + "/v1"


def resolve_checkpoints(profile):
    from surya.settings import settings
    from surya.common.s3 import S3DownloaderMixin
    from huggingface_hub import snapshot_download

    layout = profile.get("fast_layout_checkpoint")
    if not layout:
        name = settings.FAST_LAYOUT_MODEL_CHECKPOINT
        layout = (
            snapshot_download(name.removeprefix("hf://"), local_files_only=True)
            if name.startswith("hf://")
            else name
        )
    ocr = profile.get("ocr_error_checkpoint")
    if not ocr:
        name = settings.OCR_ERROR_MODEL_CHECKPOINT
        ocr = (
            S3DownloaderMixin.get_local_path(name) if name.startswith("s3://") else name
        )
    return layout, ocr


def probe(request):
    import marker.converters.pdf as converter_module
    import surya

    root = Path(converter_module.__file__).resolve().parents[1]
    try:
        revision = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
        ).strip()
    except (OSError, subprocess.SubprocessError):
        revision = None
    identity = {
        "source": request["source"],
        "config": request["config"],
        "validation_version": 1,
        "runtime": {
            "marker_code": tree_identity(root),
            "surya_code": tree_identity(Path(surya.__file__).parent),
            "git_revision": revision,
            "python": sys.version,
            "dependencies": sorted(
                (d.metadata.get("Name", ""), d.version)
                for d in importlib.metadata.distributions()
            ),
        },
    }
    profile = request["profile"]
    if set(profile) - {
        "docker_container",
        "fast_layout_checkpoint",
        "ocr_error_checkpoint",
    }:
        raise ValueError("Unsupported model profile option")
    layout, ocr = resolve_checkpoints(profile)
    runtime_cache = Path(request["model_cache"]) / digest(identity["runtime"])
    layout_path, layout_hash = checkpoint_snapshot(layout, runtime_cache)
    ocr_path, ocr_hash = checkpoint_snapshot(ocr, runtime_cache)
    models = {"fast_layout": layout_hash, "ocr_error": ocr_hash}
    witness, url = None, None
    if request["config"]["mode"] == "balanced" or not request["config"]["disable_ocr"]:
        container = profile.get("docker_container")
        if not container:
            names = subprocess.check_output(
                ["docker", "ps", "--filter", "name=surya-vllm", "--format", "{{.ID}}"],
                text=True,
                timeout=20,
            ).split()
            if len(names) != 1:
                raise ValueError("Select one verifiable local inference container")
            container = names[0]
        models["vlm"], witness, url = docker_evidence(container)
    from marker.settings import settings as marker_settings
    from surya.settings import settings as surya_settings

    surya_settings.FAST_LAYOUT_MODEL_CHECKPOINT = layout_path
    surya_settings.OCR_ERROR_MODEL_CHECKPOINT = ocr_path
    os.environ["FAST_LAYOUT_MODEL_CHECKPOINT"] = layout_path
    os.environ["OCR_ERROR_MODEL_CHECKPOINT"] = ocr_path
    surya_settings.SURYA_INFERENCE_URL = url
    surya_settings.SURYA_INFERENCE_AUTOSTART = False
    if "vlm" in models:
        surya_settings.SURYA_MODEL_CHECKPOINT = models["vlm"]["served_model"]

    def settings_values(settings):
        values = {}
        scalars = {}
        for name in set(type(settings).model_fields) | set(
            type(settings).model_computed_fields
        ):
            if name.endswith(
                (
                    "API_KEY",
                    "PASSWORD",
                    "SECRET",
                    "ACCESS_TOKEN",
                    "AUTH_TOKEN",
                    "HF_TOKEN",
                )
            ):
                continue
            if name in {
                "SURYA_INFERENCE_URL",
                "FAST_LAYOUT_MODEL_CHECKPOINT",
                "OCR_ERROR_MODEL_CHECKPOINT",
            }:
                continue
            value = getattr(settings, name)
            if not isinstance(value, (str, int, float, bool, list, dict, type(None))):
                value = str(value)
            values[name] = digest(value)
            if isinstance(value, (bool, int, float, type(None))):
                scalars[name] = value
        return {"fingerprints": values, "scalars": scalars}

    identity["effective_settings"] = {
        "marker": settings_values(marker_settings),
        "surya": settings_values(surya_settings),
    }
    identity["models"] = models
    return {
        "identity": identity,
        "layout_path": layout_path,
        "ocr_path": ocr_path,
        "container": witness,
        "url": url,
    }


def lightweight_witness(predictor):
    import psutil
    from urllib.parse import urlsplit

    client = predictor._client._client
    if client._base_url is None:
        return None
    url = urlsplit(client._base_url)
    if url.hostname != "127.0.0.1":
        raise ValueError("Lightweight server is not loopback")
    pids = {
        c.pid
        for c in psutil.net_connections(kind="tcp")
        if c.status == "LISTEN" and c.laddr.port == url.port and c.pid
    }
    matches = []
    for pid in pids:
        process = psutil.Process(pid)
        args = process.cmdline()
        redirector = None
        executable_matches = (
            Path(process.exe()).resolve() == Path(sys.executable).resolve()
        )
        if not executable_matches and sys.platform == "win32" and args:
            parent = process.parent()
            executable_matches = (
                Path(process.exe()).resolve() == Path(sys._base_executable).resolve()
                and Path(args[0]).resolve() == Path(sys.executable).resolve()
                and parent is not None
                and Path(parent.exe()).resolve() == Path(sys.executable).resolve()
                and parent.cmdline() == args
            )
            if executable_matches:
                redirector = {"pid": parent.pid, "started": parent.create_time()}
        if (
            executable_matches
            and client.config.server_module in args
            and option(args, "--checkpoint") == client.config.model_name
        ):
            witness = {"pid": pid, "started": process.create_time()}
            if redirector is not None:
                witness["redirector"] = redirector
            matches.append(witness)
    if len(matches) != 1:
        raise ValueError("Cannot bind local checkpoint to serving process")
    return matches[0]


def convert(request, before):
    from marker.converters.pdf import PdfConverter
    from marker.output import save_output
    from marker.schema import BlockTypes
    from surya.settings import settings as surya_settings
    from surya.inference import SuryaInferenceManager
    from surya.layout import LayoutPredictor
    from surya.recognition import RecognitionPredictor
    from surya.fast_layout import FastLayoutPredictor
    from surya.ocr_error import OCRErrorPredictor
    from bs4 import BeautifulSoup
    import pypdfium2

    config = request["config"]
    if config.get("use_llm") is not False or config.get("output_format") != "markdown":
        raise ValueError("Unsupported conversion configuration")
    if config["mode"] not in ("fast", "balanced"):
        raise ValueError("Explicit mode required")
    surya_settings.SURYA_INFERENCE_URL = before["url"]
    surya_settings.SURYA_INFERENCE_AUTOSTART = False
    manager = SuryaInferenceManager(method="vllm")
    layout = FastLayoutPredictor(checkpoint=before["layout_path"], use_order=False)
    ocr = OCRErrorPredictor(checkpoint=before["ocr_path"])
    for predictor in (layout, ocr):
        client = predictor._client._client
        client.config.external_url = None
        client.config.host = "127.0.0.1"
        client.config.port = None
        client.config.autostart = True
        namespace = digest(
            {
                "runtime": before["identity"]["runtime"],
                "checkpoint": client.config.model_name,
            }
        )[:24]
        client.config.backend = "marker_" + client.config.backend + "_" + namespace
    models = {
        "inference_manager": manager,
        "layout_model": LayoutPredictor(manager),
        "recognition_model": RecognitionPredictor(manager),
        "fast_layout_model": layout,
        "ocr_error_model": ocr,
    }
    used_clients = [ocr] + ([layout] if config["mode"] == "fast" else [])
    for predictor in used_clients:
        predictor._client._client._ensure_started()
    light_before = [lightweight_witness(p) for p in used_clients]
    converter = PdfConverter(artifact_dict=models, config=config)
    snapshot = Path(request["snapshot"])
    if file_hash(snapshot) != request["source"]["sha256"]:
        raise ValueError("Source snapshot changed")
    with pypdfium2.PdfDocument(str(snapshot)) as pdf:
        expected = (
            config["page_range"]
            if config["page_range"] is not None
            else list(range(len(pdf)))
        )
        if not expected or any(
            type(p) is not int or p < 0 or p >= len(pdf) for p in expected
        ):
            raise ValueError("Invalid requested pages")
    document = converter.build_document(str(snapshot))
    tables = []
    headings = []
    for page in document.pages:
        for block in page.contained_blocks(
            document, (BlockTypes.Table, BlockTypes.Form, BlockTypes.TableOfContents)
        ):
            if not block.ignore_for_output:
                table_tag = BeautifulSoup(block.html or "", "html.parser").find("table")
                tables.append(
                    {
                        "block_id": str(block.id),
                        "html_sha256": hashlib.sha256(
                            (block.html or "").encode()
                        ).hexdigest(),
                        "render_html_sha256": hashlib.sha256(
                            str(table_tag).encode()
                        ).hexdigest()
                        if table_tag
                        else None,
                    }
                )
        for block in page.contained_blocks(document, (BlockTypes.SectionHeader,)):
            html = block.render(document).html
            soup = BeautifulSoup(html, "html.parser")
            tag = soup.find(re.compile(r"^h[1-6]$"))
            title = block.raw_text(document).strip()
            headings.append(
                {
                    "page_id": page.page_id,
                    "title": title,
                    "level": int(tag.name[1]) if tag else None,
                }
            )
    renderer = converter.resolve_dependencies(converter.renderer)
    rendered = renderer(document)
    output = Path(request["output"])
    output.mkdir(exist_ok=False)
    from marker.settings import settings as marker_settings

    expected_markdown = rendered.markdown.replace("\n", os.linesep).encode(
        marker_settings.OUTPUT_ENCODING, errors="replace"
    )
    expected_markdown_hash = hashlib.sha256(expected_markdown).hexdigest()
    save_output(rendered, str(output), "document")
    light_after = [lightweight_witness(p) for p in used_clients]
    if light_before != light_after:
        raise ValueError("Lightweight serving process changed")
    after = probe(request)
    if (
        before["identity"] != after["identity"]
        or before["container"] != after["container"]
    ):
        raise ValueError("Runtime or serving identity changed")
    if file_hash(snapshot) != request["source"]["sha256"]:
        raise ValueError("Source snapshot changed after conversion")
    return {
        "attempt_id": request["attempt_id"],
        "identity": before["identity"],
        "markdown": "document.md",
        "metadata": "document_meta.json",
        "expected_pages": expected,
        "tables": tables,
        "headings": headings,
        "markdown_sha256": expected_markdown_hash,
        "images": list(rendered.images),
        "model_witness": before["container"],
        "lightweight_witness": light_after,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("request")
    parser.add_argument("result")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    before = probe(request)
    evidence = before if args.probe else convert(request, before)
    atomic_json(args.result, evidence)


if __name__ == "__main__":
    main()
