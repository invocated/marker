import json
from pathlib import Path
import shutil

import pytest

from marker.batch.validation import (
    atomic_json,
    contained,
    file_hash,
    resumable,
    validate_outputs,
)
from marker.batch.runtime import docker_evidence
from marker.scripts.validated_batch import configuration, convert_book, run_batch

pytestmark = pytest.mark.cpu


def artifacts(root):
    root.mkdir(exist_ok=True)
    (root / "document.md").write_bytes(b"A converted document.\n")
    metadata = {
        "page_stats": [{"page_id": 0}],
        "table_of_contents": [],
        "table_diagnostics": [],
    }
    atomic_json(root / "document_meta.json", metadata)
    return {
        "markdown": "document.md",
        "metadata": "document_meta.json",
        "expected_pages": [0],
        "headings": [],
        "tables": [],
        "images": [],
        "markdown_sha256": file_hash(root / "document.md"),
    }


def fake_runtime(request, attempt, probe=False):
    prefix = "probe" if probe else "conversion"
    for stream in ("stdout", "stderr"):
        (attempt / f"{prefix}.{stream}.log").write_text(
            "synthetic process", encoding="utf-8"
        )
    atomic_json(
        attempt / f"{prefix}.process.json", {"exit_code": 0, "timed_out": False}
    )
    identity = {
        "source": request["source"],
        "config": request["config"],
        "runtime": "test",
        "models": "test",
    }
    if probe:
        return {"identity": identity}
    evidence = {
        **artifacts(attempt / "output"),
        "identity": identity,
        "attempt_id": attempt.name,
    }
    atomic_json(attempt / "runtime.json", evidence)
    return evidence


def source(tmp_path, name="Guide.pdf"):
    inputs = tmp_path / "inputs"
    inputs.mkdir(exist_ok=True)
    path = inputs / name
    path.write_bytes(b"synthetic PDF bytes for orchestration only")
    return inputs, path


@pytest.mark.parametrize(
    "name", ["/outside", "../outside", "C:/outside", "\\outside", "a/../../outside"]
)
def test_confined_paths_fail_without_hanging(tmp_path, name):
    with pytest.raises(ValueError):
        contained(tmp_path, name)


def test_valid_artifacts_then_nonempty_truncation(tmp_path):
    evidence = artifacts(tmp_path)
    assert validate_outputs(tmp_path, evidence)["status"] == "pass"
    (tmp_path / "document.md").write_text("Truncated", encoding="utf-8")
    assert validate_outputs(tmp_path, evidence)["status"] == "fail"


@pytest.mark.parametrize(
    "mutation",
    ["partial", "pages", "heading", "extra_table", "missing_image", "reference_image"],
)
def test_incomplete_artifacts_do_not_pass(tmp_path, mutation):
    evidence = artifacts(tmp_path)
    meta = json.loads((tmp_path / "document_meta.json").read_text())
    if mutation == "partial":
        (tmp_path / "document_meta.json").write_text("{")
    elif mutation == "pages":
        meta["page_stats"] = []
    elif mutation == "heading":
        meta["table_of_contents"] = ["malformed"]
        evidence["headings"] = [{"level": 2, "page_id": 0, "title": "Title"}]
    elif mutation == "extra_table":
        meta["table_diagnostics"] = [{"block_id": "table"}]
    elif mutation == "missing_image":
        evidence["images"] = ["missing.png"]
    elif mutation == "reference_image":
        (tmp_path / "document.md").write_text(
            "![alt][picture]\n[picture]: missing.png", encoding="utf-8"
        )
        evidence["markdown_sha256"] = file_hash(tmp_path / "document.md")
    if mutation != "partial":
        atomic_json(tmp_path / "document_meta.json", meta)
    assert validate_outputs(tmp_path, evidence)["status"] != "pass"


def valid_table(root):
    import hashlib

    evidence = artifacts(root)
    html = "<table><tr><td>value</td></tr></table>"
    (root / "document.md").write_bytes(html.encode())
    evidence["markdown_sha256"] = file_hash(root / "document.md")
    html_hash = hashlib.sha256(html.encode()).hexdigest()
    trace = {
        "block_id": "table",
        "html_sha256_after_table_processor": html_hash,
        "source_kind": "digital_text",
        "source_coverage": "accounted",
        "reconstruction_accepted": True,
        "has_html": True,
        "requires_review": False,
        "spans": [{"status": "emitted", "text": "value"}],
    }
    evidence["tables"] = [
        {"block_id": "table", "html_sha256": html_hash, "render_html_sha256": html_hash}
    ]
    meta = json.loads((root / "document_meta.json").read_text())
    meta["table_diagnostics"] = [trace]
    atomic_json(root / "document_meta.json", meta)
    assert validate_outputs(root, evidence)["status"] == "pass"
    return evidence, meta


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("rewrite", "table_changed_after_diagnostics"),
        ("unknown", "table_requires_review"),
        ("empty_spans", "table_requires_review"),
        ("duplicate", "conflicting_table_identity"),
    ],
)
def test_table_evidence_cannot_certify_unknown_or_changed_table(
    tmp_path, mutation, reason
):
    evidence, meta = valid_table(tmp_path)
    trace = meta["table_diagnostics"][0]
    if mutation == "rewrite":
        evidence["tables"][0]["html_sha256"] = "rewritten"
    elif mutation == "unknown":
        trace["source_coverage"] = "unknown"
    elif mutation == "empty_spans":
        trace["spans"] = []
    else:
        meta["table_diagnostics"].append(trace)
    atomic_json(tmp_path / "document_meta.json", meta)
    result = validate_outputs(tmp_path, evidence)
    assert result["status"] != "pass"
    assert reason in {f["reason"] for f in result["findings"]}


@pytest.mark.parametrize("change", ["drop", "duplicate", "code_fence"])
def test_final_table_must_survive_rendering(tmp_path, change):
    evidence, _ = valid_table(tmp_path)
    html = (tmp_path / "document.md").read_text()
    rendered = (
        "Unrelated prose"
        if change == "drop"
        else html + html
        if change == "duplicate"
        else "```html\n" + html + "\n```"
    )
    (tmp_path / "document.md").write_bytes(rendered.encode())
    evidence["markdown_sha256"] = file_hash(tmp_path / "document.md")
    result = validate_outputs(tmp_path, evidence)
    assert result["status"] == "fail"
    assert "rendered_tables_missing_or_changed" in {
        f["reason"] for f in result["findings"]
    }


def test_resume_requires_source_config_inventory_and_logs(tmp_path):
    inputs, pdf = source(tmp_path)
    out = tmp_path / "out"
    first = convert_book(pdf, inputs, out, configuration(), {}, fake_runtime)
    assert first["status"] == "pass"
    second = convert_book(pdf, inputs, out, configuration(), {}, fake_runtime)
    assert second["status"] == "skipped"
    attempt = Path(first["attempt"])
    (attempt / "output/document.md").write_text("Changed")
    assert (
        convert_book(pdf, inputs, out, configuration(), {}, fake_runtime)["status"]
        == "pass"
    )
    assert (
        convert_book(pdf, inputs, out, configuration("fast"), {}, fake_runtime)[
            "status"
        ]
        == "pass"
    )
    pdf.write_bytes(b"changed source")
    assert (
        convert_book(pdf, inputs, out, configuration(), {}, fake_runtime)["status"]
        == "pass"
    )


def test_legacy_outputs_preserved_and_substring_does_not_skip(tmp_path):
    inputs, pdf = source(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    legacy = out / "Guide Revised.md"
    legacy.write_bytes(b"old" * 100)
    assert (
        convert_book(pdf, inputs, out, configuration(), {}, fake_runtime)["status"]
        == "pass"
    )
    assert legacy.read_bytes() == b"old" * 100


def test_copied_record_cannot_certify_another_attempt(tmp_path):
    inputs, pdf = source(tmp_path)
    result = convert_book(
        pdf, inputs, tmp_path / "out", configuration(), {}, fake_runtime
    )
    first = Path(result["attempt"])
    other = first.with_name("different-attempt")
    shutil.copytree(first, other)
    record = json.loads((first / "completion.json").read_text())
    assert resumable(first, record["identity"])
    assert not resumable(other, record["identity"])
    (first / "input.pdf").write_bytes(b"changed")
    assert not resumable(first, record["identity"])


def test_failure_continues_other_books(tmp_path):
    inputs, first = source(tmp_path, "a.pdf")
    _, second = source(tmp_path, "b.pdf")

    def runner(request, attempt, probe=False):
        if request["source"]["relative_path"] == "a.pdf":
            raise RuntimeError("synthetic failure")
        return fake_runtime(request, attempt, probe)

    results = run_batch(inputs, tmp_path / "out", [inputs], configuration(), {}, runner)
    assert [r["status"] for r in results] == ["unknown", "pass"]


def test_source_changes_during_probe_cannot_skip(tmp_path):
    inputs, pdf = source(tmp_path)
    out = tmp_path / "out"
    assert (
        convert_book(pdf, inputs, out, configuration(), {}, fake_runtime)["status"]
        == "pass"
    )

    def runner(request, attempt, probe=False):
        result = fake_runtime(request, attempt, probe)
        if probe:
            pdf.write_bytes(b"changed during probe")
        return result

    assert (
        convert_book(pdf, inputs, out, configuration(), {}, runner)["status"]
        == "unknown"
    )


def test_output_root_cannot_be_discovered_as_source(tmp_path):
    inputs, _ = source(tmp_path)
    with pytest.raises(ValueError):
        run_batch(
            inputs, inputs / "outputs", [inputs], configuration(), {}, fake_runtime
        )


def test_atomic_record_interruption_keeps_old_record(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    atomic_json(path, {"old": True})

    def failed(*args):
        raise OSError("interrupted replacement")

    monkeypatch.setattr("marker.batch.validation.os.replace", failed)
    with pytest.raises(OSError):
        atomic_json(path, {"old": False})
    assert json.loads(path.read_text()) == {"old": True}


@pytest.mark.parametrize("revision", ["main", "a" * 40])
@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "process_revision",
        "tokenizer_equals",
        "remote_code_equals",
        "local_path",
        "local_resolution",
    ],
)
def test_docker_revision_and_process_binding(monkeypatch, revision, mutation):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    args = [
        "--model",
        "/local/model" if mutation == "local_path" else "datalab-to/surya-ocr-2",
        "--revision",
        revision,
    ]
    if mutation == "tokenizer_equals":
        args.append("--tokenizer=other")
    if mutation == "remote_code_equals":
        args.append("--trust-remote-code=true")
    data = {
        "State": {"Running": True, "StartedAt": "time", "Pid": 1},
        "Config": {"Cmd": args},
        "Image": "sha256:" + "b" * 64,
        "Id": "container",
        "NetworkSettings": {
            "Ports": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "1234"}]}
        },
    }

    def response(command, **kwargs):
        if command[1:3] == ["context", "inspect"]:
            return json.dumps(
                [{"Endpoints": {"docker": {"Host": "unix:///docker.sock"}}}]
            )
        if command[1] == "inspect":
            return json.dumps([data])
        if command[1] == "exec":
            return json.dumps([mutation != "local_resolution"])
        process_args = list(args)
        if mutation == "process_revision":
            process_args[3] = "c" * 40
        return "PID COMMAND\n1 python /usr/bin/vllm serve " + " ".join(process_args)

    monkeypatch.setattr("marker.batch.runtime.subprocess.check_output", response)
    if revision == "main" or mutation:
        with pytest.raises(ValueError):
            docker_evidence("container")
    else:
        stable, witness, url = docker_evidence("container")
        assert stable["revision"] == revision
        assert url == "http://127.0.0.1:1234/v1"


def test_record_failure_does_not_stop_next_book(tmp_path, monkeypatch):
    import marker.scripts.validated_batch as worker

    inputs, _ = source(tmp_path, "a.pdf")
    source(tmp_path, "b.pdf")
    original = worker.atomic_json

    def persist(path, value):
        if "a-" in str(path) and Path(path).name == "completion.json":
            raise OSError("synthetic disconnected storage")
        return original(path, value)

    monkeypatch.setattr(worker, "atomic_json", persist)
    results = run_batch(
        inputs, tmp_path / "out", [inputs], configuration(), {}, fake_runtime
    )
    assert [r["status"] for r in results] == ["unknown", "pass"]
    assert results[0]["record_persistence_failed"] is True


def test_independent_simultaneous_attempts_do_not_share_outputs(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    inputs, pdf = source(tmp_path)
    barrier = Barrier(2)

    def runner(request, attempt, probe=False):
        if not probe:
            barrier.wait(timeout=10)
        return fake_runtime(request, attempt, probe)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: convert_book(
                    pdf, inputs, tmp_path / "out", configuration(), {}, runner
                ),
                range(2),
            )
        )
    assert all(r["status"] == "pass" for r in results)
    assert results[0]["attempt"] != results[1]["attempt"]
    assert all((Path(r["attempt"]) / "output/document.md").exists() for r in results)


@pytest.mark.parametrize("field", ["runtime", "models"])
def test_changed_runtime_evidence_invalidates_resume(tmp_path, field):
    inputs, pdf = source(tmp_path)
    out = tmp_path / "out"
    assert (
        convert_book(pdf, inputs, out, configuration(), {}, fake_runtime)["status"]
        == "pass"
    )

    def runner(request, attempt, probe=False):
        value = fake_runtime(request, attempt, probe)
        value["identity"][field] = "changed actual runtime evidence"
        if not probe:
            atomic_json(attempt / "runtime.json", value)
        return value

    assert (
        convert_book(pdf, inputs, out, configuration(), {}, runner)["status"] == "pass"
    )


def test_interrupted_artifacts_without_record_never_skip(tmp_path):
    inputs, pdf = source(tmp_path)
    result = convert_book(
        pdf, inputs, tmp_path / "out", configuration(), {}, fake_runtime
    )
    (Path(result["attempt"]) / "completion.json").unlink()
    assert (
        convert_book(pdf, inputs, tmp_path / "out", configuration(), {}, fake_runtime)[
            "status"
        ]
        == "pass"
    )


def test_alternate_root_requires_validated_records(tmp_path):
    inputs, pdf = source(tmp_path)
    previous = tmp_path / "previous"
    result = convert_book(pdf, inputs, previous, configuration(), {}, fake_runtime)
    current = convert_book(
        pdf, inputs, tmp_path / "new", configuration(), {}, fake_runtime, [previous]
    )
    assert current["status"] == "skipped"
    assert (Path(result["attempt"]) / "output/document.md").exists()


@pytest.mark.parametrize("timeout", [False, True])
def test_runtime_process_retains_and_redacts_logs(tmp_path, monkeypatch, timeout):
    import subprocess
    from types import SimpleNamespace
    from marker.scripts.validated_batch import run_runtime, RuntimeFailure

    monkeypatch.setenv("TEST_API_KEY", "credential-for-test")

    def run(command, **kwargs):
        if timeout:
            raise subprocess.TimeoutExpired(
                command, 1, output=b"credential-for-test", stderr=b"partial failure"
            )
        atomic_json(Path(command[4]), {"ok": True})
        return SimpleNamespace(
            returncode=0, stdout="credential-for-test", stderr="successful warning"
        )

    monkeypatch.setattr("marker.scripts.validated_batch.subprocess.run", run)
    if timeout:
        with pytest.raises(RuntimeFailure):
            run_runtime({}, tmp_path)
    else:
        assert run_runtime({}, tmp_path) == {"ok": True}
    assert "credential-for-test" not in (tmp_path / "conversion.stdout.log").read_text()
    stderr = (tmp_path / "conversion.stderr.log").read_text()
    assert ("partial failure" if timeout else "successful warning") in stderr
    assert (
        json.loads((tmp_path / "conversion.process.json").read_text())["timed_out"]
        == timeout
    )


def test_html_in_code_fence_does_not_count_as_rendered_table(tmp_path):
    evidence = artifacts(tmp_path)
    (tmp_path / "document.md").write_text(
        "```html\n<table><tr><td>Literal</td></tr></table>\n```", encoding="utf-8"
    )
    evidence["markdown_sha256"] = file_hash(tmp_path / "document.md")
    assert validate_outputs(tmp_path, evidence)["status"] == "pass"


@pytest.mark.parametrize("mode,needed", [("balanced", True), ("fast", False)])
def test_probe_model_requirement_and_inherited_checkpoints(
    tmp_path, monkeypatch, mode, needed
):
    import os
    import marker.batch.runtime as runtime
    from surya.settings import settings

    for name in (
        "FAST_LAYOUT_MODEL_CHECKPOINT",
        "OCR_ERROR_MODEL_CHECKPOINT",
        "SURYA_INFERENCE_URL",
        "SURYA_INFERENCE_AUTOSTART",
        "SURYA_MODEL_CHECKPOINT",
    ):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setenv("FAST_LAYOUT_MODEL_CHECKPOINT", "old-layout")
    monkeypatch.setenv("OCR_ERROR_MODEL_CHECKPOINT", "old-ocr")
    monkeypatch.setattr(
        runtime, "resolve_checkpoints", lambda profile: ("layout", "ocr")
    )
    monkeypatch.setattr(
        runtime,
        "checkpoint_snapshot",
        lambda source, cache: (str(cache / source), source),
    )
    calls = []

    def docker(container):
        calls.append(container)
        return {"served_model": "verified"}, {"pid": 1}, "http://127.0.0.1:1234/v1"

    monkeypatch.setattr(runtime, "docker_evidence", docker)
    result = runtime.probe(
        {
            "source": {},
            "config": configuration(mode=mode, disable_ocr=True),
            "profile": {"docker_container": "selected"},
            "model_cache": str(tmp_path),
        }
    )
    assert bool(calls) is needed
    assert ("vlm" in result["identity"]["models"]) is needed
    for name, value in (
        ("FAST_LAYOUT_MODEL_CHECKPOINT", "layout"),
        ("OCR_ERROR_MODEL_CHECKPOINT", "ocr"),
    ):
        assert os.environ[name] == result[value + "_path"]
        assert getattr(settings, name) == result[value + "_path"]
    alternate = runtime.probe(
        {
            "source": {},
            "config": configuration(mode=mode, disable_ocr=True),
            "profile": {"docker_container": "selected"},
            "model_cache": str(tmp_path / "alternate"),
        }
    )
    assert alternate["identity"] == result["identity"]
    assert alternate["layout_path"] != result["layout_path"]


def test_actual_source_digest_changes_for_temp_package(tmp_path):
    from marker.batch.runtime import tree_identity

    source = tmp_path / "module.py"
    source.write_text("value = 1\n")
    first = tree_identity(tmp_path)
    source.write_text("value = 2\n")
    assert tree_identity(tmp_path) != first


def test_directory_discovery_failure_continues_other_targets(tmp_path, monkeypatch):
    root = tmp_path / "sources"
    root.mkdir()
    bad = root / "inaccessible"
    bad.mkdir()
    good = root / "good.pdf"
    good.write_bytes(b"pdf")
    original = Path.rglob

    def scan(path, pattern):
        if path == bad:
            raise PermissionError("denied")
        return original(path, pattern)

    monkeypatch.setattr(Path, "rglob", scan)
    monkeypatch.setattr(
        "marker.scripts.validated_batch.convert_book",
        lambda *args: {"status": "pass", "source": "good.pdf"},
    )
    results = run_batch(root, tmp_path / "out", [bad, good], configuration(), {})
    assert [item["status"] for item in results] == ["unknown", "pass"]


@pytest.mark.parametrize("wrong_parent", [False, True, "argv"])
def test_windows_lightweight_redirector_requires_venv_parent(
    tmp_path, monkeypatch, wrong_parent
):
    import types
    import psutil
    import marker.batch.runtime as runtime

    executable = str(tmp_path / "venv-python.exe")
    base = str(tmp_path / "base-python.exe")
    args = [executable, "-m", "server.module", "--checkpoint", "immutable-checkpoint"]
    parent = types.SimpleNamespace(
        exe=lambda: base if wrong_parent is True else executable,
        cmdline=lambda: ["wrong"] if wrong_parent == "argv" else args,
        pid=2,
        create_time=lambda: 9,
    )
    process = types.SimpleNamespace(
        exe=lambda: base,
        cmdline=lambda: args,
        parent=lambda: parent,
        create_time=lambda: 10,
    )
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.sys, "executable", executable)
    monkeypatch.setattr(runtime.sys, "_base_executable", base)
    monkeypatch.setattr(
        psutil,
        "net_connections",
        lambda **kwargs: [
            types.SimpleNamespace(
                pid=1, status="LISTEN", laddr=types.SimpleNamespace(port=1234)
            )
        ],
    )
    monkeypatch.setattr(psutil, "Process", lambda pid: process)
    client = types.SimpleNamespace(
        _base_url="http://127.0.0.1:1234",
        config=types.SimpleNamespace(
            server_module="server.module", model_name="immutable-checkpoint"
        ),
    )
    predictor = types.SimpleNamespace(_client=types.SimpleNamespace(_client=client))
    if wrong_parent:
        with pytest.raises(ValueError, match="Cannot bind"):
            runtime.lightweight_witness(predictor)
    else:
        assert runtime.lightweight_witness(predictor) == {
            "pid": 1,
            "started": 10,
            "redirector": {"pid": 2, "started": 9},
        }
