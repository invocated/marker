"""Sequential book conversion with validated attempt records."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from marker.batch.validation import (
    VERSION,
    atomic_json,
    digest,
    file_hash,
    resumable,
    validate_outputs,
)


def configuration(mode="balanced", pages=None, disable_ocr=False):
    return {
        "mode": mode,
        "page_range": pages,
        "disable_ocr": disable_ocr,
        "output_format": "markdown",
        "html_tables_in_markdown": True,
        "use_llm": False,
        "collect_table_diagnostics": True,
        "pdftext_workers": 1,
    }


def redact(text):
    for name, value in os.environ.items():
        if (
            any(word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
            and len(value) >= 4
        ):
            text = text.replace(value, "[REDACTED]")
    return re.sub(
        r"(?i)(api[_-]?key|password|token|secret)(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[REDACTED]",
        text,
    )


class RuntimeFailure(RuntimeError):
    pass


def run_runtime(request, attempt, probe=False):
    request_path = attempt / "request.json"
    atomic_json(request_path, request)
    result = attempt / ("probe.json" if probe else "runtime.json")
    command = [
        sys.executable,
        "-m",
        "marker.batch.runtime",
        str(request_path),
        str(result),
    ]
    if probe:
        command.append("--probe")
    name = "probe" if probe else "conversion"
    try:
        run = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        code, stdout, stderr = run.returncode, run.stdout, run.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        code = -1
        timed_out = True
        stdout = (
            exc.stdout.decode(errors="replace")
            if isinstance(exc.stdout, bytes)
            else exc.stdout or ""
        )
        stderr = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else exc.stderr or ""
        )
        stderr += "\nConversion timed out.\n"
    except OSError as exc:
        code, stdout, stderr, timed_out = -2, "", str(exc), False
    atomic_json(
        attempt / (name + ".process.json"), {"exit_code": code, "timed_out": timed_out}
    )
    (attempt / (name + ".stdout.log")).write_text(redact(stdout), encoding="utf-8")
    (attempt / (name + ".stderr.log")).write_text(redact(stderr), encoding="utf-8")
    if code != 0:
        raise RuntimeFailure("Runtime process failed; inspect retained diagnostics")
    return json.loads(result.read_text(encoding="utf-8"))


def convert_book(
    source,
    source_root,
    output_root,
    config,
    profile,
    runner=run_runtime,
    alternate_roots=(),
):
    source, source_root, output_root = (
        Path(source).resolve(),
        Path(source_root).resolve(),
        Path(output_root).resolve(),
    )
    if not source.is_relative_to(source_root) or source.suffix.lower() != ".pdf":
        raise ValueError("Input must be a PDF inside the configured source root")
    relative = source.relative_to(source_root)
    parent = (
        output_root
        / relative.parent
        / ".marker-attempts"
        / (relative.stem + "-" + digest(relative.as_posix())[:12])
    )
    if not parent.resolve().is_relative_to(output_root):
        raise ValueError("Attempt directory escapes output root")
    attempt = parent / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {
        "source": relative.as_posix(),
        "status": "unknown",
        "attempt": str(attempt),
    }
    try:
        source_identity = {
            "root": digest(os.path.normcase(str(source_root))),
            "relative_path": relative.as_posix(),
            "sha256": file_hash(source),
        }
        atomic_json(
            attempt / "started.json",
            {"attempt_id": attempt.name, "source": source_identity},
        )
        snapshot = attempt / "input.pdf"
        with open(source, "rb") as incoming, open(snapshot, "xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if file_hash(snapshot) != source_identity["sha256"]:
            raise ValueError("Source changed during snapshot")
        request = {
            "attempt_id": attempt.name,
            "source": source_identity,
            "snapshot": str(snapshot),
            "output": str(attempt / "output"),
            "model_cache": str(output_root / ".marker-models"),
            "config": config,
            "profile": profile,
        }
        current = runner(request, attempt, probe=True)
        identity = current["identity"]
        search_parents = [parent]
        for alternate in alternate_roots:
            alternate = Path(alternate).resolve()
            candidate = alternate / relative.parent / ".marker-attempts" / parent.name
            if candidate.resolve().is_relative_to(alternate) and candidate.is_dir():
                search_parents.append(candidate)
        previous_attempts = [p for folder in search_parents for p in folder.iterdir()]
        for previous in sorted(previous_attempts):
            if (
                previous != attempt
                and previous.is_dir()
                and not previous.is_symlink()
                and resumable(previous, identity)
            ):
                if file_hash(source) != source_identity["sha256"]:
                    raise ValueError("Source changed before resume")
                atomic_json(
                    attempt / "completion.json",
                    {
                        "version": VERSION,
                        "attempt_id": attempt.name,
                        "status": "skipped",
                        "validated_attempt": str(previous.resolve()),
                        "identity": identity,
                    },
                )
                return {
                    **result,
                    "status": "skipped",
                    "validated_attempt": str(previous.resolve()),
                    "output": str(previous.resolve() / "output"),
                }
        evidence = runner(request, attempt)
        checked = validate_outputs(attempt / "output", evidence)
        if (
            evidence.get("identity") != identity
            or evidence.get("attempt_id") != attempt.name
        ):
            checked["status"] = "unknown"
            checked["findings"].append(
                {"status": "unknown", "reason": "runtime_identity_changed"}
            )
        if file_hash(source) != source_identity["sha256"]:
            checked["status"] = "unknown"
            checked["findings"].append(
                {"status": "unknown", "reason": "source_changed"}
            )
        logs = {
            p.name: file_hash(p)
            for pattern in ("*.log", "*.process.json")
            for p in attempt.glob(pattern)
        }
        if set(logs) != {
            "probe.stdout.log",
            "probe.stderr.log",
            "conversion.stdout.log",
            "conversion.stderr.log",
            "probe.process.json",
            "conversion.process.json",
        }:
            checked["status"] = "unknown"
            checked["findings"].append(
                {"status": "unknown", "reason": "missing_process_diagnostics"}
            )
        record = {
            "version": VERSION,
            "attempt_id": attempt.name,
            "identity": identity,
            **checked,
            "evidence_sha256": file_hash(attempt / "runtime.json"),
            "logs": logs,
        }
        atomic_json(attempt / "completion.json", record)
        return {
            **result,
            "status": checked["status"],
            "findings": checked["findings"],
            "output": str(attempt / "output"),
        }
    except Exception as exc:
        result["status"] = "fail" if isinstance(exc, RuntimeFailure) else "unknown"
        result["reason"] = type(exc).__name__ + ": " + redact(str(exc))
        try:
            atomic_json(
                attempt / "completion.json",
                {
                    "version": VERSION,
                    "attempt_id": attempt.name,
                    "status": result["status"],
                    "reason": result["reason"],
                },
            )
        except OSError:
            result["record_persistence_failed"] = True
        return result


def run_batch(
    source_root,
    output_root,
    targets,
    config,
    profile,
    runner=run_runtime,
    alternate_roots=(),
):
    sources = set()
    results = []
    root = Path(source_root).resolve()
    if Path(output_root).resolve().is_relative_to(root):
        raise ValueError("Output root must be outside source root")
    for target in targets:
        target = Path(target).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Target outside source root")
        try:
            if target.is_dir():
                sources.update(
                    p
                    for p in target.rglob("*")
                    if p.is_file() and p.suffix.lower() == ".pdf"
                )
            else:
                sources.add(target)
        except OSError as exc:
            results.append(
                {
                    "source": target.name,
                    "status": "unknown",
                    "reason": type(exc).__name__,
                }
            )
    for source in sorted(sources):
        try:
            result = convert_book(
                source, root, output_root, config, profile, runner, alternate_roots
            )
        except Exception as exc:
            result = {
                "source": source.name,
                "status": "unknown",
                "reason": type(exc).__name__,
            }
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--mode", choices=["balanced", "fast"], default="balanced")
    parser.add_argument("--page-range")
    parser.add_argument("--disable-ocr", action="store_true")
    parser.add_argument("--profile", help="Local model profile JSON")
    parser.add_argument("--alternate-output-root", action="append", default=[])
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()
    pages = None
    if args.page_range:
        from marker.util import parse_range_str

        pages = parse_range_str(args.page_range)
    profile = (
        json.loads(Path(args.profile).read_text(encoding="utf-8"))
        if args.profile
        else {}
    )
    results = run_batch(
        args.source_root,
        args.output_root,
        args.targets,
        configuration(args.mode, pages, args.disable_ocr),
        profile,
        alternate_roots=args.alternate_output_root,
    )
    print(json.dumps(results, indent=2))
    raise SystemExit(
        0 if results and all(r["status"] in ("pass", "skipped") for r in results) else 1
    )


if __name__ == "__main__":
    main()
