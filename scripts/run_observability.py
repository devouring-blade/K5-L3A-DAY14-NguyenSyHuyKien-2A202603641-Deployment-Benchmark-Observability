"""Reproduce scaling, chaos alerts, traces and logs with the provided stack."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "06-lab-complete/benchmark-observability/production"
REPORTS = ROOT / "reports"
COMPOSE = ["docker", "compose", "-p", "k5-day14-observability"]
client = httpx.Client(timeout=20, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0))


def save(name, data):
    (REPORTS / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def compose(*args, env=None, background=False, log="observability_commands.txt"):
    stream = (REPORTS / log).open("a", encoding="utf-8")
    cmd = [*COMPOSE, *args]
    stream.write("\n" + " ".join(cmd) + "\n")
    stream.flush()
    process = subprocess.Popen(cmd, cwd=OBS, env={**os.environ, **(env or {})},
                               stdout=stream, stderr=subprocess.STDOUT)
    if background:
        return process, stream
    code = process.wait()
    stream.close()
    if code:
        raise RuntimeError(f"Compose exited {code}: {cmd}")


def wait_http(url, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if client.get(url).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise RuntimeError(f"HTTP timeout: {url}")


def load(prefix, users=100, duration="2m", background=False):
    # The stack is already up. Starting dependencies here would reconcile the
    # agent back to default env/replicas, invalidating scale and chaos settings.
    return compose("run", "--rm", "--no-deps", "locust", "-f", "/mnt/locust/locustfile.py",
        "--host", "http://nginx", "--headless", "-u", str(users), "-r", "10",
        "-t", duration, "--csv", f"/mnt/results/{prefix}", background=background,
        log=f"locust_{prefix}.txt")


def finish_load(handle):
    process, stream = handle
    code = process.wait()
    stream.close()
    # The mock deliberately has upstream errors. Locust returns 1 on failures.
    if code not in (0, 1):
        raise RuntimeError(f"Unexpected Locust exit {code}")


def alert_experiment(label, settings, expected, duration="4m", users=30):
    started = time.monotonic()
    stamp = datetime.now(timezone.utc).isoformat()
    compose("up", "-d", "--no-deps", "--scale", "agent=3", "agent", env=settings)
    wait_http("http://127.0.0.1:8080/health")
    handle = load(f"chaos_{label}", users=users, duration=duration, background=True)
    first = {}
    snapshots = []
    while handle[0].poll() is None:
        try:
            data = client.get("http://127.0.0.1:9090/api/v1/alerts").json()
            snapshots.append({"elapsed_s": round(time.monotonic() - started, 2), "data": data})
            for alert in data["data"]["alerts"]:
                name = alert["labels"]["alertname"]
                if alert["state"] == "firing" and name in expected and name not in first:
                    first[name] = round(time.monotonic() - started, 2)
                    print(label, name, "firing at", first[name], "s", flush=True)
            if all(name in first for name in expected):
                save(f"alerts_{label}_firing.json", data)
                (REPORTS / f"READY_SCREENSHOT_{label}").write_text(stamp, encoding="utf-8")
                if label == "AB" and not (ROOT / "screenshots/prometheus-alert-firing.png").exists():
                    for mode in ("alerts", "baseline"):
                        shot = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"),
                            str(ROOT / "scripts/capture_dashboards.py"), mode],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
                        (REPORTS / f"screenshot_{mode}.txt").write_text(shot.stdout + shot.stderr, encoding="utf-8")
        except httpx.HTTPError:
            pass
        save(f"chaos_{label}.json", {"changed_at_utc": stamp, "settings": settings,
            "first_firing_seconds": first, "snapshots": snapshots})
        time.sleep(5)
    finish_load(handle)
    capture_traces(label)
    return first


def capture_traces(label):
    now = datetime.now(timezone.utc)
    response = client.get("http://127.0.0.1:16686/api/v3/traces", params={
        "query.serviceName": "observable-agent", "query.numTraces": 200,
        "query.startTimeMin": (now - timedelta(hours=1)).isoformat(),
        "query.startTimeMax": now.isoformat()})
    response.raise_for_status()
    # Jaeger v3 streams OTLP JSON. Preserve the exact response and normalize
    # nanosecond spans to microseconds for report calculations.
    (REPORTS / f"traces_{label}_otlp.jsonl").write_text(response.text, encoding="utf-8")
    grouped = {}
    for line in response.text.splitlines():
        result = json.loads(line).get("result", {})
        for resource in result.get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    trace = grouped.setdefault(span["traceId"], {"traceID": span["traceId"], "spans": []})
                    tags = [{"key": a["key"], "value": next(iter(a["value"].values()), None)}
                            for a in span.get("attributes", [])]
                    if span.get("status", {}).get("code") == 2:
                        tags.append({"key": "error", "value": True})
                    trace["spans"].append({"spanID": span["spanId"], "operationName": span["name"],
                        "startTime": int(span["startTimeUnixNano"]) / 1000,
                        "duration": (int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])) / 1000,
                        "tags": tags, "events": span.get("events", [])})
    traces = list(grouped.values())
    save(f"traces_{label}.json", {"data": traces, "source": "Jaeger API v3 OTLP"})
    if traces:
        def duration(trace):
            spans = trace["spans"]
            return max(s["startTime"] + s["duration"] for s in spans) - min(s["startTime"] for s in spans)
        save(f"slow_trace_{label}.json", max(traces, key=duration))
        errors = [t for t in traces if any(
            any(tag["key"] == "error" and tag["value"] for tag in s.get("tags", []))
            for s in t["spans"])]
        if errors:
            save(f"error_trace_{label}.json", errors[0])
    logs = subprocess.run([*COMPOSE, "logs", "--no-color", "agent"], cwd=OBS,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    (REPORTS / f"agent_logs_{label}.txt").write_text(logs.stdout, encoding="utf-8")


def main():
    resume = "--resume-chaos" in sys.argv
    compose("up", "-d", "--scale", "agent=3" if resume else "agent=1")
    for url in ("http://127.0.0.1:8080/health", "http://127.0.0.1:9090/-/ready",
                "http://127.0.0.1:3000/api/health", "http://127.0.0.1:16686/"):
        wait_http(url)
    save("observability_http.json", {path: client.get("http://127.0.0.1:8080" + path).status_code
                                     for path in ("/health", "/ready", "/metrics")})
    # Headless runs retain CSV even when the mock produces its expected ~1% failures.
    if not resume:
        finish_load(load("scale_1", background=True))
        compose("up", "-d", "--scale", "agent=3")
        time.sleep(20)  # DNS refresh is 10s in both Prometheus and Nginx.
        finish_load(load("scale_3", background=True))
    (REPORTS / "READY_SCREENSHOT_BASELINE").write_text("scaling complete", encoding="utf-8")
    if not resume:
        capture_traces("baseline")
    # Let 1m rate windows go idle so load-induced alerts are not misattributed
    # to the following injected faults.
    time.sleep(75)
    alert_experiment("AB", {"MOCK_ERROR_RATE": "0.2", "MOCK_SLOW_RATE": "0.3"},
                     ["AgentHighErrorRate", "AgentHighLatencyP95"])
    alert_experiment("C", {"LLM_MODEL": "mock-llm-large"}, ["LLMCostBurnRateHigh"])
    # Pausing keeps the target in DNS, unlike stopping it.
    ids = subprocess.check_output([*COMPOSE, "ps", "-q", "agent"], cwd=OBS, text=True).split()
    started = time.monotonic()
    subprocess.run(["docker", "pause", ids[0]], check=True, stdout=subprocess.DEVNULL)
    first = None
    snapshots = []
    try:
        handle = load("chaos_D", users=30, duration="90s", background=True)
        while handle[0].poll() is None:
            data = client.get("http://127.0.0.1:9090/api/v1/alerts").json()
            elapsed = round(time.monotonic() - started, 2)
            snapshots.append({"elapsed_s": elapsed, "data": data})
            if first is None and any(a["state"] == "firing" and a["labels"]["alertname"] == "AgentInstanceDown"
                                     for a in data["data"]["alerts"]):
                first = elapsed
                print("D AgentInstanceDown firing at", first, "s", flush=True)
            time.sleep(5)
        finish_load(handle)
    finally:
        subprocess.run(["docker", "unpause", ids[0]], check=True, stdout=subprocess.DEVNULL)
    save("chaos_D.json", {"first_firing_seconds": first, "snapshots": snapshots})
    compose("up", "-d", "--no-deps", "--scale", "agent=3", "agent", env={"AGENT_VERSION": "v1"})
    time.sleep(20)
    cmd = ["docker", "run", "--rm", "--network", "host", "-v", f"{ROOT}:/workspace", "-w",
        "/workspace/06-lab-complete/benchmark-observability/develop", "day14-runner", "python", "eval/run_eval.py",
        "--url", "http://127.0.0.1:8080", "--api-key", "day14-lab-key", "--baseline",
        "/workspace/reports/eval_v2_fixed.json", "--out", "/workspace/reports/eval_production_v1.json"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (REPORTS / "eval_production_v1.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    save("chaos_E.json", {"version": "v1", "eval_exit_code": result.returncode,
        "alerts": client.get("http://127.0.0.1:9090/api/v1/alerts").json()})
    compose("up", "-d", "--no-deps", "--scale", "agent=3", "agent")
    target = ROOT / "benchmark-results"
    target.mkdir(exist_ok=True)
    for source in (OBS / "benchmark-results").glob("*.csv"):
        shutil.copy2(source, target / source.name)
    print("Observability experiments complete; stack left running for screenshot verification", flush=True)


if __name__ == "__main__":
    main()
