# YCM Outreach v0.2 — 修正工作單（交給開發 AI 執行）

來源：外部資安 / 到達率審查，依 2026-11-03 原始碼交付版（`ycm-mail-system/`）。
本文件是獨立工作單，不需要其他上下文。所有行號以該版原始碼為準，若已偏移請以語意定位。

## 執行規則（給 AI 的指令）

1. 依「優先順序」由 P0 → P1 → P2 執行，每完成一項就跑該項的驗收測試，全部綠燈才進下一項。
2. 不可修改既有測試讓它通過；新增測試可以，刪除或跳過測試不行。
3. 不可開啟真實外寄。`runtime.py` 的 loopback 限制與 `live_sending_enabled: false` 在本工作單完成前維持不變。
4. 每項修完請在本文件對應項目下方補一行 `DONE: <commit> <一句話說明>`，未完成就寫 `BLOCKED: <原因>`。
5. 不要重寫整個模組。以最小 diff 修正指定問題，保留現有狀態機與資料表命名。
6. PostgreSQL 相關改動必須同步更新 `migrations/` 內的 SQL。

---

## P0 — 接上 PostgreSQL 第一天就會當機的問題

### P0-1 每個 Celery task 都重建資料庫引擎並執行 create_all

- 位置：`ycm_mail/tasks.py:15-23`、`ycm_mail/runtime.py:11-16,24-33`、`ycm_mail/db.py:101-109`
- 問題：`send()` 與 `dispatch()` 每次執行都呼叫 `runtime.worker()` / `runtime.components()`，內部每次 `Database(url)` → `create_engine` + `metadata.create_all`。引擎從不 `dispose`，連線靠 GC 釋放。PostgreSQL 預設 100 連線，寄到幾百封就會 `FATAL: too many connections`，全部寄送停止。每封信還多出 18 張表的 catalog 查詢。
- 修正：
  - `runtime.py` 改為 process 級 singleton：module-level 快取 `_service`, `_signer`, `_worker`，第一次呼叫才建立。
  - Celery 使用 `worker_process_init` signal 在每個 prefork 子程序初始化一次，`worker_process_shutdown` 時 `engine.dispose()`。
  - `Database.__init__` 移除 `metadata.create_all`；改為獨立 `ycm_mail.db:migrate()` 函式，只在 `python -m ycm_mail migrate`、tests conftest、`scripts/dev_server.py` 呼叫。
  - `create_engine` 明確設定 `pool_size=5, max_overflow=5, pool_recycle=1800`。
- 驗收：
  - 新測試：連續呼叫 `runtime.worker()` 100 次，`Database` 建構子只被呼叫 1 次（用 monkeypatch 計數）。
  - 新測試：`tasks.send` 執行 50 次後，`engine.pool.checkedout() == 0` 且 `engine.pool.size()` 不超過 5。
  - 既有 `tests/` 全部通過。

### P0-2 已寄出的信被 recover() 標成 uncertain，accepted 結果遺失，下一步永遠不排程

- 位置：`ycm_mail/service.py:222`（lease_until = now + 60）、`service.py:236-244`（finish 檢查 state == sending）、`service.py:278-287`（recover）、`ycm_mail/worker.py:61-62`（stale_completion 直接丟棄 outcome）
- 問題：`authorize()` 給 60 秒 lease，SMTP timeout 10 秒，但 `finish()` 要排隊等 tenant 全域鎖。當 `recover()` 先取得鎖，sending → uncertain、enrollment → review，接著 `finish()` 回 False，provider 已 accepted 的事實被丟掉。Operator 看到 review 去手動重跑，同一個人收到兩封一樣的信。這是重複寄送與投訴率的直接來源。
- 修正：
  - `finish()`：若 `state == "uncertain"` 且 `lease_token` 相符（recover 時不要清掉 lease_token，改為另存 `recovered_at`），且 outcome 為 accepted，允許覆寫為 accepted、補 attempt 結果、照常排下一步，並把 enrollment 從 review 改回 active（僅當 reason == "uncertain"）。
  - `recover()` 對 sending 狀態只標 delivery = uncertain 並寫 attempt，**不改 enrollment 狀態**；enrollment → review 交由獨立 reconciliation 判斷（超過 `lease_until + 15 分鐘` 仍 uncertain 才轉 review）。
  - `Worker.run()` 在 transport 回傳後、呼叫 finish 前，先呼叫新的 `service.heartbeat(tenant, did, token, now)` 延長 lease 60 秒。
  - lease 長度改為可設定常數 `LEASE_SECONDS`，預設 = transport timeout × 3（30 秒）+ 60。
- 驗收：
  - 新測試：模擬 finish 在 recover 之後才執行（虛擬時間跳 61 秒），最終 delivery = accepted、enrollment = active、step 2 的 outbox 列存在、attempt outcome = accepted。
  - 新測試：recover 後 outcome 為 temporary 時，不得變成 accepted，且 attempt_count 不重複增加。
  - 既有 `tests/test_sequence_e2e.py` 的故障案例計數不變。

### P0-3 追蹤端點每次命中都取得 tenant 全域鎖，且無任何限流

- 位置：`ycm_mail/service.py:307-317`（track 走 `db.transaction(tenant)`）、`ycm_mail/api.py:301-317`、`ycm_mail/db.py:112-127`（tenant row FOR UPDATE）
- 問題：Gmail image proxy、Outlook SafeLinks、Proofpoint/Mimecast 掃描器會在信進收件匣前批次打 `/t/open`、`/t/click`。10,000 封信寄出後，每個命中都搶同一把 tenant 鎖，worker 的 claim/finish 跟著排隊，觸發 P0-2 的 recover 競爭。掃描器點擊也被當成真人 click 寫入報表。
- 修正：
  - `track()` 改為不取 tenant 鎖：使用單條 `INSERT ... ON CONFLICT (tenant_id, delivery_id, kind) DO UPDATE SET raw_count = raw_count + 1`（SQLite 用 `INSERT ... ON CONFLICT DO UPDATE`，SQLAlchemy 兩方言都支援）。`link_url` 的查詢改用不加鎖的 `engine.connect()`。
  - delivery 狀態檢查（必須 accepted）改成在同一條 SQL 的 `WHERE EXISTS` 子句，不另開交易。
  - 新增 `tracking` 欄位 `bot_count`：User-Agent 命中已知掃描器清單（GoogleImageProxy、Microsoft Office、Proofpoint、Mimecast、Barracuda、Symantec、Cisco、curl、python-requests）或寄出後 60 秒內的命中，計入 `bot_count` 而非 `raw_count`。dashboard 的 tracking 分別回傳 `human` 與 `bot`。
  - 加入記憶體內 token bucket（每 token 每分鐘 30 次、每 IP 每分鐘 300 次），超過回 204（pixel）/ 302（click 仍導向，但不計數）。不要回 429，避免信件客戶端顯示破圖。
- 驗收：
  - 新測試：5,000 次並發 `/t/open` 命中（threading）期間，`service.claim()` 平均延遲 < 50 ms（SQLite 下允許 < 200 ms）。
  - 新測試：UA 為 `GoogleImageProxy` 的命中進 `bot_count`，一般 UA 進 `raw_count`。
  - 新測試：同一 token 第 31 次命中於 60 秒內回 204 且計數不變。

---

## P1 — 10,000 Lead 同時跑會卡死的問題

### P1-1 所有寫入序列化在同一列 tenants row lock

- 位置：`ycm_mail/db.py:112-127`、所有呼叫 `self.db.transaction(tenant)` 的 service 方法
- 問題：claim、authorize、finish、enroll、record_event、recover、import 全部搶同一把鎖，單一 tenant 吞吐量 = 一次一個交易。
- 修正：
  - `Database.transaction(tenant)` 的 tenant row lock 改為 **預設不鎖**，只有傳入 `lock_tenant=True` 才鎖。只有 `create_mailbox`、`mailbox_state`、`stop_sequence`、`new_connection`、`revoke` 保留 `lock_tenant=True`。
  - `claim()` 改為單條原子 UPDATE：`UPDATE deliveries SET state='leased', lease_token=:t, lease_until=:u WHERE tenant_id=:tid AND id=:did AND state='queued' AND due_at<=:now RETURNING id`（SQLite 3.35+ 支援 RETURNING；若 rowcount == 0 回 None）。enrollment / mailbox 的 active 檢查移到 authorize。
  - `authorize()`、`finish()` 改為 `SELECT ... FROM deliveries WHERE ... FOR UPDATE`（PostgreSQL）鎖該 delivery row；SQLite 維持 BEGIN IMMEDIATE。
  - `enroll()` 的重複檢查依賴既有 `UniqueConstraint(tenant_id, sequence_id, lead_id)`，捕捉 IntegrityError 後再查既有 enrollment 回傳，不需 tenant 鎖。
- 驗收：
  - 新測試：PostgreSQL（testcontainers 或 CI service）下，4 個 worker thread 同時處理同一 tenant 1,000 筆 due delivery，無 deadlock、無重複 attempt、每筆恰好一個 accepted attempt，總耗時 < 單執行緒的 50%。
  - 既有測試全部通過。

### P1-2 配額退回造成每分鐘 thundering herd

- 位置：`ycm_mail/service.py:202-215`（超配額時把 due_at 推到 `times[-ceiling] + window`）、`ycm_mail/worker.py:69-83`（Dispatcher 每 tick 無視配額發佈 100 筆）
- 問題：10,000 筆同時 due，每分鐘實寄 50，其餘 9,950 筆每輪各做 claim + authorize-defer（兩次交易 + 一個 Redis 訊息），全部推到同一秒再來一次。每分鐘約 2 萬次空轉交易，持續 200 分鐘。
- 修正：
  - Dispatcher 改為**準入制**：每 tick 先計算每個 tenant / mailbox / sender domain 的剩餘分鐘配額（從 `quota_reservations` 用 `COUNT(*)` 算，不載入 list），只發佈配額內的筆數。配額用完的 delivery 不發佈，`next_publish_at` 直接推到 `下一分鐘 + random(0, 60)` 抖動。
  - `authorize()` 的退回路徑保留作為第二道防線，但 `due` 加 `random.uniform(0, 60)` 抖動，不要全部堆到同一秒。
  - `quota_reservations` 查詢改為 `SELECT COUNT(*), MIN(at)`，不再 `list(...)` 載入全部。
  - Dispatcher 跨 tenant 改為 round-robin：先 `SELECT DISTINCT tenant_id`，每個 tenant 取 `min(限額, 該 tenant 分鐘配額)`，不讓單一 tenant 吃滿 100 筆。
- 驗收：
  - 新測試：10,000 筆 enrollment、tenant_minute = 50，虛擬時間跑 10 分鐘，`claim()` 被呼叫次數 ≤ 600（50 × 10 加 20% 容忍），而非 ~100,000。
  - 新測試：兩個 tenant 各 5,000 筆，10 分鐘內每個 tenant 都有寄出，差距 < 10%。

### P1-3 Dispatcher recover() 每 5 秒全表掃描、quota 表永不清理

- 位置：`ycm_mail/worker.py:70-73`、`ycm_mail/db.py:53`（只有 `state, due_at` 索引）、`service.py:278`
- 修正：
  - 新增索引 `Index("delivery_lease", deliveries.c.state, deliveries.c.lease_until)`，同步寫入 `migrations/003_locks_and_indexes.postgresql.sql`。
  - `recover()` 改為跨 tenant 一次查詢 `WHERE state IN ('leased','sending') AND lease_until <= :now LIMIT 500`，不再逐 tenant 迴圈。
  - 新增 Celery Beat task `ycm.purge_quota`，每小時刪除 `quota_reservations.at < now - 86400 - 3600`。
- 驗收：既有測試通過；新測試確認 purge 後 24 小時內的列保留、25 小時前的列刪除。

### P1-4 名單匯入在單一鎖內逐列做三條語句

- 位置：`ycm_mail/service.py:60-85`
- 修正：先一次 `SELECT id, email FROM leads WHERE tenant_id=:t AND (id IN :ids OR email IN :emails)` 建 dict，記憶體內做 immutable-email 與 duplicate 檢查，再用 `INSERT ... ON CONFLICT (tenant_id, id) DO UPDATE` 批次寫入（每 500 列一個 executemany）。整批失敗仍要原子回滾（維持既有契約）。
- 驗收：10,000 列匯入在 SQLite 下 < 3 秒；既有 `duplicate_email` 與 `lead_email_is_immutable` 測試通過。

---

## P2 — 接真實 SMTP / API provider 之前的硬性門檻（到達率）

這一組沒做完，不得把 `live_sending_enabled` 改為 true。

### P2-1 追蹤連結與 API 共用同一網域

- 位置：`ycm_mail/worker.py:12-16,25-27,39-40`、`deploy/Caddyfile`
- 問題：pixel、click、unsubscribe 全掛在 `YCM_PUBLIC_URL`，跨所有 tenant 與寄件網域共用，且與 API/OAuth/MCP 同網域。任一 tenant 被投訴，所有人的 URL reputation 一起掉。
- 修正：
  - `mailboxes` 新增欄位 `tracking_host`（必填，HTTPS，例如 `track.客戶網域`）。`Renderer` 依 mailbox 組 URL，不再用全域 `public_url`。
  - Caddyfile 新增 wildcard / on-demand TLS 區塊，只把 `/t/*` 路由到 api，其他路徑在 tracking host 上回 404。
  - `create_mailbox` 驗證 `tracking_host` 的 CNAME 指向設定的 edge host（可先 stub，提供 `YCM_SKIP_DNS_CHECK` 給測試）。
- 驗收：新測試確認渲染出的 MIME 內所有 URL host == mailbox.tracking_host，且不含 public_url host。

### P2-2 沒有 reputation 熔斷器

- 位置：`ycm_mail/service.py:38-43`（Limits 只有每分鐘）、`service.py:245-266`（finish 的錯誤處理）
- 修正：
  - 新增 `ReputationGuard`（可放 `ycm_mail/reputation.py`）：以 mailbox 與 sender domain 為單位，滾動 24 小時統計 hard_bounce 率、complaint 率、4.7.x 次數。
  - 門檻（可設定）：bounce > 2%、complaint > 0.1%、或連續 3 次 4.7.x → `mailboxes.state = 'paused'`，該 mailbox 的 active enrollment → review，reason = `reputation_guard`。
  - `Limits` 新增 `mailbox_hour`、`recipient_domain_day`；`recipient_domain_day` 預設 = mailbox day_limit 的 50%。
  - 新信箱暖機：`mailboxes` 新增 `created_at`、`warmup_day_limit` 計算函式：第 1 天 20、每天 ×1.5，上限 = day_limit。authorize 取 `min(day_limit, warmup)`。
- 驗收：新測試：100 封中 3 封 hard_bounce 後 mailbox 自動 paused；暖機第 1 天第 21 封被 defer。

### P2-3 退避策略會把「被節流」升級成「被封鎖」

- 位置：`ycm_mail/service.py:255`（5 × 2^n 秒）、`ycm_mail/transport.py:19-33`（SMTP 不產生 retry_after）、`transport.py:27`（4xx 全視為 temporary）
- 修正：
  - 暫時性錯誤退避改為 `max(900, 300 × 4^(attempt-1))` 秒（15 分、1 小時、4 小時），上限 24 小時；最多 3 次不變。
  - `smtp_outcome()`：enhanced status 為 `4.7.x` 時回傳 `Outcome("throttled", status, retry_after=3600)`；`finish()` 對 `throttled` 的處理 = 該 mailbox 立即 paused + enrollment review，不重試。
  - `smtp_outcome()` 從回應文字解析 `retry after` / `try again in N` 的秒數填入 `retry_after`，解析不到給 900。
  - `transport.py:59` 的 `local_hostname` 改為可設定 `YCM_SMTP_HELO`，必須是 FQDN，預設從 mailbox 寄件網域推導。
- 驗收：新測試：回 `421 4.7.28` 後 mailbox paused、無第二次 attempt；回 `450 4.2.1` 後下一次 due 距今 ≥ 900 秒。

### P2-4 Follow-up 不在同一個 thread

- 位置：`ycm_mail/worker.py:30-32`
- 修正：
  - `deliveries` 新增 `message_id` 欄位，第一步寄出時保存。
  - 第 2 步以後：`In-Reply-To` 與 `References` = 第 1 步的 message_id，Subject 加前綴 `Re: `（若模板 subject 已以 Re: 開頭則不重複）。
  - 模板變數空值 fallback：`{{name}}` 空時用 `there` / 中文模板用 `您好`（由 sequence 新增 `fallback_name` 欄位決定），不得產生「您好 ，」。
  - `From` 加 display name：`mailboxes` 新增 `display_name`，渲染為 `"Display Name" <address>`。
- 驗收：新測試：step 2 的 MIME 含 `In-Reply-To: <step1 message id>`；lead name 為空時 body 不含 `, ` 開頭的殘缺問候。

### P2-5 「回覆就停止」沒有自動來源

- 位置：`ycm_mail/service.py:289-305`（record_event 只能由 API/webhook 觸發）
- 修正：
  - 新增 `ycm_mail/inbound.py`：IMAP IDLE 或 provider inbound webhook adapter，解析 `In-Reply-To` / `References` 對應 `deliveries.message_id`，自動產生 `reply` 事件；同時解析 DSN（RFC 3464）產生 `hard_bounce` / `soft_bounce`。
  - 新增硬性 gate：`authorize()` 對 `step > 1` 的 delivery，若該 mailbox 沒有設定 inbound 來源（`mailboxes.inbound_configured = 0`），直接 defer 並記錄 reason = `inbound_required`。
- 驗收：新測試：模擬收到 reply 後，同 enrollment 的 step 2 變 cancelled；mailbox 未設 inbound 時 step 2 不會進 sending。

### P2-6 名單沒有驗證就能 enroll

- 位置：`ycm_mail/service.py:136-146`（enroll 只檢查 email 非空）
- 修正：
  - `leads` 新增 `verified_at`、`verification` 欄位（`mx_ok` / `role_account` / `disposable` / `invalid`）。
  - 新增 `ycm.verify_leads` Celery task：MX 查詢（DNS）、role-account 前綴清單（info、sales、support、admin、noreply、no-reply、postmaster、abuse、marketing、hello、contact）、拋棄式網域清單（放 `schemas/disposable-domains.txt`）。
  - `enroll()` 拒絕 `verification != 'mx_ok'` 的 lead，錯誤碼 `verification_required`。
- 驗收：新測試：`info@` 開頭的 lead enroll 回 409 `verification_required`；MX 查詢失敗的網域不得 enroll。

### P2-7 入口限流與 demo tenant

- 位置：`ycm_mail/api.py:159-163,177-183`、`ycm_mail/oauth.py` token endpoint、`mcp/server.mjs:29-48`
- 修正：
  - `/api/session`、`/oauth/token`、`/oauth/register`：每 IP 每分鐘 10 次，超過回 429 並帶 `Retry-After`。
  - `/api/demo-session` 發出的 session scopes 固定為 `{ycm.read, ycm.write}`，不含 `ycm.send`。
  - MCP HTTP `/mcp` 每 token 每分鐘 60 次。
- 驗收：新測試：第 11 次登入嘗試回 429；demo session 呼叫 `/api/enrollments` 回 403 `insufficient_scope`。

---

## 不要做的事

- 不要把 SQLite 路徑改成 PostgreSQL-only；本機開發仍需 SQLite 可跑。
- 不要改 MCP 工具名稱、scope 名稱、API 路徑。
- 不要在 log 寫入 email 內容、收件人、token、provider 回應全文（維持既有原則）。
- 不要為了通過壓測調低測試筆數或改虛擬時間跳躍。

## 完成定義

1. P0 全部 DONE，`tests/` 全綠，新增 PostgreSQL + Redis 真容器 CI job（docker compose up `deploy/compose.yml` + `compose.worker.yml`）。
2. 壓測腳本 `scripts/loadtest.py`：10,000 筆 enrollment、SMTP sink 延遲 2 秒、同時 5,000 次 pixel 命中。通過條件：無 enrollment 進 review（reason = uncertain）、`stale_completion` 次數 = 0、claim-to-finish p99 < 10 秒、PostgreSQL 連線數峰值 < 30。
3. P2 全部 DONE 後才可以開 `live_sending_enabled` 的設計討論。

## 進度回報

| 項目 | 狀態 | Commit | 備註 |
|---|---|---|---|
| P0-1 | | | |
| P0-2 | | | |
| P0-3 | | | |
| P1-1 | | | |
| P1-2 | | | |
| P1-3 | | | |
| P1-4 | | | |
| P2-1 | | | |
| P2-2 | | | |
| P2-3 | | | |
| P2-4 | | | |
| P2-5 | | | |
| P2-6 | | | |
| P2-7 | | | |
