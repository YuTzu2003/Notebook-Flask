import atexit
import logging
import traceback
import uuid
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request
from waitress import serve
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from config import get_settings
from modules.annotation_edit import notes_bp
from modules.auth import auth_bp
from modules.backup import run_database_backup
from modules.db import execute_query
from service.bp_docVersion import bp_docVersion
from service.bp_edit import bp_edit
from service.bp_index import bp_index
from service.bp_mapping import bp_mapping
from service.bp_notes import bp_notes


logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(message)s",datefmt="%Y-%m-%d %H:%M:%S",)

def create_app():
    app = Flask(__name__)
    app.config.from_mapping(get_settings())

    proxy_count = app.config["PROXY_COUNT"]
    if proxy_count:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_count, x_proto=proxy_count, x_host=proxy_count, x_port=proxy_count,)

    @app.errorhandler(Exception)
    def handle_exception(error):
        if isinstance(error, HTTPException):
            return error

        error_code = str(uuid.uuid4()).split("-")[0]
        traceback_text = traceback.format_exc()
        sql = "INSERT INTO ErrorLogs (ErrorCode, ErrorMessage, Traceback, CreatedAt) VALUES (?, ?, ?, GETDATE())"
        execute_query(sql, (error_code, str(error), traceback_text))
        logging.error("Unhandled error %s\n%s", error_code, traceback_text)

        api_prefixes = (
            "/admin/manage_user",
            "/doc_tool",
            "/mapping_tool",
            "/notes_tool",
            "/annotation",
        )
        if request.path.startswith(api_prefixes):
            return jsonify({"success": False, "message": f"系統錯誤，錯誤代碼：{error_code}"}), 500
        return f"<script>alert('系統錯誤，錯誤代碼：{error_code}'); window.history.back();</script>", 500

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "environment": app.config["APP_ENV"]})

    app.register_blueprint(auth_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(bp_index)
    app.register_blueprint(bp_edit)
    app.register_blueprint(bp_docVersion)
    app.register_blueprint(bp_mapping)
    app.register_blueprint(bp_notes)

    if app.config["ENABLE_SCHEDULER"]:
        scheduler = BackgroundScheduler()
        scheduler.add_job(func=run_database_backup, trigger="cron", hour=2, minute=0, id="db_backup_job",replace_existing=True,)
        scheduler.start()
        app.extensions["backup_scheduler"] = scheduler
        atexit.register(lambda: scheduler.shutdown(wait=False))
        logging.info("Automatic database backup is scheduled daily at 02:00.")
    return app

app = create_app()

if __name__ == "__main__":
    if app.config["APP_ENV"] == "development":
        app.run( host="0.0.0.0", port=50001, debug=app.config["DEBUG"],)
    else:
        logging.info("Waitress server starting on 0.0.0.0:50001")
        serve(app,host="0.0.0.0",port=50001,threads=app.config["WAITRESS_THREADS"],trusted_proxy=app.config["TRUSTED_PROXY"],
            trusted_proxy_headers={
                "x-forwarded-for",
                "x-forwarded-host",
                "x-forwarded-proto",
                "x-forwarded-port",
            },
            clear_untrusted_proxy_headers=True,
        )