"""Run the provided apps over HTTP and retain reproducible, redacted evidence.

Run inside day14-runner with repository mounted at /workspace.
"""
import json
import os
from pathlib import Path
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)
DEVELOP = ROOT / "06-lab-complete/benchmark-observability/develop"


def start(folder, port, **overrides):
    env = {**os.environ, "PORT": str(port), "PYTHONUNBUFFERED": "1", **overrides}
    # Keep Python imports and per-request logging on the Linux filesystem.
    # Windows bind-mount I/O would otherwise dominate the measurement itself.
    temporary = Path(tempfile.mkdtemp(prefix=f"day14-{port}-"))
    source = temporary / "source"
    shutil.copytree(folder, source, ignore=shutil.ignore_patterns("reports", "__pycache__"))
    log = (temporary / f"server_{port}.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app",
        "--host", "0.0.0.0", "--port", str(port), "--loop", "asyncio", "--no-access-log"],
        cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/openapi.json").status_code == 200:
                return proc, log
        except httpx.HTTPError:
            pass
        if proc.poll() is not None:
            raise RuntimeError(f"Server failed: {log.name}")
        time.sleep(0.1)
    raise RuntimeError(f"Server timeout: {log.name}")


def stop(server):
    proc, log = server
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        # Some teaching examples overwrite uvicorn's SIGTERM handler at import.
        # Record this behavior, then clean up only our own child process.
        print(f"Example {log.name} did not exit on SIGTERM; killed for cleanup", flush=True)
        proc.kill()
        proc.wait(timeout=5)
    log.close()
    shutil.copy2(log.name, REPORTS / Path(log.name).name)
    shutil.rmtree(Path(log.name).parent)


def response_data(response):
    return {"status": response.status_code, "body": response.json(),
            "headers": {k: v for k, v in response.headers.items()
                        if k in ("retry-after", "content-type", "x-request-id")}}


def exercises():
    results = {}
    server = start(ROOT / "01-localhost-vs-production/develop", 8011)
    try:
        results["part1_develop_query"] = response_data(httpx.post(
            "http://127.0.0.1:8011/ask", params={"question": "Hello"}))
        results["part1_develop_json"] = response_data(httpx.post(
            "http://127.0.0.1:8011/ask", json={"question": "Hello"}))
    finally:
        stop(server)
    server = start(ROOT / "01-localhost-vs-production/production", 8012)
    try:
        for path in ("/health", "/ready"):
            results["part1_production" + path] = response_data(httpx.get("http://127.0.0.1:8012" + path))
        results["part1_production_ask"] = response_data(httpx.post(
            "http://127.0.0.1:8012/ask", json={"question": "Hello"}))
    finally:
        stop(server)
    key = secrets.token_urlsafe(24)
    server = start(ROOT / "04-api-gateway/develop", 8014, AGENT_API_KEY=key)
    try:
        for label, headers in (("no_key", {}), ("valid_key", {"X-API-Key": key})):
            results["part4_api_key_" + label] = response_data(httpx.post(
                "http://127.0.0.1:8014/ask", headers=headers, json={"question": "Hello"}))
    finally:
        stop(server)
    # The develop example deliberately prints a fake secret. Do not retain that log.
    (REPORTS / "server_8011.log").unlink()
    server = start(ROOT / "04-api-gateway/production", 8015, JWT_SECRET=secrets.token_urlsafe(32))
    try:
        token_response = httpx.post("http://127.0.0.1:8015/auth/token",
                                   json={"username": "student", "password": "demo123"})
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        results["part4_jwt_missing"] = response_data(httpx.post("http://127.0.0.1:8015/ask", json={"question": "Hello"}))
        results["part4_jwt_burst"] = [response_data(httpx.post("http://127.0.0.1:8015/ask",
            headers={"Authorization": f"Bearer {token}"}, json={"question": "Docker"})) for _ in range(15)]
    finally:
        stop(server)
    (REPORTS / "exercises_http.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved HTTP evidence for Parts 1 and 4", flush=True)


def command(args, name):
    completed = subprocess.run([sys.executable, *args], cwd=DEVELOP, capture_output=True,
                               text=True, encoding="utf-8")
    (REPORTS / f"{name}.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    print(name, "exit", completed.returncode, flush=True)
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr)


def benchmark_baseline():
    servers = [start(DEVELOP, 8001, AGENT_VERSION="v1"), start(DEVELOP, 8002, AGENT_VERSION="v2")]
    try:
        if "--load-only" not in sys.argv and not (REPORTS / "eval_v2.json").exists():
            command(["eval/run_eval.py", "--url", "http://127.0.0.1:8001", "--out", str(REPORTS / "eval_v1.json")], "eval_v1")
            command(["eval/run_eval.py", "--url", "http://127.0.0.1:8002", "--baseline", str(REPORTS / "eval_v1.json"),
                     "--out", str(REPORTS / "eval_v2.json")], "eval_v2")
            command(["eval/run_eval.py", "--url", "http://127.0.0.1:8001", "--baseline", str(REPORTS / "eval_v2.json"),
                     "--out", str(REPORTS / "eval_v1_regression.json")], "eval_v1_regression")
        elif "--load-only" not in sys.argv:
            print("Kept historical v1/v2 baseline files; current knowledge base is already fixed", flush=True)
        for concurrency in (1, 10, 50, 100):
            name = f"load_v2_c{concurrency}"
            command(["load_test.py", "--url", "http://127.0.0.1:8002", "--requests", "300", "--concurrency", str(concurrency),
                     "--out", str(REPORTS / f"{name}.json")], name)
    finally:
        for server in servers:
            stop(server)
    for slow_rate in ("0", "0.03", "0.1"):
        server = start(DEVELOP, 8002, AGENT_VERSION="v2", MOCK_SLOW_RATE=slow_rate)
        try:
            name = f"load_v2_slow_{slow_rate}"
            command(["load_test.py", "--url", "http://127.0.0.1:8002", "--requests", "300", "--concurrency", "20",
                     "--out", str(REPORTS / f"{name}.json")], name)
        finally:
            stop(server)


def fixed_eval():
    server = start(DEVELOP, 8002, AGENT_VERSION="v2")
    try:
        command(["eval/run_eval.py", "--url", "http://127.0.0.1:8002", "--min-accuracy", "1.0",
                 "--baseline", str(REPORTS / "eval_v2.json"), "--out", str(REPORTS / "eval_v2_fixed.json")], "eval_v2_fixed")
        report = json.loads((REPORTS / "eval_v2_fixed.json").read_text(encoding="utf-8"))
        assert report["quality_gate"]["passed"], report
    finally:
        stop(server)


if __name__ == "__main__":
    if "--fixed" in sys.argv:
        fixed_eval()
    elif "--load-only" in sys.argv:
        benchmark_baseline()
    else:
        exercises()
        benchmark_baseline()
