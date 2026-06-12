import os
from datetime import datetime
from modules.db import get_conn

def run_database_backup():
    try:
        backup_dir = os.path.abspath("database_backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_path = os.path.join(backup_dir, "Hospital_.bak")
        sql = f"BACKUP DATABASE Hospital TO DISK = '{backup_path}' WITH INIT;"
        conn = get_conn()
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.close()
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 資料庫備份成功：{backup_path}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 資料庫備份失敗：{e}")