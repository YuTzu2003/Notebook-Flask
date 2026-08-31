import os
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, session, flash
from functools import wraps
import json
import secrets
import threading
from datetime import datetime
# from werkzeug.security import check_password_hash
from modules.db import get_conn

LOG_FILE_PATH = os.path.join("tasks", "login_history.json")
LOGIN_LOG_LOCK = threading.Lock()


def synchronized(lock):
    def decorate(func):
        @wraps(func)
        def locked(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)
        return locked
    return decorate

@synchronized(LOGIN_LOG_LOCK)
def log_login_attempt(emp_id, status, message, ip_address):
    os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
    
    log_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "emp_id": emp_id,
        "status": status,
        "message": message,
        "ip": ip_address
    }
    
    logs = []
    if os.path.exists(LOG_FILE_PATH):
        try:
            with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            pass
            
    logs.append(log_entry)
    
    # 保留最近 1000 筆
    if len(logs) > 1000:
        logs = logs[-1000:]
        
    try:
        with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print("Error saving log:", e)

auth_bp = Blueprint("auth", __name__, template_folder="../templates")

# 權限
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "ID" not in session:
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)
    return wrapper


# 登入
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        emp_id = request.form["emp_id"]
        password = request.form["password"]

        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""SELECT * FROM Users WHERE UserID = ? """, emp_id)

        user = cursor.fetchone()
        ip_address = request.remote_addr

        # if user and check_password_hash(user.Password, password):
        if user and secrets.compare_digest(str(user.Password), password):
            session["ID"] = user.ID        
            session["UserID"] = user.UserID 
            session["Name"] = user.Name     
            session["Position"] = user.Position
            session["Location"] = user.Location

            cursor.execute("""UPDATE Users SET Last_login = GETDATE() WHERE ID = ? """, user.ID)
            conn.commit()
            conn.close()
            
            log_login_attempt(emp_id, "Success", "登入成功", ip_address)
            
            return redirect(url_for("bp_index.index"))

        conn.close()
        
        # 紀錄失敗
        message = "密碼錯誤" if user else "帳號不存在"
        log_login_attempt(emp_id, "Failed", message, ip_address)
        
        flash("帳號或密碼錯誤")

    return render_template("login.html")


# 登出
@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if session.get("Position") not in ["Admin"]:
            flash("權限不足")
            return redirect(url_for("bp_index.index"))
        return func(*args, **kwargs)
    return wrapper

@auth_bp.route("/admin/users")
@login_required
@admin_required
def admin_users():
    conn = get_conn()
    cursor = conn.cursor()
    sort_val = request.args.get('sort_by', 'Last_login')# 預設
    search_name = request.args.get('search_name', '').strip()
    if sort_val not in {'Last_login', 'Name', 'UserID', 'Position', 'Location'}:
        sort_val = 'Last_login'
    filter_pos = request.args.get('filter_pos', '')
    
    order = 'DESC' if sort_val == 'Last_login' else 'ASC'
    
    sql = "SELECT ID, UserID, Name, Position, Location, Last_login FROM Users WHERE 1=1"
    params = []
    
    if search_name:
        sql += " AND Name LIKE ?"
        params.append(f"%{search_name}%")
        
    if filter_pos:
        sql += " AND Position = ?"
        params.append(filter_pos)
        
    sql += f" ORDER BY {sort_val} {order}"
    
    cursor.execute(sql, tuple(params))
    columns = [column[0] for column in cursor.description]
    users = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return render_template("admin.html", users=users, current_sort=sort_val, search_name=search_name, filter_pos=filter_pos)

@auth_bp.route("/admin/manage_user", methods=["POST"])
@admin_required
def manage_user():
    data = request.json
    action = data.get("action")  # 指令:'add','edit','delete'

    guid_id = data.get("id")         
    userid = data.get("user_id")     
    name = data.get("name")
    pwd = data.get("password")
    pos = data.get("position")
    loc = data.get("location")

    conn = get_conn()
    cursor = conn.cursor()

    if action == "delete":
        cursor.execute("SELECT DocID, StorageName FROM Documents WHERE User_ID = ?", (guid_id,))
        user_docs = cursor.fetchall()

        for row in user_docs:
            pdf_path = f"tasks/uploads/{str(row[1])}"
            json_path = f"tasks/annotation/{str(row[0])}.json"
            
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

            if os.path.exists(json_path):
                os.remove(json_path)

        cursor.execute("DELETE FROM Documents WHERE User_ID = ?", (guid_id,))
        cursor.execute("DELETE FROM Users WHERE ID = ?", (guid_id,))      
        conn.commit()
        return jsonify({"success": True, "message": "Delete Successful"})

    elif action == "edit":
        if pwd:
            sql = "UPDATE Users SET Name=?, Password=?, Position=?, Location=?, UserID=? WHERE ID=?"
            cursor.execute(sql, (name, pwd, pos, loc, userid, guid_id))
        else:
            sql = "UPDATE Users SET Name=?, Position=?, Location=?, UserID=? WHERE ID=?"
            cursor.execute(sql, (name, pos, loc, userid, guid_id))
        
        conn.commit()
        return jsonify({"success": True, "message": "Update Successful!"})

    elif action == "add":
        if not userid or not name:
            return jsonify({"success": False, "message": "編號與姓名為必填"}), 400

        cursor.execute("SELECT ID FROM Users WHERE UserID = ?", (userid,))
        if cursor.fetchone():
            return jsonify({"success": False, "message": f"編號 {userid} 已存在"}), 400

        sql = """INSERT INTO Users (UserID, Name, Password, Position, Location) VALUES (?, ?, ?, ?, ?)"""
        cursor.execute(sql, (userid, name, pwd, pos, loc))
        conn.commit()
        return jsonify({"success": True, "message": "Add Successful"})

@auth_bp.route("/admin/error_log")
@login_required
@admin_required
def error_log():
    conn = get_conn()
    cursor = conn.cursor()
    
    sql = "SELECT TOP 100 LogID, ErrorCode, ErrorMessage, Traceback, CreatedAt FROM ErrorLogs ORDER BY CreatedAt DESC"
    
    try:
        cursor.execute(sql)
        columns = [column[0] for column in cursor.description]
        logs = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        print("Fetch logs error:", e)
        logs = []
        
    conn.close()
    return render_template("error_log.html", logs=logs)

@auth_bp.route("/admin/login_logs")
@login_required
@admin_required
def api_login_logs():
    logs = []
    if os.path.exists(LOG_FILE_PATH):
        try:
            with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            pass
    # 回傳反轉的陣列，讓最新的在前面
    return jsonify({"success": True, "logs": logs[::-1]})
