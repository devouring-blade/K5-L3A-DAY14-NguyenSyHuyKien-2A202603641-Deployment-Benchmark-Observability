"""Verify the public agent; credential is read only from process memory/env."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
base = os.environ.get("AGENT_PUBLIC_URL", "https://day14-agent-twkr.onrender.com").rstrip("/")
key = os.environ["AGENT_API_KEY"]


def request(method, path, authenticated=False):
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["X-API-Key"] = key
    body = json.dumps({"question": "Hello"}).encode() if method == "POST" else None
    req = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=90)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw
        return {"method": method, "path": path, "authenticated": authenticated,
                "status": response.code, "body": payload}


results = [request("GET", "/health"), request("GET", "/ready"),
           request("POST", "/ask"), request("POST", "/ask", authenticated=True)]
report = {"base_url": base, "checked_at_utc": datetime.now(timezone.utc).isoformat(), "results": results}
(ROOT / "reports/public_deployment.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
for item in results:
    print(f"{item['method']} {item['path']} authenticated={item['authenticated']} -> {item['status']}")
assert [item["status"] for item in results] == [200, 200, 401, 200], report
print("Public deployment checks passed; credential was not written to disk")
