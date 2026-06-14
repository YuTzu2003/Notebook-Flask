import os
import pyodbc
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def run_database_backup():
    try:
        backup_dir = os.path.abspath("backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_path = os.path.join(backup_dir, "Hospital_.bak")
        sql = f"BACKUP DATABASE Hospital TO DISK = '{backup_path}' WITH INIT;"

        # BACKUP DATABASE 不能在交易內執行，必須用獨立連線並在建立時就開啟 autocommit
        driver = os.environ.get("DB_DRIVER")
        server = os.environ.get("DB_SERVER")
        port = os.environ.get("DB_PORT")
        database = os.environ.get("DB_NAME")
        uid = os.environ.get("DB_USER")
        pwd = os.environ.get("DB_PASS")
        conn_str = f"DRIVER={driver};SERVER={server};PORT={port};DATABASE={database};UID={uid};PWD={pwd};TrustServerCertificate=yes;"
        conn = pyodbc.connect(conn_str, autocommit=True)

        cursor = conn.cursor()
        cursor.execute(sql)
        # 等待備份完成（SQL Server 可能回傳多個結果集）
        while cursor.nextset():
            pass
        conn.close()
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 資料庫備份成功：{backup_path}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 資料庫備份失敗：{e}")