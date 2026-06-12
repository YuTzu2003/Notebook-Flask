import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()

def get_conn():
    driver = os.environ.get("DB_DRIVER")
    server = os.environ.get("DB_SERVER")
    port = os.environ.get("DB_PORT")
    database = os.environ.get("DB_NAME")
    uid = os.environ.get("DB_USER")
    pwd = os.environ.get("DB_PASS")
    return pyodbc.connect(f'DRIVER={driver};'f'SERVER={server};'f'port={port};' f'DATABASE={database};'f'UID={uid};'           f'PWD={pwd};'      'TrustServerCertificate=yes;')

def execute_query(sql, params=None):
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        conn.commit()
        return True
    except Exception as e:
        print(f"DB Error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def fetch_all(sql, params=None):
    conn = None
    try:
        conn = get_conn() 
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
            
        columns = [column[0] for column in cursor.description]
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))
            
        return results
    except Exception as e:
        print(f"DB Error: {e}")
        return []
    finally:
        if conn:
            conn.close()