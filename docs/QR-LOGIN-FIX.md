# 掃碼登入修正（experimental.2）

使用者畫面與 NAS 端點均重現「掃碼輪詢返回無法解析的回應」。這個訊息本身不足以判定上游回傳的是過期、空白、HTML 或其他錯誤；修正前沒有記錄原始回應，亦不為診斷而公開登入資料。

程式檢查找到：前端每 3 秒建立輪詢、後端最長等待 8 秒，可能重疊；後端未先處理 HTTP 狀態、空回應或標準 JSON 前綴與空白。另外，原流程以 mijia SID 登入，卻直接把該 serviceToken 存入 micoapi 快取，沒有先交換並驗證 MiNA SID。

修正版：

- 前端待上一個請求完成後再排下一次，並忽略舊 QR 的遲到回應；QR 過期／拒絕時停止輪詢。
- 後端用鎖限制單一流程，保留 QR Cookie session；等待最多 25 秒，逾時視為等待。HTTP 204/408/504 與空回應不再當成 JSON 解析失敗。
- 處理 BOM、空白、`&&&START&&&` 前綴。非 JSON 錯誤僅顯示安全類別與 HTTP 狀態，絕不回傳原始 body／URL。
- QR 到期提示重新產生。429/上游暫時錯誤可重試；401/403/404/410 標為過期或拒絕，不冒稱特定原因。
- 掃碼取得 passport 憑證後，另以 passToken 執行 `login("micoapi")`，驗證安全參數與 serviceToken 均非空，才替換原登入資料；失敗保留原憑證，寫入失敗嘗試回復原檔。
- 搜尋結果不再誤導使用者「先去米家添加」，改說明 MiNA 清單與米家可見性不同。

本機已通過 28 項 Python 測試及 3 項前端排程情境，含 Cookie session 保留、並行限制、逾時、過期、非 JSON 隱私、正確 SID 交換、寫入回復與舊 QR 回應隔離。

參考比對：原始程式與 [mijia-api 掃碼流程](https://github.com/Do1e/mijia-api/blob/main/mijiaAPI/apis.py)、[ha_miband QR connector](https://github.com/lzghzr/ha_miband/blob/main/cloud.py)。這些為第三方實作，不能視為小米官方 API 支援承諾。

升級會使記憶體內舊 QR 失效。請重新整理面板，確認版本 `3.12.1-ai01zm-experimental.2`，重新產生 QR，再用米家 App 掃碼並於手機確認。沒有手機確認，就不能驗證完整的新帳號登入成功；MiNA 是否列出鬧鐘仍須另外驗證。
