"""Capture real service UIs using an isolated headless Chrome session."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPORTS, SHOTS = ROOT / "reports", ROOT / "screenshots"
SHOTS.mkdir(exist_ok=True)


def capture(mode):
    manifest_path = REPORTS / "screenshot_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,
            executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe")
        page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=1)
        page.set_default_navigation_timeout(90000)
        page.set_default_timeout(30000)
        if mode in ("baseline", "all"):
            config = ROOT / "06-lab-complete/benchmark-observability/production/grafana/dashboards/agent-overview.json"
            uid = json.loads(config.read_text(encoding="utf-8"))["uid"]
            page.goto(f"http://127.0.0.1:3000/d/{uid}?orgId=1&from=now-15m&to=now&refresh=5s", wait_until="domcontentloaded")
            page.wait_for_timeout(12000)
            (REPORTS / "grafana_ui.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
            page.screenshot(path=str(SHOTS / "grafana-dashboard.png"), full_page=True)
            print("Captured Grafana", flush=True)
        if mode in ("alerts", "all"):
            page.goto("http://127.0.0.1:9090/alerts", wait_until="domcontentloaded")
            page.get_by_text("AgentHighErrorRate", exact=False).first.wait_for(timeout=90000)
            page.wait_for_timeout(3000)
            (REPORTS / "prometheus_alerts_ui.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
            page.screenshot(path=str(SHOTS / "prometheus-alert-firing.png"), full_page=True)
            print("Captured Prometheus", flush=True)
        if mode in ("traces", "all"):
            for kind, filename in (("slow", "jaeger-slow-trace.png"), ("error", "jaeger-error-trace.png")):
                candidates = sorted(REPORTS.glob(f"{kind}_trace_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not candidates:
                    raise RuntimeError(f"No saved {kind} trace")
                trace = json.loads(candidates[0].read_text(encoding="utf-8"))
                page.goto(f"http://127.0.0.1:16686/trace/{trace['traceID']}", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                (REPORTS / f"jaeger_{kind}_loading.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
                page.get_by_text("chat mock-llm", exact=False).first.wait_for(timeout=90000)
                page.get_by_text("chat mock-llm", exact=False).first.click()
                details = page.get_by_text("Details", exact=True)
                if details.count():
                    details.first.click()
                page.wait_for_timeout(2000)
                (REPORTS / f"jaeger_{kind}_ui.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
                page.screenshot(path=str(SHOTS / filename), full_page=True)
                manifest[filename] = {"trace_id": trace["traceID"], "source": candidates[0].name}
                print("Captured Jaeger", kind, trace["traceID"], flush=True)
        browser.close()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["baseline", "alerts", "traces", "all"])
    capture(parser.parse_args().mode)
