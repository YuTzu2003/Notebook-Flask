本專案是一個基於 Flask 開發的 Web 應用程式，專為**台灣癌症登記師**設計。其主要功能是讓使用者能在不同版本的「台灣癌症登記手冊」PDF 文件之間，實現筆記的自動化遷移與管理，解決手冊更版時筆記重新謄寫的痛點。

## 核心功能

- **PDF 筆記編輯與管理**：支援在PDF上直接進行標記與筆記。
- **版本比對 (Mapping)**：自動分析不同版本手冊之間的文本差異與對應關係。
- **筆記自動遷移**：根據版本比對結果，將舊版手冊上的筆記轉移至新版手冊。
- **版本控制與歷史紀錄**：管理各年度手冊版本，並記錄完整的筆記轉移歷程。
- **使用者權限管理**：安全的登入系統，確保每位登記師的筆記資料獨立且安全。

## 使用技術

- **後端框架**: Flask (Python 3.12+)
- **資料庫**: SQL Server Management Studio (SSMS)
- **PDF 處理庫**: PyMuPDF (fitz), pdfplumber, pdfrw
- **資料分析**: Pandas, RapidFuzz, Scikit-learn
- **環境管理**: [uv](https://github.com/astral-sh/uv)

---

## 環境建置與使用流程

### 1. 資料庫還原
本系統依賴 SQL Server，請先使用 SSMS 還原專案中的資料庫備份檔：
- 還原檔案：`Hospital.bak`
- 資料庫名稱：`Hospital`

### 2. 建立 Python 執行環境
使用 `uv` 進行使用。

```bash
cd notebook-flask
uv venv

.venv\Scripts\activate  # Windows

uv sync
```

### 3. 設定環境變數與資料庫連接
在專案根目錄建立一個 `.env` 檔案，並寫入以下內容：

```ini
DB_DRIVER={ODBC Driver 17 for SQL Server}
DB_SERVER=localhost
DB_PORT=1433
DB_NAME=Hospital
DB_USER=YLH
DB_PASS=YLH
FLASK_PORT=50001
FLASK_RUN_PORT=50001
FLASK_RUN_HOST=0.0.0.0
```

請確認上述參數與您的本地資料庫環境一致（可依實際需求修改帳號密碼與主機位址）。

### 4. 執行專案
```bash
flask run
```
啟動後，開啟瀏覽器造訪 `http://127.0.0.1:5001` 即可進入系統。