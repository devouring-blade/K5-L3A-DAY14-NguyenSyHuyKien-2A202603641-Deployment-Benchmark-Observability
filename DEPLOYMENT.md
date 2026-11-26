# Deployment Information

## Trạng thái

**Chưa deploy cloud; chưa có public URL.** Chủ bài xác nhận chưa có tài khoản cloud. Không có ảnh dashboard/running/test cloud; không xem localhost là URL public. Source Part 6 đã đạt PASS 12/12 (43/43 checks), nhưng vẫn phải deploy và kiểm tra bốn request dưới đây để hoàn thành CP6.

## Cấu hình đã chuẩn bị

- Agent: `06-lab-complete/`, Docker multi-stage, user non-root, hai Uvicorn worker, cổng từ PORT.
- Railway: `06-lab-complete/railway.toml`, Dockerfile builder, `/health`, restart policy.
- Render: `06-lab-complete/render.yaml`, web service và Key Value, gói free; rootDir là `06-lab-complete`, REDIS_URL tham chiếu connectionString nội bộ, API key sinh bởi platform.
- Redis local dùng AOF volume. Render Key Value free chỉ giữ dữ liệu trong RAM và mất state khi datastore restart; phù hợp lab, không đủ để lưu sổ chi phí lâu dài trong production. [Nguồn Render](https://render.com/docs/free).

## Deploy bằng Render

1. Tạo/đăng nhập tài khoản [Render](https://dashboard.render.com/), kết nối đúng repo bài làm sau khi source đã được push.
2. New → Blueprint → chọn repo. Đặt Blueprint path là `06-lab-complete/render.yaml`.
3. Kiểm tra chỉ có hai resource free: day14-agent và day14-redis. Nếu nền tảng yêu cầu chuyển gói hoặc nhập thẻ, dừng và hỏi Lab Coach trước khi chấp nhận chi phí.
4. Tạo resources; đợi build/deploy và Redis sẵn sàng. Kiểm tra Environment đã có REDIS_URL và AGENT_API_KEY; giữ key trong dashboard, không dán vào repo/chat.
5. Lấy URL HTTPS platform cấp; chạy bốn kiểm tra bên dưới. `/ready` cần 200, `/health` 200 một mình chưa đủ.
6. Lưu ảnh thật vào `screenshots/dashboard.png`, `running.png`, `test.png`; che secret. Điền URL thực và kết quả vào tài liệu này cùng Part 3 của MISSION_ANSWERS.md.

Đường dẫn Dockerfile/context được tính theo rootDir khi cấu hình monorepo. [Nguồn Render về monorepo](https://render.com/docs/monorepo-support), [Blueprint reference](https://render.com/docs/blueprint-spec).

## Thay thế bằng Railway

```bash
cd 06-lab-complete
npm install -g @railway/cli
railway login
railway init
# Tạo Redis trong project; nối REDIS_URL của agent tới biến URL của Redis.
# Đặt AGENT_API_KEY bằng secret mới và ENVIRONMENT=production trong Variables.
railway up
railway domain
```

Không truyền key thật trong lệnh sẽ được ghi vào bằng chứng. Kiểm tra plan/credit trong dashboard trước khi tạo tài nguyên; không cam kết số credit cũ của tài liệu bài giảng còn áp dụng.

## Environment variables

| Biến | Giá trị/cách cấp |
|---|---|
| PORT | Do nền tảng cấp; Docker CMD đọc env |
| ENVIRONMENT | production |
| AGENT_API_KEY | Secret ngẫu nhiên, không lưu source |
| REDIS_URL | Connection string nội bộ từ Redis/Key Value |
| RATE_LIMIT_PER_MINUTE | 10 |
| DAILY_BUDGET_USD | 1 |
| MONTHLY_BUDGET_USD | 10 |
| LOG_LEVEL | INFO |

## Test public URL (Bash / WSL)

Đặt BASE là URL thực và nhập key vào env từ dashboard, không in ra màn hình:

```bash
read -r -p 'Public URL: ' BASE
read -r -s -p 'Agent API key: ' AGENT_API_KEY; echo
export BASE AGENT_API_KEY
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

Kỳ vọng theo thứ tự: 200, 200, 401, 200. Đây là **kỳ vọng**, chưa phải kết quả cloud đã đo. Sau khi đã chấm có thể xoá tài nguyên cloud theo RULES.md.
