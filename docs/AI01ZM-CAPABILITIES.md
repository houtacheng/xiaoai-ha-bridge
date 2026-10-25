# AI01ZM 能力與實測範圍

目標型號：AI01ZM / zimi.clock.myk01。語音控制 HA 仍未驗證。

`experimental.4` 新增此型號的獨立只讀狀態設定檔，從米家中國區辨識型號，透過已驗證的 xiaomiio SID 讀取 `get_volume` 與 `get_hourly_system`。離線紀錄不送 RPC；所有結果採白名單，不回傳 did、token、MAC 或 IP。這條路徑不會把米家 did 填成 MiNA deviceID，不包含改音量、改鬧鈴或播放音訊的命令。

面板「小米帳號」新增「偵測 AI01ZM 鬧鐘」，顯示在線狀態、音量與時制。一般搜尋在 MiNA 清單為空時也會執行這個只讀檢查。單獨的 API 為 `/api/clock/diagnostics`。

實機結果：米家兩筆型號紀錄，一筆在線、一筆離線；在線紀錄的音量與時制讀取成功。現有 passport 已經正常在乾淨會話登入 MiNA，master=0/1 清單仍為空。使用者確認米家 App 能顯示這台鬧鐘剛說的語句，因此對話資料可能使用另一條 App 路徑；未找到並驗證該路徑前，不啟動 HA 控制。

已核對公開 MIoT 型號索引：此型號 released v1 的規格包含裝置資訊、指示燈與音量，沒有對話讀取 action。這僅說明該規格沒有列出，不能推論米家 App 的私有對話路徑不存在。

來源：[MIoT 型號索引](https://miot-spec.org/miot-spec-v2/instances?status=all)、[此型號規格](https://miot-spec.org/miot-spec-v2/instance?type=urn:miot-spec-v2:device:clock:0000A026:zimi-myk01:1)、[python-miio 的 AI01ZM 驅動](https://github.com/rytilahti/python-miio/blob/master/miio/integrations/zimi/clock/alarmclock.py)。

35 項 Python 測試與 3 項前端排程情境通過。新增測試確認只對精確型號送出兩種已記載的讀取命令、跳過離線／缺少路由的紀錄，且錯誤與異常 payload 不會洩漏原始資料。

## experimental.5：米家鬧鐘專用對話路徑

已從小米官方 CDN 提供的 AI01ZM Android 插件 v107 靜態還原請求格式，未安裝或執行插件。該設備頁使用 xiaomiio `/v2/api/aivs`，代理 path `/api/aivs/device-events`，事件名稱 `DialogRecord.FetchByTime`，以米家 did 指定目標，payload 的 start 為毫秒時間、pagesize 為筆數。這是米家路徑，不是把米家 did 當作 MiNA deviceID。

已對帳號內唯一在線 AI01ZM 實機唯讀驗證：取得 4 筆紀錄，其中 2 筆角色為 `User`，一筆符合使用者自行提供截圖的語句；沒有把原始紀錄寫入檔案或輸出到聊天室。這確認歷史讀取可用，仍需測試啟動後的新語音及 HA 控制。

新增 `conversation_api: mijia_aivs`、獨立 `clock_did` 與預設為 true 的 `clock_bridge_dry_run`。只處理精確角色 `User` 的非空 content，忽略助手回覆、widget 與無效時間；啟動前、超過 30 秒、未來超過 30 秒的紀錄不執行。去重鍵使用獨立 aivs 命名空間，重啟不補執行舊語音。此模式不呼叫 MiNA 播報或播放器中斷。

面板「選取在線鬧鐘並測試新語音」只選唯一在線且型號相符的設備，進入 dry run。多台在線或指定目標離線時拒絕，不默選另一台。

實機 HA 驗證可設定 `clock_bridge_test_only: true` 及專用 `clock_test_entity`。這個模式只接受「打开桥接测试／关闭桥接测试」及繁體對應語句，且只能操作本次建立、ID 以 `input_boolean.xiaoai_ai01zm_bridge_test` 開頭的單一合法測試輔助開關，不會執行其餘日常規則。原有 7 條規則保留。完整測試通過後才將 dry run 與 test only 關閉，正式使用原有規則。

測試增為 42 項 Python 測試，涵蓋專用請求格式、角色過濾、時間順序、設備固定、dry run 無 HA 呼叫，以及僅操作測試開關。TTS 與鬧鈴管理沒有因此宣稱支援。
