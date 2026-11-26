# Bằng chứng hình ảnh

Ảnh local được chụp bằng Playwright từ chính các dịch vụ Docker đang chạy; không dùng ảnh tạo sinh hoặc ảnh trong tài liệu đề.

| File | Nội dung |
|---|---|
| grafana-dashboard.png | Dashboard metrics khi có traffic |
| jaeger-slow-trace.png | Waterfall trace chậm, mở span LLM |
| jaeger-error-trace.png | Trace lỗi upstream |
| prometheus-alert-firing.png | Hai alert firing trong lượt fault injection A+B |

Ba ảnh cloud `dashboard.png`, `running.png`, `test.png` chưa có vì chưa tạo tài khoản/deploy. Xem `../DEPLOYMENT.md` để thực hiện, không thay các ảnh này bằng screenshot localhost.
