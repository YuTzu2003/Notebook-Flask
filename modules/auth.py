import os
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, session, flash
from functools import wraps
import secrets
from werkzeug.security import check_password_hash, generate_password_hash
from modules.audit import write_audit_log
from modules.db import get_conn

auth_bp = Blueprint("auth", __name__, template_folder="../templates")

# 權限
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "ID" not in session:
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)
    return wrapper


def password_matches(stored_password, provided_password):
    stored_password = str(stored_password)
    if "$" not in stored_password:
        return secrets.compare_digest(stored_password, provided_password)
    try:
        return check_password_hash(stored_password, provided_password)
    except (TypeError, ValueError):
        return secrets.compare_digest(str(stored_password), provided_password)


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_password or not new_password or not confirm_password:
            flash("請完整填寫所有密碼欄位。", "error")
            return render_template("profile.html", show_password_form=True)

        if new_password != confirm_password:
            flash("新密碼與確認密碼不一致。", "error")
            return render_template("profile.html", show_password_form=True)

        conn = get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT UserID, Name, Position, Location, Password FROM Users WHERE ID = ?",
                (session["ID"],),
            )
            user = cursor.fetchone()

            if not user or not password_matches(user.Password, current_password):
                write_audit_log("auth_change_password_failed", {"reason": "current_password_incorrect"})
                flash("目前密碼不正確。", "error")
                return render_template("profile.html", user=user, show_password_form=True)

            cursor.execute(
                "UPDATE Users SET Password = ? WHERE ID = ?",
                (generate_password_hash(new_password), session["ID"]),
            )
            conn.commit()
        finally:
            conn.close()

        write_audit_log("auth_change_password", {"status": "success"})
        flash("密碼已更新。", "success")
        return redirect(url_for("auth.profile"))

    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT UserID, Name, Position, Location FROM Users WHERE ID = ?", (session["ID"],))
        user = cursor.fetchone()
    finally:
        conn.close()
    return render_template("profile.html", user=user)


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

        if user and password_matches(user.Password, password):
            session["ID"] = user.ID        
            session["UserID"] = user.UserID 
            session["Name"] = user.Name     
            session["Position"] = user.Position
            session["Location"] = user.Location

            cursor.execute("""UPDATE Users SET Last_login = GETDATE() WHERE ID = ? """, user.ID)
            conn.commit()
            conn.close()
            
            write_audit_log("auth_login_success", {"login_id": emp_id, "status": "success"}, user_id=user.ID, remote_addr=ip_address)
            
            return redirect(url_for("bp_index.index"))

        conn.close()
        
        # 紀錄失敗
        message = "密碼錯誤" if user else "帳號不存在"
        write_audit_log("auth_login_failed", {"login_id": emp_id, "reason": message}, user_id=user.ID if user else None, remote_addr=ip_address)
        
        flash("帳號或密碼錯誤")

    return render_template("login.html")


# 登出
@auth_bp.route("/logout")
def logout():
    write_audit_log("auth_logout", {"name": session.get("Name")})
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
            cursor.execute(sql, (name, generate_password_hash(pwd), pos, loc, userid, guid_id))
        else:
            sql = "UPDATE Users SET Name=?, Position=?, Location=?, UserID=? WHERE ID=?"
            cursor.execute(sql, (name, pos, loc, userid, guid_id))
        
        conn.commit()
        return jsonify({"success": True, "message": "Update Successful!"})

    elif action == "add":
        if not userid or not name or not pwd:
            return jsonify({"success": False, "message": "編號與姓名為必填"}), 400

        cursor.execute("SELECT ID FROM Users WHERE UserID = ?", (userid,))
        if cursor.fetchone():
            return jsonify({"success": False, "message": f"編號 {userid} 已存在"}), 400

        sql = """INSERT INTO Users (UserID, Name, Password, Position, Location) VALUES (?, ?, ?, ?, ?)"""
        cursor.execute(sql, (userid, name, generate_password_hash(pwd), pos, loc))
        conn.commit()
        return jsonify({"success": True, "message": "Add Successful"})

@auth_bp.route("/admin/system_log")
@login_required
@admin_required
def system_log():
    conn = get_conn()
    cursor = conn.cursor()
    
    date_filter = request.args.get('date', '').strip()
    sort_order = request.args.get('sort', 'desc').lower()
    search_query = request.args.get('search', '').strip()
    
    if sort_order not in ['asc', 'desc']:
        sort_order = 'desc'
        
    sql = """SELECT TOP 100 logs.LogID, logs.[Action], logs.CreatedAt, logs.User_id,
                    logs.Detail_json, logs.Remote_addr, users.Name AS UserName
             FROM Audit_logs AS logs
             LEFT JOIN Users AS users ON logs.User_id = CONVERT(varchar(100), users.ID)
                                      OR logs.User_id = users.UserID
             WHERE 1=1"""
             
    params = []
    
    if date_filter:
        sql += " AND CAST(logs.CreatedAt AS DATE) = ?"
        params.append(date_filter)
        
    if search_query:
        sql += """ AND (
            logs.[Action] LIKE ? 
            OR users.Name LIKE ? 
            OR logs.User_id LIKE ? 
            OR logs.Remote_addr LIKE ?
        )"""
        like_term = f"%{search_query}%"
        params.extend([like_term, like_term, like_term, like_term])
        
    sql += f" ORDER BY logs.CreatedAt {sort_order}"
    
    try:
        if params:
            cursor.execute(sql, tuple(params))
        else:
            cursor.execute(sql)
            
        columns = [column[0] for column in cursor.description]
        logs = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        print("Fetch logs error:", e)
        logs = []
        
    conn.close()
    return render_template("system_log.html", logs=logs, current_date=date_filter, current_sort=sort_order, current_search=search_query)
