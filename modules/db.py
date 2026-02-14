import pyodbc

def get_conn():
    return pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=127.0.0.1;' 
        'DATABASE=Hospital;'
        'UID=YLH;'           
        'PWD=YLH;'      
        'TrustServerCertificate=yes;'
    )

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