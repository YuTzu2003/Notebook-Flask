import os
import pyodbc
from dotenv import load_dotenv
from dbutils.pooled_db import PooledDB

load_dotenv()

class DBConnectWrapper:
    threadsafety = 1
    dbapi = pyodbc 
    def __init__(self, conn_str):
        self.conn_str = conn_str
    def connect(self, *args, **kwargs):
        return pyodbc.connect(self.conn_str, *args, **kwargs)
_pool = None

def get_conn():
    global _pool
    if _pool is None:
        driver = os.environ.get("DB_DRIVER")
        server = os.environ.get("DB_SERVER")
        port = os.environ.get("DB_PORT")
        database = os.environ.get("DB_NAME")
        uid = os.environ.get("DB_USER")
        pwd = os.environ.get("DB_PASS")
        conn_str = f"DRIVER={driver};SERVER={server};PORT={port};DATABASE={database};UID={uid};PWD={pwd};TrustServerCertificate=yes;"
        _pool = PooledDB(
            creator=DBConnectWrapper(conn_str),
            maxconnections=30,
            mincached=2,
            maxcached=10,
            blocking=True,
            failures=(pyodbc.OperationalError, pyodbc.InternalError, pyodbc.ProgrammingError, pyodbc.DatabaseError)
        )
    return _pool.connection()


def execute_query(sql, params=None):
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
            
        if cursor.description:
            columns = [column[0] for column in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results
        else:
            conn.commit()
            return True
            
    except Exception as e:
        print(f"DB Error | SQL: {sql} | Msg: {e}")
        if sql.strip().upper().startswith("SELECT"):
            return []
        return False  
    finally:
        if conn:
            conn.close()
