# Benchmark & Observability Report — Day 14

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

| Concurrency | RPS | p50 ms | p95 ms | p99 ms | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.65 | 206.9 | 381.7 | 1713.4 | 0.33% | PASS |
| 10 | 40.23 | 206.6 | 288.5 | 1671.1 | 0.33% | PASS |
| 50 | 27.08 | 746.8 | 5704.8 | 6069.5 | 1.67% | FAIL |
| 100 | 62.4 | 792.3 | 3982.9 | 4317.5 | 1.33% | FAIL |

RPS không tăng tuyến tính mãi: concurrency cho phép chồng thời gian chờ I/O nhưng thêm scheduling, HTTP connection contention và queueing. Khi đạt khả năng xử lý của một process/CPU, p95/p99 tăng. Không gọi một lần test FAIL là PASS chỉ vì accuracy tốt.

Mức 50 và 100 được chạy ở hai thời điểm khác nhau trên máy dùng chung tài nguyên với Docker; RPS của mức 100 cao hơn mức 50 không chứng minh 100 là cấu hình tối ưu. Cần lặp nhiều lượt trong môi trường cô lập để suy ra đường cong capacity đáng tin cậy.

### 2.2 Tail latency

Ba lần chạy cùng 300 request/concurrency 20; mỗi lần restart v2 với slow rate tương ứng.

| MOCK_SLOW_RATE | avg ms | p95 ms | p99 ms |
|---|---|---|---|
| 0 | 227.3 | 451.5 | 501.3 |
| 0.03 | 259.0 | 285.7 | 1698.6 |
| 0.1 | 330.1 | 1695.7 | 1725.2 |

p99 rất nhạy với nhóm request chậm; ở slow rate 10%, p95 cũng lọt vào nhóm được cộng 1500ms. Average trộn đa số nhanh với thiểu số chậm, dễ che trải nghiệm ở đuôi phân phối. Mỗi mẫu chỉ 300 request và fault ngẫu nhiên, nên không suy diễn thành kết quả ổn định của production.

Lần đo đầu khi Docker còn build/tải image được giữ ở `reports/initial_busy/`. Bảng chính dùng lần đo lại: source và log của server đặt trên filesystem Linux, tránh Windows bind-mount I/O chi phối phép đo. Một số load vẫn đồng thời với stack giám sát trên cùng máy; đây là giới hạn kiểm soát tài nguyên của thí nghiệm.

## 3. Benchmark chất lượng

| Chỉ số | v1 | v2 ban đầu | v2 sau sửa KB |
|---|---|---|---|
| Accuracy | 1/23 (4.35%) | 21/23 (91.30%) | 23/23 (100.00%) |
| Avg tokens/câu | 56.3 | 109.0 | 118.4 |
| Tổng cost USD | 0.000393 | 0.000759 | 0.000832 |
| Cost/câu đúng USD | 0.00039255 | 3.616e-05 | 3.616e-05 |
| p95 ms | 264.7 | 466.0 | 258.2 |
| Quality gate | FAIL | PASS | PASS |

| ID | Keyword thiếu | Thay đổi KB |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Thêm mô tả JWT: token, chữ ký, hết hạn |
| scaling-03 | cpu, memory, custom metrics | Thêm mô tả HPA: CPU, memory, custom metrics |

Đã chép cùng KB sửa sang develop và production. v2 tăng token do prompt có retrieval nhưng cải thiện cost/câu đúng. KB bổ sung dài hơn làm chi phí v2 sau sửa tăng; latency giữa các lần còn chịu ảnh hưởng tải máy, không quy toàn bộ chênh lệch cho KB.

Quality gate cuối yêu cầu accuracy 1.0 và không regression so với eval_v2.json. Thử v1 với baseline v2 trả exit code 1; xem `reports/eval_v1_regression.json`. Workflow `.github/workflows/quality-gate.yml` chạy gate trên push/PR và upload report. Cần chọn job này làm required status check trong branch protection để GitHub thực sự chặn merge. Workflow đã tạo, chưa xác nhận chạy trên GitHub.

## 4. Observability

### 4.1 Bằng chứng giao diện

- [grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

Prometheus pull /metrics mỗi 5s, DNS discovery tìm từng agent; Grafana query Prometheus. Nginx chặn /metrics public (404) nhưng agent nội bộ vẫn cho scrape. GET /health và /ready qua Nginx trả 200: `reports/observability_http.json`.

Lượt kiểm soát chạy Locust bằng `docker compose run --rm --no-deps locust ...` vì stack đã khởi động. Nếu thiếu --no-deps, Compose có thể reconcile agent về env/replicas mặc định, phá phép đo scaling hoặc fault injection. Các lượt trước khi phát hiện lỗi được giữ riêng trong `reports/initial_busy/benchmark-results/`, không dùng làm bằng chứng số instance cố định.

Golden Signals: traffic, error rate, latency, in-flight requests. Dùng route template thay URL thực để tránh cardinality theo ID. Không gắn câu hỏi/user_id/request_id làm metric label. Metrics cho biết triệu chứng; trace tách thời gian retrieval/LLM; JSON log liên kết bằng trace_id.

Percentile Prometheus được ước lượng từ histogram buckets; load_test.py đo phía client và tính percentile trên các response 200. Điểm đo và tập mẫu khác nhau nên không yêu cầu hai con số trùng nhau.

### 4.2 Chaos và alerts

| Thí nghiệm | Thay đổi | Alert kiểm tra | Thời gian đã đo |
|---|---|---|---|
| AB | MOCK_ERROR_RATE=0.2 + MOCK_SLOW_RATE=0.3 | AgentHighErrorRate / AgentHighLatencyP95 | AgentHighErrorRate: 86.43s; AgentHighLatencyP95: 146.7s |
| C | LLM_MODEL=mock-llm-large | LLMCostBurnRateHigh | LLMCostBurnRateHigh: 153.87s |
| D | docker pause một instance | AgentInstanceDown | 40.68s |

A và B được bật đồng thời trên cùng lượt traffic để chụp hai alert firing; không kết luận tác động độc lập từ lượt kết hợp này. Thời gian tính từ lúc bắt đầu áp cấu hình (gồm recreate/startup), lấy snapshot API mỗi 5s. C có panel cost USD/giờ; D có Instances up và scrape up. Rule `for` cần điều kiện đúng liên tục và thêm độ trễ scrape/evaluation.

Pause giữ container trong DNS nên Prometheus thấy target nhưng up=0; stop có thể xoá target khỏi discovery. Lỗi 504 sinh ở Nginx không nhất thiết được agent đếm vào metric HTTP, cần metric ở tầng LB hoặc synthetic probe để thấy đủ lỗi người dùng.

Thí nghiệm E: đổi AGENT_VERSION=v1 làm giảm chất lượng trong khi request vẫn trả 200. Phát hiện bằng golden eval, canary/synthetic câu hỏi và theo dõi version/retrieval; metric hạ tầng không chứng minh câu trả lời đúng. Bằng chứng nếu đã chạy nằm trong `reports/chaos_E.json`, `eval_production_v1.json`; alert cũ còn firing sau fault trước không được coi là do v1 gây ra.

Kết quả E đã đo: v1 đúng 1/23 (4.35%); quality gate FAIL, 22 câu regression so với v2 đã sửa.

Alert rule tests gốc đã chạy bằng promtool: `reports/alert_rules_test.txt` báo SUCCESS. Jaeger image 2.23 chạy API v3; raw OTLP ở `reports/traces_*_otlp.jsonl`, file JSON chuẩn hoá chỉ đổi đơn vị ns sang µs để tính thời gian, không sinh span mới.

### 4.3 Debug trace

Trace ID: `ff180657e3a7cea74d451e1de0d37688`. Tổng thời gian: **1720.102 ms**.
Span LLM: `chat mock-llm-small`, **1694.860 ms**, chiếm **98.53%** tổng thời gian.
Các span cha bao gồm thời gian con, không cộng chồng các duration. LLM là bước cần kiểm tra trước; retrieval và overhead được tách ở waterfall.

Log có cùng trace_id (nguồn `reports/agent_logs_*.txt`):

```json
{"ts": "2026-11-26T00:49:19.952413+00:00", "level": "INFO", "service": "observable-agent", "instance": "678208683a55", "event": "llm_call", "trace_id": "ff180657e3a7cea74d451e1de0d37688", "span_id": "5b46a41224bb6569", "request_id": "77dcbe2d5e25", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 76, "output_tokens": 39, "cost_usd": 3.5e-05, "llm_ms": 1693.8}
```

Trace lỗi: `144867f013eaec48e4ef4db1fd76a31d`. Ảnh `jaeger-error-trace.png` hiển thị HTTP 503,
span LLM có `error.type=upstream_unavailable` và event `exception`.
Log lỗi có cùng trace_id:

```json
{"ts": "2026-11-26T00:49:20.074814+00:00", "level": "INFO", "service": "observable-agent", "instance": "1d7fe628fdba", "event": "llm_error", "trace_id": "144867f013eaec48e4ef4db1fd76a31d", "span_id": "d0aac493f40bddcc", "request_id": "71b6debf61f3", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```


## 5. Scaling bằng Locust headless

Cùng 100 users, ramp 10/s, cấu hình -t 2m. Bảng lấy hàng Aggregated (gồm /ask và /health), không chỉ request thành công. Thời gian kết thúc thực có thể dài hơn 2 phút vì request đang chờ; xem stats history và output Locust.

| Instances | RPS | p50 ms | p95 ms | p99 ms | Failures |
|---|---|---|---|---|---|
| 1 | 48.658 | 490 | 2200 | 3300 | 43/5756 (0.75%) |
| 3 | 62.057 | 210 | 910 | 1800 | 61/7352 (0.83%) |

RPS đổi từ 48.658 lên 62.057; p95 đổi từ 2200ms sang 910ms. Scale cải thiện p95 trong lượt đo này. Cần đọc cùng failures.csv và trace, vì response lỗi tại proxy cũng nằm trong bảng tổng. Nếu LLM span vẫn chiếm phần lớn thời gian thì thêm instance chủ yếu giảm queueing, không giảm latency upstream. Nếu có nhiều 502/504 hoặc duration vượt xa latency mock, kiểm tra CPU quota, throttling và kết nối Nginx; không quy mọi chậm trễ cho LLM hoặc dùng response lỗi nhanh để tuyên bố hệ thống nhanh hơn.

## 6. Bài học và trạng thái nộp

1. Đo p95/p99 cùng error rate và throughput; trung bình hoặc RPS riêng lẻ có thể gây hiểu sai.
2. Chất lượng, tốc độ và chi phí là ba trục khác nhau; cost/câu đúng hữu ích hơn cost/câu.
3. Correlate metric → trace → log giúp phân biệt lỗi upstream, queueing và lỗi tại proxy.

Khi triển khai thật: thêm metric ở Nginx, hàng đợi/timeouts, CPU throttling, Redis availability, budget remaining và canary chất lượng. Bài dùng mock nên không chứng minh chi phí hay chất lượng của LLM thật. Cloud chưa deploy vì chưa có tài khoản; trạng thái và lệnh hoàn tất ở `DEPLOYMENT.md`.
