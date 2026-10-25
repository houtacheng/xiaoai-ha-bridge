# AI01ZM / zimi.clock.myk01 實驗分支與 QNAP 實測指南

狀態：**尚未實機驗證，不能宣稱已支援。**

本分支完成可測試的搜尋、選擇、對話讀取及診斷路徑；沒有小米帳號憑證、實體鬧鐘或 QNAP 可供此開發環境驗證。AI01ZM 與 zimi.clock.myk01 是本次使用者提供的目標標識；不能直接把其中任何一個當成 MiNA 回傳的 `hardware`。

## 已確認的原始碼事實

基準：chenshuhe/xiaoai-ha-bridge 的 `015c6ece402f4fec6e7c75ac0d6d12a2b484d500`（v3.12.1）。本分支固定 `miservice_fork==2.9.3`，以對應所檢查的 API。

| 路徑 | 驗證到的行為與限制 |
| --- | --- |
| MiNA 搜尋 | `sid=micoapi`，`https://api2.mina.mi.com/admin/v2/device_list?master=0`；原版只呼叫預設清單。`master=1` 是套件接受的另一個查詢值，並不保證其語義或涵蓋鬧鐘。 |
| MiNA 對話 | `/remote/ubus`，`deviceId=<MiNA deviceID>`、`method=nlp_result_get`、`path=mibrain`。套件原有 helper 對 ubus 拒絕回傳空列表，且假設只有一個 answer。 |
| HTTP 對話 | `userprofile.mina.mi.com/device_profile/v2/conversation`，`source=dialogu`、`hardware`、毫秒 timestamp、limit=2；使用 micoapi serviceToken 與所選 MiNA deviceID。 |
| 米家搜尋 | `sid=xiaomiio`，`/home/device_list`；清單內 `did`、`model`、裝置 token 與 MiNA 不是同一種識別資料。只能確認米家帳號及區域可見性。 |

原版指定設備找不到時會改選第一台，輪詢又可能繼續使用原先填寫的 did，造成硬體與識別碼不一致；TTS 測試也會選第一台。現在三條路徑使用同一個明確的設備解析規則。多台設備時必須選定，指定 ID 找不到就停止，不改投其他設備。

來源：[基準 bridge.py](https://github.com/chenshuhe/xiaoai-ha-bridge/blob/015c6ece402f4fec6e7c75ac0d6d12a2b484d500/bridge.py)、[MiService 專案](https://github.com/yihong0618/MiService)、[miservice_fork 2.9.3](https://pypi.org/project/miservice_fork/2.9.3/)。實際 API 檢查以已安裝 2.9.3 的 `minaservice.py`、`miaccount.py`、`miioservice.py` 為準；上游網站的現行主分支可能已不同。

## 實作範圍

- `discovery_all: true` 時合併 MiNA master=0 與 master=1，依真正的 deviceID 去重。
- 設定 `conversation_api: mina` 或 `http`，可逐一測試兩種 API；`auto` 保留 M01 走 MiNA、其他型號走 HTTP 的既有規則，沒有新增未經驗證的鬧鐘硬體映射。
- MiNA 讀取檢查 gateway 與 ubus code，支援多個 answer；HTTP 支援 data 為 JSON 字串或物件，拒絕業務錯誤與異常結構。
- 新啟動時略過啟動前的雲端紀錄；每批依時間排序並沿用持久化去重，避免重播舊指令。停機期間的指令不補執行。
- 診斷報告使用每次執行不同的設備指紋，只含搜尋摘要、錯誤類別、紀錄數與近 120 秒紀錄數，不含帳號、名稱、token、原始 ID 或對話。`--local-ids` 是刻意開啟的本機例外，不能分享其輸出。
- 日誌 handler 過濾 miservice 原始認證／請求日誌、已知憑證與常見 credential 欄位，例外僅記類別；設定 API 額外遮罩 cookie_text，設備 API 採欄位白名單。新檔預設只讓建立者讀寫。舊檔權限需部署時另行收緊。
- 2.9.3 的 `_serviceLogin` 使用 `ssl=False`；此分支的帳號 adapter 與 QR 登入路徑改為驗證 TLS 憑證，且不記錄登入回應。不要為了解決 NAS 憑證問題而關閉驗證。
- TTS API 成功只表示雲端接受請求，仍要用耳朵確認。實驗分支停用網頁一鍵覆蓋更新，避免漏更新新模組。

這些修改提供的是兼容性實驗入口；如果雲端沒有鬧鐘的 MiNA 路由或不提供語音紀錄，單純新增型號名稱不能解決。沒有實作猜測的 MIoT action、韌體修改或本地攔截協定。

## QNAP Container Station 3 部署

QNAP 官方說明支援以 Docker Compose YAML 建立 Application：[Container Station 3 指南](https://www.qnap.com/en/how-to/tutorial/article/how-to-use-container-station-3)。以下以 NAS 上本機建置的映像部署，沒有預先發布的 GHCR 映像。

1. 在 File Station 建立共享資料夾下的 `Container/xiaoai-ha-bridge`，確認實際路徑。本例用 `/share/Container/xiaoai-ha-bridge`；若不同，修改所有命令及 YAML 掛載路徑。先備份舊實例的 config，在 Container Station 停止舊容器，避免兩個橋接器重複執行。
2. 透過 NAS SSH 取得原始碼（或解壓附帶的原始碼 ZIP 到此資料夾）。確認 NAS 裝有 Docker、Compose 與可用的 Python 3.12 基底映像；本機建置會依 NAS 架構拉取基底，不是跨架構建置。舊款 ARM 或缺少套件 wheel 的 NAS 可能建置失敗，尚未驗證。

```sh
cd /share/Container
git clone --branch experimental/ai01zm-diagnostics https://github.com/houtacheng/xiaoai-ha-bridge.git
cd xiaoai-ha-bridge
mkdir -p config logs
cp config/config.yaml.example config/config.yaml
chmod 700 config logs
chmod 600 config/config.yaml
```

若已有 repo 或設定檔，跳過 clone/cp，勿覆蓋原有憑證；改切換實驗分支後使用備份的設定。

3. 啟動前在本機編輯 `config/config.yaml`：清空範例的 Xiaomi username/password、cookie_text、HA token 與 AI key。設定 `ai_mode: false`、`intent_rules: []`、`event_monitors: []`，先只做診斷；把 `web_auth.enabled` 設為 true 並設定自選管理密碼。`xiaomi.hardware` 先留空，`discovery_all: true`，`tts_reply: false`、`interrupt_native_reply: false`。選擇對話 API 前先搜尋設備。範例中的 L06A 不是鬧鐘的已知硬體。
4. 在 NAS 建置：

```sh
docker build -t xiaoai-ha-bridge:ai01zm-experimental .
```

5. Container Station → Applications → Create，名稱例如 `xiaoai-ha-bridge-ai01zm`，貼入 `compose.qnap.yaml`，調整掛載路徑後驗證並建立。它使用剛建置的本機映像。時區已設 `America/New_York`，不必改成中國時間。若 47521 被舊實例占用，先停舊實例或改主機端口。
6. 只從可信任的區域網路開啟 `http://NAS-IP:47521`，以剛設定的管理帳密登入，再用米家 App 掃碼。不要把面板公開到網際網路；需要遠端存取時使用既有 HTTPS 反向代理或 VPN。先不填 HA token、不啟用橋接，避免診斷前產生控制動作。
7. 掃碼後確認 config 中出現 `.mi.token`。在本機收緊既有檔案權限：

```sh
chmod 700 config
find config -type f -exec chmod 600 {} \;
```

不要提供上述檔案內容、Cookie、HA token、QR 登入連結或 NAS 管理密碼給聊天室。

此 QNAP YAML 僅掛載 config/logs，程式封裝在映像；新版本需重新 build 並在 Container Station 重新建立 Application。修改本機 .py 後只 restart 不會更新程式。無需 privileged 或 host network；HA 使用 NAS 可路由到的 LAN IP/主機名，`localhost` 在容器內指容器本身。

## 搜尋與對話實測順序

在 NAS SSH 執行，或 Container Station 的該容器 Terminal 中移除前面的 `docker exec <容器名>`。診斷不會呼叫 HA、播報或修改鬧鐘設定；雲端可能進行登入更新，但診斷本身不寫入 token 檔。先在面板停止橋接，保持單一實例。

### 1. 安全搜尋摘要

```sh
docker exec xiaoai-ha-bridge-ai01zm python diagnose_clock.py
```

檢查兩份 MiNA 清單。若需以米家作交叉檢查：

```sh
docker exec xiaoai-ha-bridge-ai01zm python diagnose_clock.py --miio --region cn
```

region 應與綁定鬧鐘的米家區域一致。米家中國區不取決於 NAS 時區。xiaomiio 可能需要額外登入；失敗不表示 MiNA 也失敗。米家有鬧鐘但兩份 MiNA 清單都沒有，記錄此結果，**不要把米家 did 硬填為 MiNA deviceID**。

### 2. 在本機選擇目標

面板搜尋清單中點選實際鬧鐘；若無法分辨，可在自己的終端執行：

```sh
docker exec xiaoai-ha-bridge-ai01zm python diagnose_clock.py --local-ids
```

此輸出包含完整 ID，只供本機配置，勿貼到 issue 或聊天室。比對實際 MiNA deviceID 後在面板填入設備欄並保存；需要的 `hardware` 必須取自回應，不要用 model、AI01ZM 或其他音箱代號代填。若無法確定哪台是鬧鐘，停止，不對未知設備進行 TTS 或控制測試。

只有在從可信的本機資料確實取得鬧鐘的 **MiNA deviceID**、但清單未列出時，才可自行編輯 YAML 實驗：`xiaomi.device_id` 填該 ID、`allow_unlisted_device: true` 並明確指定 `conversation_api: mina` 或 `http`。HTTP 還要求觀測到的 hardware。這不是 MIoT did 到 MiNA ID 的轉換功能。平常保持 false。

### 3. 分別探測兩條對話路徑

對鬧鐘說一句不控制設備的唯一測試語句（例如詢問時間），立即執行：

```sh
docker exec xiaoai-ha-bridge-ai01zm python diagnose_clock.py --probe-conversation
```

重複至少三次，在自己的終端記錄說話時點。若有多台音箱，對另一台說話並確認所選鬧鐘路徑不把別台對話算入。摘要不顯示語句，故近 120 秒紀錄增加只是必要線索；之後還要做指定 HA 測試才能證明路由正確。

| 結果 | 判讀／下一步 |
| --- | --- |
| `login_required` | 先在面板重新登入以產生 token 快取。 |
| `selection: explicit_mina_device_required` | 指定目標未唯一找到；先處理搜尋／選擇，不能判定對話 API 能力。 |
| `status: error` | 登入、網路、API 拒絕或結構解析失敗；error_type 是安全摘要，不等於硬體不支援。修復登入／區域／網路後重試；仍失敗再依可重現測試擴充錯誤分類。 |
| API ok 但 record_count=0 | 本次格式解析成功但沒資料；在正確帳號與新語句後重試，不能宣稱支援或不支援。 |
| recent_record_count 增加 | 是對話路徑可能可用的證據，還不是完整語音控制驗證。 |
| 米家有、MiNA 無，且沒有已知 MiNA ID | 停在「缺少可用 MiNA 路由」，不要猜 ID 或硬體；需另研究雲端是否提供此設備對話。 |

診斷固定保留 `hardware_verified: false`；離線程式無法自動證明拿到的是這台鬧鐘的聲音。

### 4. TTS 單獨驗證

確認設備 ID 後，面板用固定文字測試 TTS。只有實際鬧鐘播出且其他音箱沒有響，才記 TTS 通過。API accepted 仍可能無聲。TTS 與語音紀錄讀取是不同能力；其中一個通過不代表另一個通過。首次測試關閉原生回答中斷與事件播報，避免誤停鬧鐘或其他聲音。

### 5. Home Assistant 端到端驗證（experimental.6）

米家 AI01ZM 採用獨立的 `mijia_aivs` 對話路徑，不要求 MiNA 清單出現設備。歷史紀錄讀取已確認；HA 控制仍需下列實測。

1. 建立無實體負載的 HA 輔助開關，entity_id 必須符合 `input_boolean.xiaoai_ai01zm_bridge_test[a-z0-9_]*`，填入 `xiaomi.clock_test_entity`。
2. 「僅測收音」會設定 `clock_bridge_dry_run: true`，收到語音也不呼叫 HA。要測 HA 請按「開始 HA 虛擬開關測試」，成功後會顯示測試模式及實際開關狀態。原有規則保留，但此模式不會執行它們。
3. 啟動後才對鬧鐘說「打開測試開關」，等待約 5 秒後說「關閉測試開關」。舊的「打開橋接測試／關閉橋接測試」也可用。
4. 面板顯示的 HA 成功次數是服務回應；另列的開關 on/off 才是從 HA 讀取的實際狀態。需要觀察 on 再 off，不能用小愛原生回答判定成敗。
5. 重複測試、不相關語句、重啟後不重播及重新登入後恢復，分別記錄。輪詢忽略啟動前及超時紀錄，請每次啟動後重新說指令。
6. TTS、日常規則與自動啟動尚需獨立驗證；本次診斷部署使用 lifespan off，容器重建後需重新啟動測試模式。

## 回報、驗收與回退

可分享 `diagnose_clock.py` **未加 --local-ids** 的 JSON 摘要，另附本機記錄的：分支 commit、鬧鐘標籤型號、韌體版本（不要序號/MAC）、NAS 型號與架構、QTS/QuTS 與 Container Station 版本、米家區域、成功的 API、各階段結果及延遲。原始 `logs/` 仍可能含日常語句與 HA 實體資訊，不能把完整日誌視為可公開資料；需要時只提供已檢查的相關安全摘要。不要上傳 config/、auth.json、.mi.token、HAR 或完整 HTTP 回應。

只有「確認實體設備 → 唯一設備與已驗證對話路由 → 新語音紀錄 → 正確 HA 動作 → 無重播／誤選 → 重啟與重新登入後重測」全數通過，才能在該帳號、區域、韌體與版本組合上稱為實機驗證通過。未通過時維持實驗標示。

回退：停止實驗 Application，保留 config 備份並恢復原映像／原容器；不要同時啟動兩份橋接器。若手動恢復原版程式，需重建原版映像，不能只刪除新模組。實驗新增的 YAML 欄位可留存備份，但重新確認原版的設備選擇，避免原版回落第一台。

## 本次開發驗證

experimental.6 通過 48 項合成資料 Python 測試及 3 個 QR 前端排程測試。已在 QNAP 建置並部署前版；米家實際歷史紀錄及啟動後的新語音已讀取。HA 開關 on→off 的完整實測仍待確認，不能稱為完整支援。
