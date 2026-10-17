# 現場商品預約與叫號

## 使用方式

1. 管理員登入購物網站，後台右上角選「現場預約管理」。
2. 先在商品管理新增／修改商品名稱、價格、說明及款式，再於預約管理勾選「現場製作」。
3. 開新場次，將管理區的 QR Code 提供給現場客人；同時只能有一個未結束場次。
4. 客人掃碼、LINE 登入並加入官方帳號，只填姓名，選商品、款式、顏色與數量後取號。
5. 管理員可修改「到號通知文字」，在任一有效預約按「通知到場」時，會自動儲存文字並使用同一份內容建立通知；也可先按「儲存通知文字」。通知保留場次、姓名與號碼。未報到前可再次通知；每次主動點擊會使用 LINE 訊息額度。客人頁每 5 秒更新，叫號進度只往前。
6. 預約成功即扣除可售庫存；有任一商品、款式或顏色不足，整筆不取號、不扣庫存。客人到場按「已報到／建立訂單」，承接原扣減，不再扣第二次；即使可售量已為 0，已保留的預約仍可報到。
7. 現場訂單會出現在既有訂單管理，標示場次、號碼，運費預設 0。後續取消、結算沿用既有流程。

預約成功即扣庫存，取消預約才釋放；價格與商品名稱保留取號時的快照。多項商品共用一張號碼。
同一 LINE 有等候中預約時不能再取號；到號或取消後才能重新取號。
客人可取消自己尚未報到的預約。管理員也可取消、將已到號者標記未到。標記未到會保留庫存，仍可通知、報到或取消。
暫停只停止新取號；結束場次會在畫面確認後取消所有未報到預約（包括未到場者）並釋放庫存，保留紀錄。已報到訂單不受影響，新場次從 001 開始。

## LINE 與上線前置

- LINE Login 與 Messaging API 必須使用同一 Provider，並在 Login channel 連結官方帳號。
- 使用既有 `LINE_LOGIN_CHANNEL_ID`、`LINE_LOGIN_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_LOGIN_REDIRECT_URI` 設定。金鑰只放環境變數，不進版控。
- Login callback 沿用 `/api/line/callback`。預約登入使用好友提示，檢查 `friendFlag` 後才允許取號。不要求現場客人完成會員註冊。
- 可設定 `RESERVATION_PUBLIC_BASE_URL=https://網站網域`（無尾端斜線與路徑）。未設定時，QR Code／通知查詢連結優先沿用 LINE callback 的網域，最後才採請求來源。
- 部署後應用手機掃實際 QR Code，確認 HTTPS 網域、LINE callback 及回到原場次。沒有正式網域、Provider 與好友設定的驗證，不能宣稱 LINE 端到端完成。
- 正常每筆有取號與到號兩次個人推播，使用官方帳號訊息額度。通知不會退回管理群組。
- `ACCEPTED` 僅代表 LINE API 已接受，不能確認送達或已讀。客人之後封鎖、關閉手機通知等因素仍可能收不到。
- 通知先記錄至資料庫，再送出；失敗或中斷會留在管理頁，管理者可重試。重試沿用相同 LINE retry key；超過 24 小時停止發送，請人工核對，避免失效的 retry key 導致重複通知。
- 正式更新已由張小龍授權；測試使用模擬 LINE，真人收訊由管理者操作確認。

官方文件：[好友連結設定](https://developers.line.biz/en/docs/line-login/link-a-bot/)、[推播限制](https://developers.line.biz/en/reference/messaging-api/nojs/#send-push-message)、[訊息額度](https://developers.line.biz/en/docs/messaging-api/pricing/)。

## API 與權限

| 介面 | 用途／限制 |
| --- | --- |
| `GET /reservations?scene=場次ID` | 客人與管理員共用頁面 |
| `GET /api/reservations/state?scene=場次ID` | 公開場次／叫號及可預約商品；包含目前瀏覽者自己的登入狀態與 CSRF token，禁止快取 |
| `GET /api/reservations/login?scene=場次ID` | 預約專用 OAuth，驗證後回到原場次 |
| `GET /api/reservations/mine` | 僅本人當場預約 |
| `POST /api/reservations` | LINE 驗證且好友狀態通過；提交場次、姓名、商品與 request_key |
| `POST /api/reservations/預約ID/cancel` | 僅本人尚未報到預約 |
| `POST /api/admin/reservations/tickets/預約ID/notify` | 管理員提交 session_id、message、request_key；儲存文字與建立通知同一交易。每次主動通知使用新 UUID，同次請求重送沿用；未更新的舊頁面未傳 message 時仍使用已儲存文字。 |
| `/api/admin/reservations/...` | 伺服器重新查驗資料庫角色，僅 admin；助教不可操作 |

所有新增寫入 API 要求 JSON 與 `X-Reservation-CSRF`。LINE ID 只採 OAuth 回呼後的簽章 session，不採用表單提供值。
公開資料不含他人姓名、LINE ID、預約明細或通知紀錄。

## 資料與驗證

- 新增 `reservation_sessions`、`reservations`、`reservation_notifications`。
- 商品新增 `onsite_enabled`，舊商品預設 false。既有商品儲存不會清除此設定。
- 訂單新增 `source`、`reservation_session_id`、`reservation_number`；舊訂單來源預設 web。
- 資料庫唯一限制保證單一有效場次、場次內號碼唯一、同人單一等候中預約與一票一單。
- 場次鎖定使取號、通知、取消、結束與報到依序完成。取號與既有購物、改單共用商品鎖與庫存檢查。
- `sales_logs.reservation_id/reservation_line` 保存預約扣減；報到轉綁 order_id。`reservations.stock_state` 區分 LEGACY、HELD、TRANSFERRED、RELEASED，取消及報到不會重複退扣。
- 仍有未報到預約（包括未到場）的商品不可直接刪除；取消現場勾選不影響既有預約。
- 到號紀錄依 (reservation_id,kind,request_key) 唯一，失敗重試沿用原 LINE retry key。舊 call-next 介面拒絕操作並提示重新整理。
- 預約測試在 `tests/test_reservations.py`，僅接受 `SOAR_TEST_DATABASE_URL` 指向 `127.0.0.1` 的獨立 `soar_validation` 資料庫。此測試會清空該測試資料庫的訂單、庫存及預約，嚴禁指向營運環境。
- 現有 `tests/test_soar_improvements.py`、圖片寬度與 Cloudinary 測試一併回歸。測試使用模擬 LINE，不通知真人。

本機驗收的測試伺服器、假登入入口、瀏覽器工具與 PostgreSQL 執行環境只放在工作副本，不屬於網站交付檔案。

## 庫存模式切換與回復

新資料表 `reservation_stock_mode` 初始為 MAINTENANCE；HTTP 寫入在 READY 前一律回覆維護中。
部署工具先唯讀盤點並保留舊版本，再停止所有舊工作程序；確認停止後才能補扣。以相同資料庫連線的 `ReservationService.migrate_stock(dry_run=True)` 預演（交易完整 rollback），再執行 `migrate_stock()`。
補扣只處理 WAITING、CALLED、NO_SHOW 的 LEGACY 預約，全批同一交易，檢查商品與款色及合計庫存；失敗整批 rollback 且維持維護。成功更新為 HELD 並將模式設為 READY，安全重跑不重扣。核對後才啟動新版本。
若回復舊版，先停止新版本全部工作程序，在維護期間執行 `rollback_stock()`，只解除未報到 HELD 扣減，保留已轉訂單扣減，再部署回復套件。回復套件以 b2ebd88 為基礎，通知 INSERT 使用 `ON CONFLICT DO NOTHING` 以相容多次通知的新索引，保留所有通知歷史。禁止直接帶著 HELD 資料或舊通知唯一限制的假設退回原程式。
