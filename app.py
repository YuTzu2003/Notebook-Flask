import logging
import traceback
import uuid
import os
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from modules.db import execute_query
from modules.auth import auth_bp
from modules.annotation_edit import notes_bp
from service.bp_index import bp_index
from service.bp_edit import bp_edit
from service.bp_docVersion import bp_docVersion
from service.bp_mapping import bp_mapping
from service.bp_notes import bp_notes
from modules.backup import run_database_backup
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
from waitress import serve

logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s',datefmt='%Y-%m-%d %H:%M:%S')
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True  # 前端每次都重新讀取，不用重啟伺服器

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e      
    error_code = str(uuid.uuid4()).split('-')[0]
    error_msg = str(e)
    tb = traceback.format_exc()
    sql = "INSERT INTO ErrorLogs (ErrorCode, ErrorMessage, Traceback, CreatedAt) VALUES (?, ?, ?, GETDATE())"
    execute_query(sql, (error_code, error_msg, tb))
    if request.path.startswith('/admin/manage_user') or request.path.startswith('/doc_tool') or request.path.startswith('/mapping_tool') or request.path.startswith('/notes_tool') or request.path.startswith('/annotation'):
        return jsonify({"success": False, "message": f"發生錯誤，錯誤代碼：{error_code}，請聯絡資訊人員。"}), 500
    return f"<script>alert('發生錯誤，錯誤代碼：{error_code}，請聯絡資訊人員。'); window.history.back();</script>", 500

app.secret_key = "replace-with-a-secret-key"
app.register_blueprint(auth_bp)
app.register_blueprint(notes_bp)
app.register_blueprint(bp_index)
app.register_blueprint(bp_edit)
app.register_blueprint(bp_docVersion)
app.register_blueprint(bp_mapping)
app.register_blueprint(bp_notes)

# 資料備份排程器 (設定為每天凌晨 2:00 執行備份)
scheduler = BackgroundScheduler()
scheduler.add_job(func=run_database_backup, trigger="cron", hour=2, minute=0, id='db_backup_job', replace_existing=True)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())
logging.info("APScheduler is running: Automatic database backup is performed daily at 02:00.")

if __name__ == "__main__":
    flask_port = int(os.environ.get("FLASK_PORT", 5000))
    logging.info(f"Waitress server starting on port {flask_port}...")
    serve(app, host="0.0.0.0", port=flask_port, threads=30)