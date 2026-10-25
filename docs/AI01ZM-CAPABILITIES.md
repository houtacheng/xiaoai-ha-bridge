# AI01ZM 能力與實測範圍

目標型號：AI01ZM / zimi.clock.myk01。語音控制 HA 仍未驗證。

`experimental.4` 新增此型號的獨立只讀狀態設定檔，從米家中國區辨識型號，透過已驗證的 xiaomiio SID 讀取 `get_volume` 與 `get_hourly_system`。離線紀錄不送 RPC；所有結果採白名單，不回傳 did、token、MAC 或 IP。這條路徑不會把米家 did 填成 MiNA deviceID，不包含改音量、改鬧鈴或播放音訊的命令。

面板「小米帳號」新增「偵測 AI01ZM 鬧鐘」，顯示在線狀態、音量與時制。一般搜尋在 MiNA 清單為空時也會執行這個只讀檢查。單獨的 API 為 `/api/clock/diagnostics`。

實機結果：米家兩筆型號紀錄，一筆在線、一筆離線；在線紀錄的音量與時制讀取成功。現有 passport 已經正常在乾淨會話登入 MiNA，master=0/1 清單仍為空。使用者確認米家 App 能顯示這台鬧鐘剛說的語句，因此對話資料可能使用另一條 App 路徑；未找到並驗證該路徑前，不啟動 HA 控制。

已核對公開 MIoT 型號索引：此型號 released v1 的規格包含裝置資訊、指示燈與音量，沒有對話讀取 action。這僅說明該規格沒有列出，不能推論米家 App 的私有對話路徑不存在。

來源：[MIoT 型號索引](https://miot-spec.org/miot-spec-v2/instances?status=all)、[此型號規格](https://miot-spec.org/miot-spec-v2/instance?type=urn:miot-spec-v2:device:clock:0000A026:zimi-myk01:1)、[python-miio 的 AI01ZM 驅動](https://github.com/rytilahti/python-miio/blob/master/miio/integrations/zimi/clock/alarmclock.py)。

35 項 Python 測試與 3 項前端排程情境通過。新增測試確認只對精確型號送出兩種已記載的讀取命令、跳過離線／缺少路由的紀錄，且錯誤與異常 payload 不會洩漏原始資料。
