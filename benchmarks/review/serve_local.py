"""Hold one owned local Surya server for bounded conversion comparisons."""

import argparse
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import urlparse


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--max-lifetime", type=int, default=1800)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.model_revision):
        raise ValueError("Use an immutable model revision")
    if not 1 <= args.max_lifetime <= 3600:
        raise ValueError("Lifetime must be between 1 and 3600 seconds")
    args.out.mkdir(parents=True, exist_ok=False)
    from surya.settings import settings
    from surya.inference import SuryaInferenceManager
    from surya.inference.backends.spawn import _read_sentinel

    settings.SURYA_INFERENCE_URL = None
    settings.SURYA_INFERENCE_BACKEND = "vllm"
    settings.SURYA_INFERENCE_AUTOSTART = True
    # This process stops the immutable container ID after checking ownership.
    settings.SURYA_INFERENCE_KEEP_ALIVE = True
    settings.SURYA_INFERENCE_STARTUP_TIMEOUT = 600
    settings.SURYA_MODEL_CHECKPOINT = "datalab-to/surya-ocr-2"
    settings.VLLM_DOCKER_IMAGE = "vllm/vllm-openai:v0.20.1"
    settings.VLLM_GPU_TYPE = "4090"
    settings.VLLM_DTYPE = "bfloat16"
    settings.VLLM_MAX_MODEL_LEN = 18000
    settings.VLLM_GPU_MEMORY_UTILIZATION = 0.80
    settings.VLLM_ENABLE_MTP = True
    settings.VLLM_MTP_TOKENS = 2
    settings.VLLM_EXTRA_ARGS = f"--revision {args.model_revision}"
    manager = SuryaInferenceManager(method="vllm")
    container_id = None
    started = time.monotonic()
    record = {"requested_model_revision": args.model_revision, "status": "starting"}
    try:
        handle = manager.backend.start()
        if not handle.spawned_by_us:
            raise RuntimeError("A server already exists; no owned test server was created or stopped")
        sentinel = _read_sentinel("vllm") or {}
        name = sentinel.get("cleanup_id")
        port = urlparse(handle.base_url).port
        if sentinel.get("cleanup_kind") != "docker" or sentinel.get("port") != port or not name:
            raise RuntimeError("Cannot verify owned server from its sentinel; inspect before cleanup")
        inspected = docker("inspect", name)
        inspected.check_returncode()
        details = json.loads(inspected.stdout)[0]
        container_id = details["Id"]
        command = details["Config"]["Cmd"]
        if "--revision" not in command or command[command.index("--revision") + 1] != args.model_revision:
            raise RuntimeError("Container revision differs from requested revision; inspect before cleanup")
        record.update(status="ready", base_url=handle.base_url, model=handle.model_name,
                      container_id=container_id, container_name=name,
                      image_id=details["Image"], launch_command=command,
                      startup_seconds=time.monotonic() - started)
        (args.out / "server.json").write_text(json.dumps(record, indent=2))
        print(json.dumps(record), flush=True)
        signals = queue.Queue()

        def read_stop():
            signals.put(sys.stdin.readline())

        threading.Thread(target=read_stop, daemon=True).start()
        try:
            signals.get(timeout=args.max_lifetime)
            record["stop_reason"] = "stdin or EOF"
        except queue.Empty:
            record["stop_reason"] = "lifetime expired"
    except Exception:
        record.update(status="error", error=traceback.format_exc(),
                      cleanup_verified=container_id is not None)
        raise
    finally:
        if container_id:
            current = docker("inspect", container_id)
            if current.returncode == 0:
                details = json.loads(current.stdout)[0]
                if details["Id"] != container_id:
                    raise RuntimeError("Container identity changed; refusing stop")
                logs = docker("logs", container_id)
                (args.out / "server.log").write_text(logs.stdout + logs.stderr)
                stopped = docker("stop", container_id)
                record["stop_exit_code"] = stopped.returncode
                record["status"] = "stopped" if stopped.returncode == 0 else "cleanup_failed"
            else:
                record["status"] = "container_already_absent"
        record["elapsed_seconds"] = time.monotonic() - started
        (args.out / "server.json").write_text(json.dumps(record, indent=2))
        manager.stop()


if __name__ == "__main__":
    main()
