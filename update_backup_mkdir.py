import os
import re

with open('modules/backup.py', 'r', encoding='utf-8') as f:
    content = f.read()

find_str = """        backup_dir = os.path.abspath("backups")
        os.makedirs(backup_dir, exist_ok=True)

        backup_path = os.getenv("DB_BACKUP_PATH", os.path.join(backup_dir, "Hospital_.bak"))"""

replace_str = """        backup_dir = os.path.abspath("backups")
        os.makedirs(backup_dir, exist_ok=True)

        backup_path = os.getenv("DB_BACKUP_PATH", os.path.join(backup_dir, "Hospital_.bak"))
        
        # 自動建立備份路徑的資料夾 (確保指定的路徑存在)
        target_dir = os.path.dirname(backup_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)"""

content = content.replace(find_str, replace_str)

with open('modules/backup.py', 'w', encoding='utf-8') as f:
    f.write(content)
