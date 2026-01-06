# Ghost CMS 設定檢核表

> 用於 Daily Deep Brief 自動化發佈系統

## 前置確認

- [ ] Ghost 版本確認: ______ (需 v5.0+)
- [ ] Admin URL: `https://rocket-screener.ghost.io/ghost`
- [ ] API URL: `https://rocket-screener.ghost.io`

---

## Step 1: 啟用 Newsletter Sending

**路徑**: Settings → Membership → Email newsletter → Newsletter sending

- [ ] Newsletter sending 已開啟

---

## Step 2: Email Delivery 設定

### Ghost(Pro) 用戶
- [ ] 確認 Ghost 代管 email delivery 正常

### Self-hosted 用戶
- [ ] Mailgun API keys 已設定（用於 bulk newsletters）
- [ ] Mail config 已設定（用於 auth emails）

---

## Step 3: 建立 Newsletters

**路徑**: Settings → Membership → Newsletters → Add newsletter

### 3.1 正式 Newsletter
- [ ] 已建立
- Name: `Daily Brief`
- Slug: `daily-brief`
- [ ] **記錄**: `NEWSLETTER_SLUG_PROD=daily-brief`

### 3.2 測試 Newsletter
- [ ] 已建立
- Name: `Daily Brief (Test)`
- Slug: `daily-brief-test`
- [ ] 既有會員 **未** opt-in
- [ ] **記錄**: `NEWSLETTER_SLUG_TEST=daily-brief-test`

---

## Step 4: Newsletter 寄件資訊設定

對每個 newsletter 確認：

### Daily Brief (正式)
- [ ] From name: ______________________
- [ ] Reply-to: ______________________

### Daily Brief Test (測試)
- [ ] From name: ______________________
- [ ] Reply-to: ______________________

---

## Step 5: 建立測試分眾 (Internal Segment)

**路徑**: Members → 找到自己的 email → 加上 label

- [ ] 已給自己的帳號加上 `internal` label
- [ ] **記錄**: `EMAIL_SEGMENT_TEST=label:internal`

### 其他常用 segment 參考:
- `status:free` - 免費會員
- `status:-free` - 付費會員
- `all` - 全部會員（危險！）

---

## Step 6: 建立 Tag Taxonomy

**路徑**: Settings → Tags

### 6.1 Base Tags (每篇必加)
- [ ] `us-stocks`
- [ ] `daily-brief`

### 6.2 Theme Tags
- [ ] `theme-crypto`
- [ ] `theme-quantum`
- [ ] `theme-robotics`
- [ ] `theme-nuclear`
- [ ] `theme-ai-infra`
- [ ] `theme-ai-semis`
- [ ] `theme-grid-power`
- [ ] `theme-drones`
- [ ] `theme-ai-data`
- [ ] `theme-ai-security`
- [ ] `theme-space`
- [ ] `theme-ai-networking`
- [ ] `theme-ai-cloud`

### 6.3 Internal Tags (以 # 開頭)
- [ ] `#autogen` - 自動產生的文章
- [ ] `#edition-premarket`
- [ ] `#edition-postclose`
- [ ] `#pipeline-v1`

---

## Step 7: 建立 Custom Integration

**路徑**: Settings → Integrations → Add custom integration

- [ ] Integration 名稱: `Daily Deep Brief Pipeline`
- [ ] 已複製 Admin API Key
- [ ] **記錄**: `GHOST_ADMIN_API_KEY=______:______`

> 格式: `{id}:{secret}`

---

## Step 8: 程式端環境變數

確認以下變數已設定在 `.env`:

```bash
# Ghost CMS 設定
GHOST_API_URL=https://rocket-screener.ghost.io
GHOST_ADMIN_API_KEY=695a061f5008b80001531e6a:5c441b3bbe3f1e8b79709efa447f79240ca3c5a83bdebd6fa2be1c325d5b085c
GHOST_ACCEPT_VERSION=v5.0

# Newsletter 設定
GHOST_NEWSLETTER_SLUG=daily-brief
GHOST_NEWSLETTER_SLUG_TEST=daily-brief-test

# 安全 Allowlist（強制）
GHOST_NEWSLETTER_ALLOWLIST=daily-brief-test
GHOST_SEGMENT_ALLOWLIST=label:internal

# Segment 設定
GHOST_SEGMENT_TEST=label:internal
GHOST_SEGMENT_FREE=status:free
GHOST_SEGMENT_PAID=status:-free
```

---

## Step 9: 驗證測試

### 9.1 API 連線測試
```bash
make ghost-smoke-test
```
- [ ] 成功建立 Draft
- [ ] Ghost 後台可見該 Draft

### 9.2 Draft 模式測試
```bash
make ghost-draft
```
- [ ] 使用 pipeline 產出建立 Draft
- [ ] 內容格式正確

### 9.3 Publish (不寄信) 測試
```bash
make ghost-publish
```
- [ ] 文章成功發佈到網站
- [ ] 未寄出 email

### 9.4 Newsletter (內部) 測試
```bash
make ghost-send
# 輸入: daily-brief-test
# 輸入: label:internal
```
- [ ] 只有自己收到 email
- [ ] Email 格式正確
- [ ] Ghost 後台 email 狀態非 failed

---

## 上線順序建議

| 階段 | 時間 | 模式 | 說明 |
|------|------|------|------|
| 1 | Day 1-3 | Draft only | 每天人工檢查 1 分鐘 |
| 2 | Day 4-7 | Publish (no email) | 確認網站展示/SEO/tag |
| 3 | Week 2 | Newsletter (internal) | 只寄給自己測試 |
| 4 | Week 3+ | Newsletter (prod) | 正式對外發送 |

---

## 故障排除

### Email 發送失敗
1. 到 Ghost 後台檢查 post 的 email 狀態
2. 如果 failed，將 post revert 回 draft
3. 修正問題後 republish 觸發重送

### 格式在 Email 崩壞
- 表格欄位不要超過 6-8 欄
- 避免過寬表格
- 提供 2-6 條 takeaways

### 分類越來越亂
- 確保每篇都有 base tags
- 使用 internal tags 追蹤來源
- 定期清理未使用的 tags

---

## 關鍵值快速參考

| 變數 | 值 | 用途 |
|------|-----|------|
| `GHOST_API_URL` | `https://rocket-screener.ghost.io` | API 根 URL |
| `GHOST_ADMIN_API_KEY` | (已設定) | Admin API 認證 |
| `NEWSLETTER_SLUG_TEST` | `daily-brief-test` | 測試用 newsletter |
| `EMAIL_SEGMENT_TEST` | `label:internal` | 只寄給自己 |

---

*最後更新: 2026-01-05*
