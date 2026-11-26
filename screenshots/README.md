# Bằng chứng hình ảnh

Ảnh local được chụp bằng Playwright từ chính các dịch vụ Docker đang chạy; không dùng ảnh tạo sinh hoặc ảnh trong tài liệu đề.

| File | Nội dung |
|---|---|
| grafana-dashboard.png | Dashboard metrics khi có traffic |
| jaeger-slow-trace.png | Waterfall trace chậm, mở span LLM |
| jaeger-error-trace.png | Trace lỗi upstream |
| prometheus-alert-firing.png | Hai alert firing trong lượt fault injection A+B |

Ba ảnh cloud `dashboard.png`, `running.png`, `test.png` đã chụp từ Render Live và Swagger UI của agent public. `test.png` thể hiện thiếu key trả 401; `../reports/public_deployment.json` ghi đủ bốn request 200/200/401/200, gồm request có key trả 200. Không có API key trong ảnh hoặc report.
