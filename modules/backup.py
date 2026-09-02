import os
from datetime import datetime

from dotenv import load_dotenv
from modules.db import get_conn

from modules.db import get_conn


load_dotenv()


def run_database_backup():
    conn = None
    try:
        backup_dir = os.path.abspath("backups")
        os.makedirs(backup_dir, exist_ok=True)

        backup_path = os.getenv("DB_BACKUP_PATH", os.path.join(backup_dir, "Hospital_.bak"))
        
        # 自動建立備份路徑的資料夾 (確保指定的路徑存在)
        target_dir = os.path.dirname(backup_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        database = os.getenv("DB_BACKUP_DATABASE", os.getenv("DB_NAME", "Hospital"))
        safe_database = database.replace("]", "]]")
        safe_backup_path = backup_path.replace("'", "''")
        sql = f"BACKUP DATABASE [{safe_database}] TO DISK = '{safe_backup_path}' WITH INIT;"

        conn = get_conn()
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute(sql)
        while cursor.nextset():
            pass

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 資料庫備份成功：{backup_path}")
    except Exception as error:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 資料庫備份失敗：{error}")
    finally:
        if conn:
            conn.autocommit = False
            conn.close()
