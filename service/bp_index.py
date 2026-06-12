from flask import Blueprint, render_template, request, jsonify, session
import os
import json
import fitz
from modules.auth import login_required
from modules.db import execute_query

bp_index = Blueprint('bp_index', __name__)

UPLOAD_Folder = "static/uploads"
NOTE_Folder = "static/annotation"

@bp_index.route("/")
@login_required
def index():
    user_id = session.get("ID")
    sql = """SELECT DocID, OriginalName, UploadTime, Pages FROM Documents  WHERE User_ID = ? ORDER BY UploadTime DESC"""
    documents = execute_query(sql, (user_id,))
    return render_template("index.html", documents=documents)

@bp_index.route("/doc_tool", methods=["POST"])
@login_required
def doc_tool():
    try:
        data = request.json
        action, doc_id = data.get("action"), data.get("doc_id")
        user_id = session.get("ID")
        rows = execute_query("SELECT * FROM Documents WHERE DocID = ? AND User_ID = ?", (doc_id, user_id))
        doc_info = rows[0]

        pdf_path = f"{UPLOAD_Folder}/{doc_info['StorageName']}"
        json_path = f"{NOTE_Folder}/{doc_id}.json"

        if action == "delete":
            if execute_query("DELETE FROM Documents WHERE DocID = ? AND User_ID = ?", (doc_id, user_id)):
                for path in [pdf_path, json_path]:
                    if os.path.exists(path): os.remove(path)
                return jsonify({"success": True, "message": "刪除成功"})
            return jsonify({"success": False, "message": "刪除失敗"}), 500

        elif action == "edit":
            with fitz.open(pdf_path) as doc:
                width, height = doc[0].rect.width, doc[0].rect.height
                has_toc = len(doc.get_toc()) > 0

            mods = {}
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as jf:
                        content = jf.read().strip()
                        if content:
                            mods = json.loads(content)
                except Exception:
                    pass

            return jsonify({
                "success": True,
                "data": {
                    "doc_id": doc_id,
                    "pdf_name": doc_info['StorageName'],
                    "original_name": doc_info['OriginalName'],
                    "total_pages": doc_info['Pages'],
                    "width": width,
                    "height": height,
                    "mods": mods,
                    "has_toc": has_toc
                }
            })
            
        return jsonify({"success": False, "message": "未知的操作指令"}), 400
        
    except Exception as e:
        print(f"doc_tool Error: {e}")
        return jsonify({"success": False, "message": f"error: {str(e)}"}), 500