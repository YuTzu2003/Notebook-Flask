import os
import re
from flask import Blueprint, current_app, jsonify, render_template, request, redirect, url_for, session, flash
from functools import wraps
import secrets
from werkzeug.security import check_password_hash, generate_password_hash
from modules.audit import write_audit_log
from modules.db import get_conn
from modules.gmail_mailer import MailDeliveryError, send_email

auth_bp = Blueprint("auth", __name__, template_folder="../templates")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
CODE_LENGTH = 6
MAX_CODE_ATTEMPTS = 5


class CodeRequestLimitError(RuntimeError):
    pass


def _valid_email(email):
    return len(email) <= 254 and bool(EMAIL_PATTERN.fullmatch(email))


def _new_code():
    return f"{secrets.randbelow(1_000_000):0{CODE_LENGTH}d}"


def _send_code(user_id, purpose, email):
    """Invalidate earlier codes and issue one short-lived code for this account."""
    code = _new_code()
    minutes = current_app.config["PASSWORD_CODE_MINUTES"]
    conn = get_conn()
    cursor = conn.cursor()
    try:
        resend_seconds = current_app.config["VERIFICATION_CODE_RESEND_SECONDS"]
        max_per_hour = current_app.config["VERIFICATION_CODE_MAX_PER_HOUR"]
        cursor.execute("""SELECT COUNT(*) FROM AccountVerificationCodes
                          WHERE UserID = ? AND Purpose = ?
                            AND CreatedAt > DATEADD(second, ?, SYSDATETIMEOFFSET())""",
                       (user_id, purpose, -resend_seconds))
        if cursor.fetchone()[0]:
            raise CodeRequestLimitError(f"請於 {resend_seconds} 秒後再重新寄送驗證碼。")
        cursor.execute("""SELECT COUNT(*) FROM AccountVerificationCodes
                          WHERE UserID = ? AND Purpose = ?
                            AND CreatedAt > DATEADD(hour, -1, SYSDATETIMEOFFSET())""", (user_id, purpose))
        if cursor.fetchone()[0] >= max_per_hour:
            raise CodeRequestLimitError("此帳號目前寄送驗證碼次數過多，請 1 小時後再試。")
        cursor.execute("""UPDATE AccountVerificationCodes SET UsedAt = SYSDATETIMEOFFSET()
                          WHERE UserID = ? AND Purpose = ? AND UsedAt IS NULL""", (user_id, purpose))
        cursor.execute("""INSERT INTO AccountVerificationCodes
                          (UserID, Purpose, Email, CodeHash, ExpiresAt)
                          VALUES (?, ?, ?, ?, DATEADD(minute, ?, SYSDATETIMEOFFSET()))""",
                       (user_id, purpose, email, generate_password_hash(code), minutes))
        conn.commit()
    finally:
        conn.close()
    subject = "臺大醫院PDF做筆記－驗證碼" if purpose == "verify_email" else "臺大醫院PDF做筆記－重設密碼驗證碼"
    body = f"您的驗證碼為：{code}\n\n此驗證碼將於 {minutes} 分鐘後失效，且只能使用一次。若不是您本人操作，請忽略此信件。"
    try:
        send_email(current_app.config, email, subject, body)
    except MailDeliveryError:
        # A code that was not delivered must never remain usable.
        conn = get_conn()
        try:
            conn.cursor().execute("UPDATE AccountVerificationCodes SET UsedAt = SYSDATETIMEOFFSET() WHERE UserID = ? AND Purpose = ? AND UsedAt IS NULL", (user_id, purpose))
            conn.commit()
        finally:
            conn.close()
        raise


def _consume_code(user_id, purpose, code):
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("""SELECT TOP 1 CodeID, Email, CodeHash, Attempts
                          FROM AccountVerificationCodes
                          WHERE UserID = ? AND Purpose = ? AND UsedAt IS NULL
                            AND ExpiresAt > SYSDATETIMEOFFSET()
                          ORDER BY CreatedAt DESC""", (user_id, purpose))
        record = cursor.fetchone()
        if not record or record.Attempts >= MAX_CODE_ATTEMPTS or not check_password_hash(record.CodeHash, code):
            if record:
                cursor.execute("UPDATE AccountVerificationCodes SET Attempts = Attempts + 1 WHERE CodeID = ?", (record.CodeID,))
                conn.commit()
            return None
        cursor.execute("UPDATE AccountVerificationCodes SET UsedAt = SYSDATETIMEOFFSET() WHERE CodeID = ? AND UsedAt IS NULL", (record.CodeID,))
        if cursor.rowcount != 1:
            return None
        conn.commit()
        return record.Email
    finally:
        conn.close()


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
            return redirect(url_for("auth.profile", show_password_form=1))

        if new_password != confirm_password:
            flash("新密碼與確認密碼不一致。", "error")
            return redirect(url_for("auth.profile", show_password_form=1))

        conn = get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT UserID, Name, Position, Location, Email, EmailVerifiedAt, Password FROM Users WHERE ID = ?",
                (session["ID"],),
            )
            user = cursor.fetchone()

            if not user or not password_matches(user.Password, current_password):
                write_audit_log("auth_change_password_failed", {"reason": "current_password_incorrect"})
                flash("目前密碼不正確。", "error")
                return redirect(url_for("auth.profile", show_password_form=1))

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
        cursor.execute("SELECT UserID, Name, Position, Location, Email, EmailVerifiedAt FROM Users WHERE ID = ?", (session["ID"],))
        user = cursor.fetchone()
    finally:
        conn.close()
    return render_template(
        "profile.html",
        user=user,
        pending_email=session.get("pending_email"),
        show_password_form=request.args.get("show_password_form") == "1",
    )


@auth_bp.post("/profile/email")
@login_required
def request_email_verification():
    email = request.form.get("email", "").strip().lower()
    if not _valid_email(email):
        flash("請輸入有效的 Email。", "error")
        return redirect(url_for("auth.profile", setup_email=1))
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Email, EmailVerifiedAt FROM Users WHERE ID = ?", (session["ID"],))
        user = cursor.fetchone()
    finally:
        conn.close()
    if user and user.EmailVerifiedAt and str(user.Email).strip().lower() == email:
        flash("此 Email 已完成綁定，無需再次驗證。", "success")
        return redirect(url_for("auth.profile"))
    try:
        _send_code(session["ID"], "verify_email", email)
    except (MailDeliveryError, CodeRequestLimitError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.profile", setup_email=1))
    session["pending_email"] = email
    write_audit_log("auth_email_verification_requested")
    flash(f"驗證碼已寄至 {email}，請至信箱查看。", "success")
    return redirect(url_for("auth.profile", setup_email=1, verify_email=1))


@auth_bp.post("/profile/email/verify")
@login_required
def verify_email():
    code = request.form.get("code", "").strip()
    if not re.fullmatch(r"\d{6}", code) or not (email := _consume_code(session["ID"], "verify_email", code)):
        flash("驗證碼無效、已過期或輸入次數過多。", "error")
        return redirect(url_for("auth.profile", setup_email=1, verify_email=1))
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT EmailVerifiedAt FROM Users WHERE ID = ?", (session["ID"],))
        user = cursor.fetchone()
        was_verified = bool(user and user.EmailVerifiedAt)
        cursor.execute("UPDATE Users SET Email = ?, EmailVerifiedAt = SYSDATETIMEOFFSET() WHERE ID = ?", (email, session["ID"]))
        conn.commit()
    finally:
        conn.close()
    session.pop("pending_email", None)
    write_audit_log("auth_email_verified")
    flash("Email 已完成綁定。", "success")
    if was_verified:
        return redirect(url_for("auth.profile"))
    return redirect(url_for("auth.profile", email_bound=1, redirect_home=1))


@auth_bp.post("/profile/email/resend")
@login_required
def resend_email_verification():
    email = session.get("pending_email", "")
    if not _valid_email(email):
        flash("請先輸入要綁定的 Email。", "error")
        return redirect(url_for("auth.profile", setup_email=1))
    try:
        _send_code(session["ID"], "verify_email", email)
    except (MailDeliveryError, CodeRequestLimitError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.profile", setup_email=1, verify_email=1))
    write_audit_log("auth_email_verification_resent")
    flash(f"新的驗證碼已寄至 {email}，舊驗證碼已失效。", "success")
    return redirect(url_for("auth.profile", setup_email=1, verify_email=1))


@auth_bp.post("/profile/email/unbind")
@login_required
def unbind_email():
    """Remove a verified email and invalidate any remaining account codes."""
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET Email = NULL, EmailVerifiedAt = NULL WHERE ID = ?", (session["ID"],))
        cursor.execute("""UPDATE AccountVerificationCodes SET UsedAt = SYSDATETIMEOFFSET()
                          WHERE UserID = ? AND UsedAt IS NULL""", (session["ID"],))
        conn.commit()
    finally:
        conn.close()
    session.pop("pending_email", None)
    write_audit_log("auth_email_unbound")
    flash("Email 已取消綁定。", "success")
    return redirect(url_for("auth.profile"))


@auth_bp.post("/profile/email/dismiss-suggestion")
@login_required
def dismiss_email_suggestion():
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET EmailPromptDismissedAt = SYSDATETIMEOFFSET() WHERE ID = ?", (session["ID"],))
        conn.commit()
    finally:
        conn.close()
    write_audit_log("auth_email_suggestion_dismissed")
    return redirect(url_for("bp_index.index"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        conn = get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT ID, Email, EmailVerifiedAt FROM Users WHERE UserID = ?", (user_id,))
            user = cursor.fetchone()
        finally:
            conn.close()
        if not user or not user.EmailVerifiedAt:
            flash("此帳號目前無法自行重設密碼，因無綁定 Email，請聯絡資訊室協助更改密碼。", "error")
            return redirect(url_for("auth.forgot_password"))
        try:
            _send_code(user.ID, "reset_password", user.Email)
            write_audit_log("auth_password_reset_requested", user_id=user.ID)
        except CodeRequestLimitError as exc:
            flash(str(exc), "error")
            return redirect(url_for("auth.forgot_password"))
        except MailDeliveryError:
            flash("目前無法寄送驗證碼，請稍後再試或聯絡資訊室協助處理。", "error")
            return redirect(url_for("auth.forgot_password"))
        flash("驗證碼已寄出，請至信箱查看。", "success")
        return redirect(url_for("auth.reset_password", user_id=user_id, code_sent=1))
    return render_template("forgot_password.html")


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "GET":
        return render_template(
            "reset_password.html",
            user_id=request.args.get("user_id", ""),
            code_sent=request.args.get("code_sent") == "1",
        )
    user_id = request.form.get("user_id", "").strip()
    code = request.form.get("code", "").strip()
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    if not new_password or new_password != confirm_password:
        flash("請輸入新密碼，且兩次輸入必須一致。", "error")
        return render_template("reset_password.html", user_id=user_id, code_sent=True)
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID FROM Users WHERE UserID = ?", (user_id,))
        user = cursor.fetchone()
    finally:
        conn.close()
    if not user or not re.fullmatch(r"\d{6}", code) or not _consume_code(user.ID, "reset_password", code):
        flash("驗證碼無效、已過期或輸入次數過多。", "error")
        return render_template("reset_password.html", user_id=user_id, code_sent=True)
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE Users SET Password = ? WHERE ID = ?", (generate_password_hash(new_password), user.ID))
        conn.commit()
    finally:
        conn.close()
    write_audit_log("auth_password_reset_completed", user_id=user.ID)
    flash("密碼已重設，請使用新密碼登入。", "success")
    return redirect(url_for("auth.login"))


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

            is_admin = str(getattr(user, "Position", "")).strip().lower() == "admin"
            if (current_app.config["EMAIL_VERIFICATION_ENABLED"] and not is_admin
                    and not getattr(user, "EmailVerifiedAt", None)
                    and not getattr(user, "EmailPromptDismissedAt", None)):
                return redirect(url_for("auth.profile", setup_email=1, email_suggestion=1))
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
        if str(guid_id) == str(session.get("ID")):
            conn.close()
            return jsonify({"success": False, "message": "無法刪除目前正在登入的帳號。"}), 400

        related_checks = (
            ("文件版本", "DocVersion", "Uploader"),
            ("版本比對紀錄", "MappingRecord", "Creator"),
            ("筆記轉移紀錄", "NoteTransferHistory", "UserID"),
            ("背景任務", "BackgroundTasks", "UserID"),
        )
        related_labels = []
        for label, table, column in related_checks:
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (guid_id,))
            if cursor.fetchone()[0]:
                related_labels.append(label)
        if related_labels:
            conn.close()
            return jsonify({
                "success": False,
                "message": f"此帳號已有{'、'.join(related_labels)}，為避免遺失資料，無法直接刪除。",
            }), 409

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
        cursor.execute("DELETE FROM AccountVerificationCodes WHERE UserID = ?", (guid_id,))
        cursor.execute("DELETE FROM Users WHERE ID = ?", (guid_id,))      
        conn.commit()
        conn.close()
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
