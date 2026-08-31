import logging
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
_engine = None

def _database_url():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return database_url

def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            _database_url(),
            pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
            pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
            pool_pre_ping=True,
        )
    return _engine

def get_conn():
    return get_engine().raw_connection()

def execute_query(sql, params=None):
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        if params is not None:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        if cursor.description:
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        conn.commit()
        return True
    except Exception:
        logging.exception("DB query failed | SQL: %s", sql)
        if sql.strip().upper().startswith("SELECT"):
            return []
        return False
    finally:
        if conn:
            conn.close()