import json
import logging

from flask import request, session

from modules.db import execute_query


_SENSITIVE_FIELDS = {"password", "pwd", "token", "secret"}


def _sanitize(value):
    if isinstance(value, dict):
        return {
            key: "***" if key.lower() in _SENSITIVE_FIELDS else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value


def write_audit_log(action, detail=None, user_id=None, remote_addr=None):
    payload = json.dumps(_sanitize(detail or {}), ensure_ascii=False, default=str)
    actor = user_id if user_id is not None else session.get("ID")
    address = remote_addr if remote_addr is not None else request.remote_addr
    sql = """INSERT INTO Audit_logs ([Action], CreatedAt, User_id, Detail_json, Remote_addr)
             VALUES (?, SYSDATETIMEOFFSET(), ?, ?, ?)"""
    return execute_query(sql, (action, actor, payload, address))


def _request_detail(response):
    detail = {
        "endpoint": request.endpoint,
        "method": request.method,
        "path": request.path,
        "status_code": response.status_code,
    }
    if request.args:
        detail["query"] = request.args.to_dict(flat=False)
    if request.form:
        detail["form"] = request.form.to_dict(flat=False)
    if request.is_json:
        detail["json"] = request.get_json(silent=True)
    if request.files:
        detail["files"] = {key: [item.filename for item in values] for key, values in request.files.lists()}
    if response.status_code >= 400 and not response.direct_passthrough:
        detail["response_body"] = response.get_data(as_text=True)[:4000]
    return detail


def audit_request(response):
    endpoint = request.endpoint or "system"
    if endpoint in {"auth.login", "auth.logout", "auth.profile"}:
        return response

    if request.path == "/favicon.ico":
        return response

    if not session.get("UserID"):
        return response

    action_prefix = endpoint.replace(".", "_")
    detail = _request_detail(response)
    try:
        if response.status_code >= 400:
            write_audit_log(f"{action_prefix}_error", detail)
        elif request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            body = request.get_json(silent=True)
            submitted_action = body.get("action") if isinstance(body, dict) else request.values.get("action")
            route_action = (request.view_args or {}).get("action")
            default_operations = {
                "bp_docVersion.docVersion": "upload",
                "bp_mapping.mapping": "create",
                "bp_notes.migrate_pdf_api": "migrate",
                "notes_bp.upload_pdf": "upload",
            }
            operation = submitted_action or route_action or default_operations.get(endpoint) or request.method.lower()
            operation = str(operation).strip().lower()
            write_audit_log(f"{action_prefix}_{operation}", detail)
        elif "attachment" in response.headers.get("Content-Disposition", "").lower():
            write_audit_log(f"{action_prefix}_download", detail)
    except Exception:
        logging.exception("Audit log write failed")
    return response
