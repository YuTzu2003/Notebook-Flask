import os
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, session, flash
from functools import wraps
# from werkzeug.security import check_password_hash
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

        # if user and check_password_hash(user.Password, password):
        if user and user.Password == password:
            session["ID"] = user.ID        
            session["UserID"] = user.UserID 
            session["Name"] = user.Name     
            session["Position"] = user.Position
            session["Location"] = user.Location

            cursor.execute("""UPDATE Users SET Last_login = GETDATE() WHERE ID = ? """, user.ID)
            conn.commit()
            conn.close()
            return redirect(url_for("index"))

        conn.close()
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
            return redirect(url_for("index"))
        return func(*args, **kwargs)
    return wrapper

@auth_bp.route("/admin/users")
@login_required
@admin_required
def admin_users():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT ID, UserID, Name, Position, Location, Last_login FROM Users ORDER BY Last_login DESC")
    columns = [column[0] for column in cursor.description]
    users = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return render_template("admin.html", users=users)

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
            pdf_path = f"static/uploads/{str(row[1])}"
            json_path = f"static/annotation/{str(row[0])}.json"
            
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