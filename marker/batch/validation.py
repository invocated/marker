"""Identity and output checks for the external batch worker."""

import hashlib
import json
import os
from pathlib import Path
import stat
import uuid
from urllib.parse import unquote, urlsplit

VERSION = 1


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with open(temp, "x", encoding="utf-8") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def reject_link(path):
    path = Path(path)
    if path.is_symlink() or (
        path.exists()
        and getattr(path.lstat(), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    ):
        raise ValueError("Artifact link or junction is not allowed")


def contained(root, relative):
    reject_link(root)
    root = Path(root).resolve()
    part = Path(relative)
    if (
        part.anchor
        or part.root
        or part.drive
        or "\\" in str(relative)
        or ".." in part.parts
        or ":" in str(relative)
    ):
        raise ValueError("Artifact path is not relative")
    candidate = root / part
    if not candidate.is_relative_to(root):
        raise ValueError("Artifact escapes output directory")
    current = candidate
    while current != root:
        if current.parent == current:
            raise ValueError("Artifact parent escaped root")
        reject_link(current)
        current = current.parent
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("Artifact escapes output directory")
    return candidate


def inventory(root):
    root = Path(root)
    reject_link(root)
    result = {}
    for path in sorted(root.rglob("*")):
        reject_link(path)
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            result[relative] = file_hash(contained(root, relative))
    return result


def validate_outputs(root, evidence):
    root = Path(root)
    findings = []

    def note(status, reason):
        findings.append({"status": status, "reason": reason})

    try:
        artifacts = inventory(root)
        markdown = contained(root, evidence["markdown"]).read_text(encoding="utf-8")
        metadata = json.loads(
            contained(root, evidence["metadata"]).read_text(encoding="utf-8")
        )
        if evidence.get("markdown_sha256") != file_hash(
            contained(root, evidence["markdown"])
        ):
            note("fail", "rendered_output_changed")
        if not markdown.strip():
            note("fail", "empty_output")
        actual = [p["page_id"] for p in metadata["page_stats"]]
        if actual != evidence["expected_pages"] or len(set(actual)) != len(actual):
            note("fail", "page_coverage")
        if not isinstance(metadata.get("table_of_contents"), list):
            note("unknown", "missing_heading_metadata")
        else:
            expected_headings = evidence["headings"]
            observed = metadata["table_of_contents"]
            if len(observed) != len(expected_headings):
                note("fail", "heading_count")
            for item, final in zip(observed, expected_headings):
                level = item.get("heading_level")
                if (
                    type(level) is not int
                    or not 1 <= level <= 6
                    or level != final["level"]
                ):
                    note("fail", "heading_level")
                if (
                    item.get("page_id") != final["page_id"]
                    or item.get("title") != final["title"]
                ):
                    note("fail", "heading_identity")
        traces = metadata.get("table_diagnostics")
        if not isinstance(traces, list):
            traces = []
            note("unknown", "missing_table_diagnostics")
        ids = [t.get("block_id") for t in traces]
        finals = evidence["tables"]
        final_ids = [t["block_id"] for t in finals]
        if len(set(ids)) != len(ids) or len(set(final_ids)) != len(final_ids):
            note("fail", "conflicting_table_identity")
        if set(ids) != set(final_ids):
            note("unknown", "table_applicability_changed")
        from bs4 import BeautifulSoup
        from collections import Counter
        import markdown2

        rendered_markup = markdown2.markdown(markdown, extras=["fenced-code-blocks"])
        rendered_tables = Counter(
            hashlib.sha256(str(t).encode()).hexdigest()
            for t in BeautifulSoup(rendered_markup, "html.parser").find_all("table")
        )
        expected_tables = Counter(t.get("render_html_sha256") for t in finals)
        if None in expected_tables:
            note("unknown", "table_render_evidence_unavailable")
        elif rendered_tables != expected_tables:
            note("fail", "rendered_tables_missing_or_changed")
        by_id = {t.get("block_id"): t for t in traces}
        for final in finals:
            trace = by_id.get(final["block_id"])
            if trace is None:
                note("unknown", "missing_table_diagnostic")
                continue
            if trace.get("html_sha256_after_table_processor") != final["html_sha256"]:
                note("unknown", "table_changed_after_diagnostics")
            if (
                not trace.get("spans")
                or trace.get("has_html") is not True
                or trace.get("source_kind") != "digital_text"
                or trace.get("source_coverage") != "accounted"
                or trace.get("reconstruction_accepted") is not True
                or trace.get("requires_review") is True
                or any(s.get("status") == "unresolved" for s in trace.get("spans", []))
            ):
                note("unknown", "table_requires_review")
        from html.parser import HTMLParser

        class Images(HTMLParser):
            def __init__(self):
                super().__init__()
                self.sources = []

            def handle_starttag(self, tag, attrs):
                if tag == "img":
                    self.sources.extend(v for k, v in attrs if k == "src")

        images = Images()
        images.feed(rendered_markup)
        refs = images.sources
        for ref in refs:
            ref = ref.strip().strip("<>")
            if urlsplit(ref).scheme or ref.startswith("//"):
                note("fail", "nonlocal_image")
                continue
            name = unquote(ref)
            path = contained(root, name)
            if not path.is_file() or name not in artifacts:
                note("fail", "missing_image")
        for name in evidence["images"]:
            if name not in artifacts or not contained(root, name).is_file():
                note("fail", "missing_expected_image")
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
    ) as exc:
        artifacts = {}
        note("fail", "invalid_artifacts:" + type(exc).__name__)
    status = (
        "fail"
        if any(f["status"] == "fail" for f in findings)
        else "unknown"
        if findings
        else "pass"
    )
    return {"status": status, "findings": findings, "artifacts": artifacts}


def resumable(attempt, identity):
    try:
        attempt = Path(attempt)
        reject_link(attempt)
        record = json.loads(
            contained(attempt, "completion.json").read_text(encoding="utf-8")
        )
        if record["attempt_id"] != attempt.name:
            return False
        if (
            record["version"] != VERSION
            or record["status"] != "pass"
            or record["identity"] != identity
        ):
            return False
        if file_hash(contained(attempt, "input.pdf")) != identity["source"]["sha256"]:
            return False
        if record["evidence_sha256"] != file_hash(contained(attempt, "runtime.json")):
            return False
        evidence = json.loads(
            contained(attempt, "runtime.json").read_text(encoding="utf-8")
        )
        if evidence["attempt_id"] != attempt.name or evidence["identity"] != identity:
            return False
        expected_logs = {
            "probe.stdout.log",
            "probe.stderr.log",
            "conversion.stdout.log",
            "conversion.stderr.log",
            "probe.process.json",
            "conversion.process.json",
        }
        if set(record["logs"]) != expected_logs or any(
            file_hash(contained(attempt, name)) != value
            for name, value in record["logs"].items()
        ):
            return False
        checked = validate_outputs(attempt / "output", evidence)
        return (
            checked["status"] == "pass" and checked["artifacts"] == record["artifacts"]
        )
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError):
        return False
