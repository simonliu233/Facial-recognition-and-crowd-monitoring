# FaceTech 本機版

本項目已改為單一網址的本機應用。無需舊伺服器、網域、Nginx、HTTPS 憑證或雲端 PostgreSQL；只有 `127.0.0.1` 可以連線。


## GitHub 下載版本

倉庫包含程式、測試、合成測試影片及本機推論所需模型；不包含這台電腦的帳戶資料庫、人員照片、辨識快取、憑證或備份。新下載的版本沒有預設帳戶，請自行註冊。

在新電腦準備好 Python 3.10 後，於專案根目錄建立環境：

```powershell
py -3.10 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r "Python Page\requirements.txt"
.\Start-Local.ps1
```

Windows 首次安裝 dlib 需要可用的 C++ Build Tools 和 CMake。需要執行測試時，再安裝 `Python Page/requirements-dev.txt`。上傳內容與排除規則見 `PUBLISHING.md`。

## 啟動

在 Windows 雙擊根目錄的 **Start-Local.bat**。它會使用此項目的 `.venv`，並開啟：

http://127.0.0.1:5000/

首次使用請註冊本機帳戶。原本 `Python Page/instance/login_database.db` 中的帳戶保留；雲端帳戶不會同步。

PowerShell 也可以從任何目錄執行：

```powershell
.\Start-Local.ps1
```

若 5000 被佔用：

```powershell
.\Start-Local.ps1 -Port 5050
```

在終端按 Ctrl+C 停止服務。不需管理員權限。請保持該終端運行；不要同時啟動多份服務。

## 此電腦的 Python 環境

已建立 Python 3.10 的 `.venv`，重用這台電腦現有的 Python 3.10 套件，沒有修改全域套件。預設的 Python 3.14 並不適合本項目已驗證的依賴組合。

檢查實際匯入及模型：

```powershell
.\Start-Local.ps1 -Check
```

搬到另一台電腦時，請重建虛擬環境，不要直接複製 `.venv`。使用 Python 3.10 或 3.11，然後安裝 `Python Page/requirements.txt`。Windows 上首次編譯 dlib 需要 C++ Build Tools 和 CMake；目前這台電腦已經安裝好 dlib。

## 人臉識別

1. 登入後，從「人員資料」新增清晰、單一人臉的正面照片。
2. 開啟「人臉識別」，按「開始攝影機」並允許這個本機網站使用鏡頭。
3. 也可以選擇本機影片，不需要攝影機。
4. 新增、改名、替換或刪除照片後，下一次識別會自動刷新資料。
5. 年齡範圍、性別和情緒為模型估計；相似度不是經校準的正確機率。

已改用 HOG/dlib、OpenCV Caffe 模型，以及本機 FER 模型的 Keras/PyTorch 後端。TensorFlow、MediaPipe、InsightFace、TensorRT、GPU 和雲端模型下載均非必要。

GitHub 版本不附帶原有人臉照片；請在本機人員管理新增自己的清晰照片。沒有單一可編碼人臉的照片會被略過並顯示警告。

## 門口／通道雙向人流

已改用 **YOLOv8 + ByteTrack + 雙側確認的越線狀態機**：

- 只追蹤 person 類別，每個追蹤 ID 獨立判斷，移除全域兩秒冷卻。
- 使用人體框底部中心作定位點，支援左右或上下通行。
- 越過計數線兩側的緩衝區且連續確認後才計數，避免線附近抖動。
- 只根據實際偵測到的軌跡計數，不從區域總人數變化補算，也不對消失人物推測越線。
- 同一人折返可計入反方向；這是通行次數，不是去重後的人數。
- 可調整線位置、緩衝區及計數線的有效範圍，排除非通道區域。
- 同一時間只允許一個影片／攝影機來源，避免多分頁混用追蹤狀態。
- 傳送原始影格，而非含偵測框、文字的畫布，避免畫面標記反過來干擾模型。
- 影片按時間順序逐影格分析，處理慢時放慢播放而不跳過通行過程。
- 顯示本次計數和今日累計；事件立即寫入 SQLite，防止隨機存檔漏存。
- 本機 Ultralytics 同步／Hub 已關閉。

建議先使用內附的 `validation/synthetic-crossing.webm` 測試：一人向右再向左通行，預期正反各 1 次。此影片是合成的軟體測試樣本，不能代表實際門口的準確率。

現場改善順序：

1. 固定鏡位並改善光線，避免人物在計數線附近被門框或其他人長時間遮擋。
2. 計數線放在人物兩側都看得清楚的位置，勿貼近畫面邊緣。
3. 用有效範圍排除鄰近行人和反光區域；一般先使用 4% 半緩衝區。
4. 用人工逐段標記的現場影片分別計算漏計與誤計，再調整鏡位及參數。
5. 若人群密集、小人物漏檢仍明顯，可透過 `FACE_APP_YOLO_MODEL` 指向較大或經場景訓練的本機模型。需要重新評估速度和準確率，不能僅憑模型大小保證改善。

追蹤原理與參數參考：[Ultralytics Tracking](https://docs.ultralytics.com/modes/track/)。

## 資料位置與備份

- 帳戶、人員資料：`Python Page/instance/login_database.db`，保留原檔。
- 人臉照片：`Python Page/data/photo/`。
- 識別、人流日計數與越線事件：`Python Page/data/local/analytics.db`。
- 計數線設定：`Python Page/data/local/flow-settings.json`。
- 人臉快取：`Python Page/data/local/cache/face-encodings.json`，使用安全 JSON，不讀取原 pickle。
- 本機登入 session key：`Python Page/data/local/.session-key`。
- 原本 `data/achieve` 的紀錄第一次使用時會複製到新資料庫，原檔不變。
- 修改前的程式與網頁備份：`.local-backups/before-local-migration.zip`。備份可能含舊部署憑證資訊或密碼，請勿公開分享。
- 舊的 `certs` 不再使用，不需修復或設定。

備份資料庫前請先停止服務，並連同照片及本機資料目錄一起備份。

## 測試

```powershell
& ".\.venv\Scripts\python.exe" -B -m pytest "Python Page\tests" -q -p no:cacheprovider
```

完整測試會使用臨時帳戶和資料庫；真實模型測試會禁止 HTTP 存取，檢查照片登錄、識別、改名、刪除、空白影格、完整 80 影格雙向通行影片、來源衝突、設定與重設。更多人工驗證紀錄見 `validation/REPORT.md`。

## 執行參數

- `FACE_APP_DEVICE`：預設 `cpu`；只有已配置相容 GPU 環境時才改用 CUDA。
- `FACE_APP_YOLO_MODEL`：指定本機行人模型完整路徑，不會自動下載模型。
- `FACE_APP_DATA_DIR`、`FACE_APP_PHOTO_DIR`、`FACE_APP_LOGIN_DB`：可分別指定本機資料、照片和帳戶檔案位置。

本版本為單機使用，預設不開放區域網路或公網。模型有其辨識限制；目前測試可證明已覆蓋流程通過，不能保證所有攝影機、姿態和人群密度都沒有誤差。
