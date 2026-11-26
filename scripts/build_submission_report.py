"""Build submission tables from actual JSON/CSV evidence (no synthetic values)."""
import csv
import json
from pathlib import Path
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OBS = ROOT / "06-lab-complete/benchmark-observability/production"


def read(name):
    return json.loads((REPORTS / name).read_text(encoding="utf-8-sig"))


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers),
        *("| " + " | ".join(map(str, row)) + " |" for row in rows)])


def find_log(trace_id, event):
    for path in sorted(REPORTS.glob("agent_logs_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True):
        for line in path.read_text(encoding="utf-8").splitlines():
            if trace_id not in line or "{" not in line:
                continue
            try:
                item = json.loads(line[line.index("{"):])
            except ValueError:
                continue
            if item.get("event") == event and item.get("trace_id") == trace_id:
                return item
    return None


def main():
    target = ROOT / "benchmark-results"
    target.mkdir(exist_ok=True)
    for source in (OBS / "benchmark-results").glob("*.csv"):
        shutil.copy2(source, target / source.name)
    develop_reports = ROOT / "06-lab-complete/benchmark-observability/develop/reports"
    develop_reports.mkdir(exist_ok=True)
    for pattern in ("load_v2_*.json", "eval_v*.json"):
        for source in REPORTS.glob(pattern):
            shutil.copy2(source, develop_reports / source.name)

    loads = [read(f"load_v2_c{c}.json") for c in (1, 10, 50, 100)]
    tails = [read(f"load_v2_slow_{rate}.json") for rate in ("0", "0.03", "0.1")]
    versions = [read(f"eval_{version}.json") for version in ("v1", "v2", "v2_fixed")]
    load_table = table(["Concurrency", "RPS", "p50 ms", "p95 ms", "p99 ms", "Error rate", "SLO"], [
        [r["concurrency"], r["rps"], r["latency_ms"]["p50"], r["latency_ms"]["p95"], r["latency_ms"]["p99"],
         f'{r["error_rate"]:.2%}', "PASS" if r["slo"]["passed"] else "FAIL"] for r in loads])
    tail_table = table(["MOCK_SLOW_RATE", "avg ms", "p95 ms", "p99 ms"], [
        [rate, r["latency_ms"]["avg"], r["latency_ms"]["p95"], r["latency_ms"]["p99"]]
        for rate, r in zip(("0", "0.03", "0.1"), tails)])
    quality_table = table(["Chỉ số", "v1", "v2 ban đầu", "v2 sau sửa KB"], [
        ["Accuracy", *[f'{r["passed"]}/{r["total"]} ({r["accuracy"]:.2%})' for r in versions]],
        ["Avg tokens/câu", *[r["avg_tokens"] for r in versions]],
        ["Tổng cost USD", *[r["total_cost_usd"] for r in versions]],
        ["Cost/câu đúng USD", *[r["cost_per_correct_usd"] for r in versions]],
        ["p95 ms", *[r["latency_ms"]["p95"] for r in versions]],
        ["Quality gate", *["PASS" if r["quality_gate"]["passed"] else "FAIL" for r in versions]]])
    failures = [r for r in versions[1]["results"] if not r["passed"]]
    fixes = table(["ID", "Keyword thiếu", "Thay đổi KB"], [[r["id"], ", ".join(r.get("missing_keywords", [])),
        "Thêm mô tả HPA: CPU, memory, custom metrics" if r["id"] == "scaling-03" else "Thêm mô tả JWT: token, chữ ký, hết hạn"] for r in failures])
    scaling_rows = []
    for replicas in (1, 3):
        with (target / f"scale_{replicas}_stats.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        row = next(r for r in rows if r["Name"] == "Aggregated")
        scaling_rows.append([replicas, round(float(row["Requests/s"]), 3), row["50%"], row["95%"], row["99%"],
            f'{row["Failure Count"]}/{row["Request Count"]} ({int(row["Failure Count"])/int(row["Request Count"]):.2%})'])
    scale_table = table(["Instances", "RPS", "p50 ms", "p95 ms", "p99 ms", "Failures"], scaling_rows)
    rps1, rps3 = float(scaling_rows[0][1]), float(scaling_rows[1][1])
    p951, p953 = float(scaling_rows[0][3]), float(scaling_rows[1][3])
    scale_comment = (f"RPS đổi từ {rps1:g} lên {rps3:g}; p95 đổi từ {p951:g}ms sang {p953:g}ms. "
        + ("Scale cải thiện p95 trong lượt đo này. " if p953 < p951 else "Scale không cải thiện p95 trong lượt đo này. ")
        + "Cần đọc cùng failures.csv và trace, vì response lỗi tại proxy cũng nằm trong bảng tổng. "
        "Nếu LLM span vẫn chiếm phần lớn thời gian thì thêm instance chủ yếu giảm queueing, không giảm latency upstream. "
        "Nếu có nhiều 502/504 hoặc duration vượt xa latency mock, kiểm tra CPU quota, throttling và kết nối Nginx; "
        "không quy mọi chậm trễ cho LLM hoặc dùng response lỗi nhanh để tuyên bố hệ thống nhanh hơn.")
    chaos_rows = []
    for label, change, alert in (("AB", "MOCK_ERROR_RATE=0.2 + MOCK_SLOW_RATE=0.3", "AgentHighErrorRate / AgentHighLatencyP95"),
            ("C", "LLM_MODEL=mock-llm-large", "LLMCostBurnRateHigh"), ("D", "docker pause một instance", "AgentInstanceDown")):
        path = REPORTS / f"chaos_{label}.json"
        result = read(path.name) if path.exists() else None
        firing = result.get("first_firing_seconds") if result else None
        measured = ("; ".join(f"{k}: {v}s" for k, v in firing.items()) or "Chưa quan sát firing") if isinstance(firing, dict) else (f"{firing}s" if firing is not None else "Chưa có kết quả")
        if result and result.get("changed_at_utc") and result.get("snapshots"):
            changed = datetime.fromisoformat(result["changed_at_utc"])
            first_snapshot = result["snapshots"][0]["data"]["data"]["alerts"]
            preexisting = [a["labels"]["alertname"] for a in first_snapshot
                if a["state"] == "firing" and a.get("activeAt")
                and datetime.fromisoformat(a["activeAt"].replace("Z", "+00:00")) < changed]
            if label == "C" and "LLMCostBurnRateHigh" in preexisting:
                measured = "Đã firing trước khi đổi model; không đo được độ trễ phát hiện mới"
        chaos_rows.append([label, change, alert, measured])
    chaos_table = table(["Thí nghiệm", "Thay đổi", "Alert kiểm tra", "Thời gian đã đo"], chaos_rows)
    e_path = REPORTS / "eval_production_v1.json"
    if e_path.exists():
        e_result = read(e_path.name)
        e_note = (f"Kết quả E đã đo: v1 đúng {e_result['passed']}/{e_result['total']} "
            f"({e_result['accuracy']:.2%}); quality gate "
            f"{'PASS' if e_result['quality_gate']['passed'] else 'FAIL'}, "
            f"{len(e_result['quality_gate']['regressions'])} câu regression so với v2 đã sửa.")
    else:
        e_note = "Kết quả E chưa thu xong; không điền accuracy giả."
    shots = [name for name in ("grafana-dashboard.png", "jaeger-slow-trace.png", "jaeger-error-trace.png", "prometheus-alert-firing.png") if (ROOT / "screenshots" / name).exists()]
    shot_links = "\n".join(f"- [{name}](screenshots/{name})" for name in shots)
    trace_section = "Chưa thu được trace kèm log; không điền ID hoặc thời gian giả."
    manifest = read("screenshot_manifest.json") if (REPORTS / "screenshot_manifest.json").exists() else {}
    trace_meta = manifest.get("jaeger-slow-trace.png")
    if trace_meta:
        trace = read(trace_meta["source"])
        spans = trace["spans"]
        total = max(s["startTime"] + s["duration"] for s in spans) - min(s["startTime"] for s in spans)
        llm = max((s for s in spans if s["operationName"].startswith("chat ")), key=lambda s: s["duration"])
        log = find_log(trace["traceID"], "llm_call")
        trace_section = f'''Trace ID: `{trace['traceID']}`. Tổng thời gian: **{total / 1000:.3f} ms**.
Span LLM: `{llm['operationName']}`, **{llm['duration'] / 1000:.3f} ms**, chiếm **{llm['duration'] / total:.2%}** tổng thời gian.
Các span cha bao gồm thời gian con, không cộng chồng các duration. LLM là bước cần kiểm tra trước; retrieval và overhead được tách ở waterfall.

Log có cùng trace_id (nguồn `reports/agent_logs_*.txt`):

```json
{json.dumps(log, ensure_ascii=False) if log else 'Chưa tìm thấy log khớp; cần bổ sung.'}
```
'''
    error_meta = manifest.get("jaeger-error-trace.png")
    if error_meta:
        error_trace = read(error_meta["source"])
        error_log = find_log(error_trace["traceID"], "llm_error")
        trace_section += f'''
Trace lỗi: `{error_trace['traceID']}`. Ảnh `jaeger-error-trace.png` hiển thị HTTP 503,
span LLM có `error.type=upstream_unavailable` và event `exception`.
Log lỗi có cùng trace_id:

```json
{json.dumps(error_log, ensure_ascii=False) if error_log else 'Chưa tìm thấy log lỗi khớp; cần bổ sung.'}
```
'''
    content = f'''# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Sỹ Huy Kiên — 2A202603641

**Ngày chạy:** 25–26/11/2026 (GMT+7); ngày 26 tiếp tục sau khi Docker/máy dừng.

**Môi trường:** Windows, Docker Desktop Linux, 8 CPU được cấp, RAM Docker 3.718 GiB; Python 3.11 trong runner. Agent observability bị giới hạn 0.5 CPU/256 MiB mỗi container. LLM là mock, chi phí là mô phỏng.

## 1. SLO

| SLI | Mục tiêu | Lý do |
|---|---|---|
| p95 POST /ask | ≤500 ms | Phần lớn request cần phản hồi nhanh; vẫn quan sát p99 để thấy tail |
| Error rate POST /ask | ≤2% | Có khoảng 1% lỗi upstream được mô phỏng |
| Accuracy golden dataset | 100% ở quality gate cuối | Bộ 23 câu cố định của lab, không sửa đáp án |

SLO local theo ngưỡng mặc định của load_test.py. Alert production có ngưỡng riêng trong alert_rules.yml: 5% error và p95 >1s; không đồng nhất hai cấu hình.

## 2. Benchmark hiệu năng

### 2.1 Concurrency

Mỗi mức 300 request, MOCK_SLOW_RATE mặc định 0.03, MOCK_ERROR_RATE mặc định 0.01. Bảng sinh từ `reports/load_v2_c*.json`.

{load_table}

RPS không tăng tuyến tính mãi: concurrency cho phép chồng thời gian chờ I/O nhưng thêm scheduling, HTTP connection contention và queueing. Khi đạt khả năng xử lý của một process/CPU, p95/p99 tăng. Không gọi một lần test FAIL là PASS chỉ vì accuracy tốt.

Mức 50 và 100 được chạy ở hai thời điểm khác nhau trên máy dùng chung tài nguyên với Docker; RPS của mức 100 cao hơn mức 50 không chứng minh 100 là cấu hình tối ưu. Cần lặp nhiều lượt trong môi trường cô lập để suy ra đường cong capacity đáng tin cậy.

### 2.2 Tail latency

Ba lần chạy cùng 300 request/concurrency 20; mỗi lần restart v2 với slow rate tương ứng.

{tail_table}

p99 rất nhạy với nhóm request chậm; ở slow rate 10%, p95 cũng lọt vào nhóm được cộng 1500ms. Average trộn đa số nhanh với thiểu số chậm, dễ che trải nghiệm ở đuôi phân phối. Mỗi mẫu chỉ 300 request và fault ngẫu nhiên, nên không suy diễn thành kết quả ổn định của production.

Lần đo đầu khi Docker còn build/tải image được giữ ở `reports/initial_busy/`. Bảng chính dùng lần đo lại: source và log của server đặt trên filesystem Linux, tránh Windows bind-mount I/O chi phối phép đo. Một số load vẫn đồng thời với stack giám sát trên cùng máy; đây là giới hạn kiểm soát tài nguyên của thí nghiệm.

## 3. Benchmark chất lượng

{quality_table}

{fixes}

Đã chép cùng KB sửa sang develop và production. v2 tăng token do prompt có retrieval nhưng cải thiện cost/câu đúng. KB bổ sung dài hơn làm chi phí v2 sau sửa tăng; latency giữa các lần còn chịu ảnh hưởng tải máy, không quy toàn bộ chênh lệch cho KB.

Quality gate cuối yêu cầu accuracy 1.0 và không regression so với eval_v2.json. Thử v1 với baseline v2 trả exit code 1; xem `reports/eval_v1_regression.json`. Workflow `.github/workflows/quality-gate.yml` chạy gate trên push/PR và upload report. Cần chọn job này làm required status check trong branch protection để GitHub thực sự chặn merge. Workflow đã tạo, chưa xác nhận chạy trên GitHub.

## 4. Observability

### 4.1 Bằng chứng giao diện

{shot_links or 'Chưa chụp được ảnh; không thay bằng hình minh hoạ.'}

Prometheus pull /metrics mỗi 5s, DNS discovery tìm từng agent; Grafana query Prometheus. Nginx chặn /metrics public (404) nhưng agent nội bộ vẫn cho scrape. GET /health và /ready qua Nginx trả 200: `reports/observability_http.json`.

Lượt kiểm soát chạy Locust bằng `docker compose run --rm --no-deps locust ...` vì stack đã khởi động. Nếu thiếu --no-deps, Compose có thể reconcile agent về env/replicas mặc định, phá phép đo scaling hoặc fault injection. Các lượt trước khi phát hiện lỗi được giữ riêng trong `reports/initial_busy/benchmark-results/`, không dùng làm bằng chứng số instance cố định.

Golden Signals: traffic, error rate, latency, in-flight requests. Dùng route template thay URL thực để tránh cardinality theo ID. Không gắn câu hỏi/user_id/request_id làm metric label. Metrics cho biết triệu chứng; trace tách thời gian retrieval/LLM; JSON log liên kết bằng trace_id.

Percentile Prometheus được ước lượng từ histogram buckets; load_test.py đo phía client và tính percentile trên các response 200. Điểm đo và tập mẫu khác nhau nên không yêu cầu hai con số trùng nhau.

### 4.2 Chaos và alerts

{chaos_table}

A và B được bật đồng thời trên cùng lượt traffic để chụp hai alert firing; không kết luận tác động độc lập từ lượt kết hợp này. Thời gian tính từ lúc bắt đầu áp cấu hình (gồm recreate/startup), lấy snapshot API mỗi 5s. C có panel cost USD/giờ; D có Instances up và scrape up. Rule `for` cần điều kiện đúng liên tục và thêm độ trễ scrape/evaluation.

Pause giữ container trong DNS nên Prometheus thấy target nhưng up=0; stop có thể xoá target khỏi discovery. Lỗi 504 sinh ở Nginx không nhất thiết được agent đếm vào metric HTTP, cần metric ở tầng LB hoặc synthetic probe để thấy đủ lỗi người dùng.

Thí nghiệm E: đổi AGENT_VERSION=v1 làm giảm chất lượng trong khi request vẫn trả 200. Phát hiện bằng golden eval, canary/synthetic câu hỏi và theo dõi version/retrieval; metric hạ tầng không chứng minh câu trả lời đúng. Bằng chứng nếu đã chạy nằm trong `reports/chaos_E.json`, `eval_production_v1.json`; alert cũ còn firing sau fault trước không được coi là do v1 gây ra.

{e_note}

Alert rule tests gốc đã chạy bằng promtool: `reports/alert_rules_test.txt` báo SUCCESS. Jaeger image 2.23 chạy API v3; raw OTLP ở `reports/traces_*_otlp.jsonl`, file JSON chuẩn hoá chỉ đổi đơn vị ns sang µs để tính thời gian, không sinh span mới.

### 4.3 Debug trace

{trace_section}

## 5. Scaling bằng Locust headless

Cùng 100 users, ramp 10/s, cấu hình -t 2m. Bảng lấy hàng Aggregated (gồm /ask và /health), không chỉ request thành công. Thời gian kết thúc thực có thể dài hơn 2 phút vì request đang chờ; xem stats history và output Locust.

{scale_table}

{scale_comment}

## 6. Bài học và trạng thái nộp

1. Đo p95/p99 cùng error rate và throughput; trung bình hoặc RPS riêng lẻ có thể gây hiểu sai.
2. Chất lượng, tốc độ và chi phí là ba trục khác nhau; cost/câu đúng hữu ích hơn cost/câu.
3. Correlate metric → trace → log giúp phân biệt lỗi upstream, queueing và lỗi tại proxy.

Khi triển khai thật: thêm metric ở Nginx, hàng đợi/timeouts, CPU throttling, Redis availability, budget remaining và canary chất lượng. Bài dùng mock nên không chứng minh chi phí hay chất lượng của LLM thật. Cloud chưa deploy vì chưa có tài khoản; trạng thái và lệnh hoàn tất ở `DEPLOYMENT.md`.
'''
    (ROOT / "BENCHMARK_REPORT.md").write_text(content, encoding="utf-8")

    mission = ROOT / "MISSION_ANSWERS.md"
    base = mission.read_text(encoding="utf-8").split("\n## Bằng chứng thực nghiệm tự động\n")[0]
    sizes = []
    for line in (REPORTS / "image_sizes.txt").read_text(encoding="utf-8-sig").splitlines():
        tags, size = line.rsplit(" ", 1)
        sizes.append((tags, int(size)))
    by_tag = {json.loads(tags)[0]: size for tags, size in sizes}
    dev, prod = by_tag["my-agent:develop"], by_tag["my-agent:advanced"]
    checklist = (REPORTS / "production_ready.txt").read_text(encoding="utf-8").split("📋 Checklist Deliverable")[-1]
    curl_output = (REPORTS / "security_curl.txt").read_text(encoding="utf-8-sig")
    evidence = f'''\n## Bằng chứng thực nghiệm tự động

Part 2: develop **{dev / 1024**2:.2f} MiB**, production **{prod / 1024**2:.2f} MiB**, giảm **{(dev - prod) / dev:.2%}**. Đơn vị MiB=bytes/1024², không nhầm với số làm tròn SI của docker images. Part 6: **{by_tag['day14-agent:final'] / 1024**2:.2f} MiB**. Nguồn: reports/image_sizes.txt và docker_images.txt.

Part 2 qua Nginx: reports/docker_stack_http.txt có GET /health 200 và POST /ask 200. Part 5: reports/stateless.txt ghi 10 messages được giữ qua nhiều instance.

### Part 4 — output curl -i thật

Token chỉ gửi trong request header, không in hoặc lưu vào output:

```text
{curl_output.strip()}
```

### Part 6 — Checklist Deliverable từ script gốc

```text
📋 Checklist Deliverable{checklist.rstrip()}
```
'''
    mission.write_text(base + evidence, encoding="utf-8")
    print("Generated BENCHMARK_REPORT.md and evidence section in MISSION_ANSWERS.md")


if __name__ == "__main__":
    main()
