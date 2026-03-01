使用Flask和SQL Server Management Studio(SSMS)製作

## 介紹
本專案主要提供給**台灣癌症登記師**使用，允許使用者在PDF文件上直接做筆記。
目前功能範圍主要針對**台灣癌症登記手冊**癌登師需求進行開發。

## 執行步驟
還原資料庫：
```bash
Restore Hospital.bak
```

建立環境：
```bash
cd notebook-flask
uv venv
.venv\Scripts\activate
uv sync
```

執行專案：
```bash
uv run app.py
```