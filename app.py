import logging
import traceback
import uuid
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from modules.db import get_conn, execute_query

from modules.auth import auth_bp
from modules.annotation_edit import notes_bp
from service.bp_index import bp_index
from service.bp_edit import bp_edit
from service.bp_docVersion import bp_docVersion
from service.bp_mapping import bp_mapping
from service.bp_notes import bp_notes

logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s',datefmt='%Y-%m-%d %H:%M:%S')

app = Flask(__name__)

@app.errorhandler(Exception)
def handle_exception(e):
    # Pass through HTTP errors
    if isinstance(e, HTTPException):
        return e
        
    error_code = str(uuid.uuid4()).split('-')[0]
    error_msg = str(e)
    tb = traceback.format_exc()
    sql = "INSERT INTO ErrorLogs (ErrorCode, ErrorMessage, Traceback, CreatedAt) VALUES (?, ?, ?, GETDATE())"
    execute_query(sql, (error_code, error_msg, tb))
    if request.path.startswith('/admin/manage_user') or request.path.startswith('/doc_tool') or request.path.startswith('/mapping_tool') or request.path.startswith('/notes_tool') or request.path.startswith('/annotation'):
        return jsonify({"success": False, "message": f"發生錯誤，錯誤代碼：{error_code}，請聯絡資訊人員。"}), 500

    return f"<h3>系統發生未預期的錯誤</h3><p>錯誤代碼：<b>{error_code}</b></p><p>請將此代碼提供給資訊人員進行查修。</p>", 500

app.secret_key = "replace-with-a-secret-key"
app.register_blueprint(auth_bp)
app.register_blueprint(notes_bp)
app.register_blueprint(bp_index)
app.register_blueprint(bp_edit)
app.register_blueprint(bp_docVersion)
app.register_blueprint(bp_mapping)
app.register_blueprint(bp_notes)

if __name__ == "__main__":
    app.run(debug=True,host="0.0.0.0",port=5000)
    # app.run(host='0.0.0.0', port=80, debug=True)
    # app.run(debug=True,host="0.0.0.0",port=51000,ssl_context=('server.crt', 'server.key'))