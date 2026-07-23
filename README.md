# UX-PRINT // 3D & UV 列印運動風社團銷售網站 (與 LINE 整合)

## 📌 專案簡介
本專案為社團專屬的運動極限風格銷售網站，專門展示與銷售 **3D 列印套件**（如 TPU 避震件、Nylon-CF 碳纖維魂板、PLA-PRO 結構件）與 **UV 炫彩作品**（如立體浮雕貼紙、夜光/光澤標章、車貼彩繪）。

---

## 🌟 核心功能說明

### 1. 📢 運動風格社團公佈欄 (Club Bulletin Board)
- **即時賽事與活動公告**：支援置頂公告、標籤分類（賽事公告、資材更新、系統更新）。
- **LINE 訊息同步廣播**：參考 `第一金人壽 BR` 的 `line_service.py` 整合概念，發布公告時可一鍵推播至 LINE 官方社群與 Bot。

### 2. 🛒 3D & UV 列印商品分類大廳 (Product Catalog)
- **多重篩選機制**：
  - 分類：全部商品、3D列印套件、UV炫彩作品、社團限定。
  - 材質等級 (Material Grade)：`TPU_95A`, `PLA_PRO`, `NYLON_CF`, `UV_RESIN`。
- **UV 揭露效果 (UV Overlay)**：懸停於 UV 作品時顯示隱藏立體印製層細節。
- **購物車與結帳抽屜 (Cart Drawer)**：支援數量動態調整與總額實時計算。

### 3. 💬 LINE 服務中心 (LINE Service Integration)
- **LINE Login 快速登入模組**：模擬存取用戶 LINE Profile（暱稱、大頭貼、User ID）。
- **LINE 群組推播結帳**：完成購物車結帳時，自動產生將訂單與規格發送至 LINE 管理團隊的 Push Notification。
- **LINE 訊息訂閱與社群 QR Code**：方便成員一鍵開啟 LINE 進行客服與加入社交流群。

---

## 🚀 視覺設計規範 (Design Aesthetics)
- **主配色**：極致暗色調 (`#131313`) + 螢光黃綠 Cyber Lime (`#c3f400`) + 運動橘 (`#fe6b00`) + LINE 經典綠 (`#06C755`)
- **字型組合**：Anybody (極粗斜體 Headline) + JetBrains Mono (Tech Specs) + Noto Sans TC (中文內文)
- **特效細節**：45度斜線切割、掃描線 scanline 動畫、螢光 Glow 霓虹光澤、點陣網格 background。
