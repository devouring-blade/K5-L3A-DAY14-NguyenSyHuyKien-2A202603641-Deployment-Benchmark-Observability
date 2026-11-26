"""Validate the local deliverables against their recorded evidence."""
import csv
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def main():
    for name in ("MISSION_ANSWERS.md", "DEPLOYMENT.md", "BENCHMARK_REPORT.md"):
        assert (ROOT / name).is_file(), name
    for concurrency in (1, 10, 50, 100):
        result = json.loads((REPORTS / f"load_v2_c{concurrency}.json").read_text(encoding="utf-8"))
        assert result["concurrency"] == concurrency and result["total_requests"] == 300
        assert sum(result["status_codes"].values()) == result["total_requests"]
    for rate in ("0", "0.03", "0.1"):
        result = json.loads((REPORTS / f"load_v2_slow_{rate}.json").read_text(encoding="utf-8"))
        assert result["concurrency"] == 20 and result["total_requests"] == 300
    result = json.loads((REPORTS / "eval_v2_fixed.json").read_text(encoding="utf-8"))
    assert result["passed"] == result["total"] == 23
    assert result["quality_gate"]["passed"] and not result["quality_gate"]["regressions"]
    assert "PASS 12/12" in (REPORTS / "production_ready.txt").read_text(encoding="utf-8")
    for replicas in (1, 3):
        with (ROOT / "benchmark-results" / f"scale_{replicas}_stats.csv").open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        row = next(r for r in rows if r["Name"] == "Aggregated")
        assert 0 <= int(row["Failure Count"]) <= int(row["Request Count"])
        snapshot = (REPORTS / f"scale_{replicas}_instances.txt").read_text(encoding="utf-8-sig")
        assert len(snapshot.strip().splitlines()) == replicas, snapshot
    for filename in ("grafana-dashboard.png", "jaeger-slow-trace.png", "jaeger-error-trace.png", "prometheus-alert-firing.png"):
        image = (ROOT / "screenshots" / filename).read_bytes()
        assert image.startswith(b"\x89PNG\r\n\x1a\n") and len(image) > 10000, filename
    firing = json.loads((REPORTS / "alerts_AB_firing.json").read_text(encoding="utf-8"))
    names = {a["labels"]["alertname"] for a in firing["data"]["alerts"] if a["state"] == "firing"}
    assert {"AgentHighErrorRate", "AgentHighLatencyP95"} <= names, names
    assert "exception" in (REPORTS / "jaeger_error_ui.txt").read_text(encoding="utf-8").lower()
    manifest = json.loads((REPORTS / "screenshot_manifest.json").read_text(encoding="utf-8"))
    error_trace = json.loads((REPORTS / manifest["jaeger-error-trace.png"]["source"]).read_text(encoding="utf-8"))
    assert any(e.get("name") == "exception" for s in error_trace["spans"] for e in s.get("events", []))
    protected = ["06-lab-complete/check_production_ready.py",
                 "06-lab-complete/benchmark-observability/develop/eval/golden_dataset.jsonl"]
    changed = subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", *protected], cwd=ROOT, text=True)
    assert not changed.strip(), changed
    assert not subprocess.check_output(["git", "ls-files", "--", "*.env", ".env"], cwd=ROOT, text=True).strip()
    for label, required in (("AB", {"AgentHighErrorRate", "AgentHighLatencyP95"}), ("C", {"LLMCostBurnRateHigh"})):
        result = json.loads((REPORTS / f"chaos_{label}.json").read_text(encoding="utf-8"))
        assert required <= set(result["first_firing_seconds"]), label
    down = json.loads((REPORTS / "chaos_D.json").read_text(encoding="utf-8"))
    assert down["first_firing_seconds"] is not None
    version = json.loads((REPORTS / "chaos_E.json").read_text(encoding="utf-8"))
    assert version["eval_exit_code"] == 1
    evaluation = json.loads((REPORTS / "eval_production_v1.json").read_text(encoding="utf-8"))
    assert evaluation["total"] == 23 and not evaluation["quality_gate"]["passed"]
    cloud_path = REPORTS / "public_deployment.json"
    if cloud_path.exists():
        cloud = json.loads(cloud_path.read_text(encoding="utf-8"))
        assert [r["status"] for r in cloud["results"]] == [200, 200, 401, 200]
        for name in ("dashboard.png", "running.png", "test.png"):
            data = (ROOT / "screenshots" / name).read_bytes()
            assert data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) > 10000
        print("Local and cloud deliverables verified: 12/12, eval 23/23, seven screenshots, public 200/200/401/200. LMS link submission remains.")
    else:
        print("Local deliverables verified. Cloud URL/screenshots and LMS submission remain manual account steps.")


if __name__ == "__main__":
    main()
