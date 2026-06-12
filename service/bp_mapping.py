from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, send_from_directory, current_app
import os
import uuid
from modules.auth import login_required
from modules.db import execute_query
from modules.mapping import UseMapping
import threading

bp_mapping = Blueprint('bp_mapping', __name__)
VERSION_Folder = 'static/docVersion'
Mapping_Folder = "static/docMapResult"
Note_Folder = 'static/note'

@bp_mapping.route("/mapping", methods=["GET"])
def mapping_page():
    sql = "SELECT ID,FileName,Version FROM DocVersion ORDER BY UploadTime DESC"
    docVersion = execute_query(sql)
    sql_history = """
                    SELECT  MappingRecord.RecordID, Users.Name, DocVersion_Old.FileName AS OldFileName, DocVersion_Old.Version AS OldVersion, 
                            DocVersion_New.FileName AS NewFileName, DocVersion_New.Version AS NewVersion,MappingRecord.Status, dbo.MappingRecord.CreateTime, 
                            MappingRecord.IsPublish, MappingRecord.DiffPages
                    FROM MappingRecord INNER JOIN Users ON MappingRecord.Creator = Users.ID 
                    LEFT OUTER JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID 
                    LEFT OUTER JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
                    ORDER BY dbo.MappingRecord.CreateTime DESC
                """
    history = execute_query(sql_history)
    return render_template('mapping.html',files=docVersion,history=history)


mapping_semaphore = threading.Semaphore(3)

def run_mapping_background(app, record_id, old_pdf_path, new_pdf_path, csv_result, diff_pdf_path):
    with app.app_context():
        mapping_semaphore.acquire()
        try:
            result_df, diff_pages = UseMapping(old_pdf_path, new_pdf_path, csv_result, diff_pdf_path)
            is_success = 1 if not result_df.empty else 0
            diff_pages_str = ",".join(map(str, diff_pages)) if diff_pages else ""
            
            if is_success == 1:
                sql = "UPDATE MappingRecord SET Status = ?, DiffPages = ?, IsPublish = 1 WHERE RecordID = ?"
            else:
                sql = "UPDATE MappingRecord SET Status = ?, DiffPages = ? WHERE RecordID = ?"
            execute_query(sql, (is_success, diff_pages_str, record_id))
        except Exception as e:
            print("Background Mapping Error:", e)

            sql = "UPDATE MappingRecord SET Status = 0, DiffPages = 'ERROR' WHERE RecordID = ?"
            execute_query(sql, (record_id,))
        finally:
            mapping_semaphore.release()

@bp_mapping.route("/mapping/doc_mapping", methods=["POST"])
def doc_mapping():
    old_id = request.form.get("old_pdf_id")
    new_id = request.form.get("new_pdf_id")
    creator = session.get("ID")

    doc_files_sql = "SELECT ID, FileName FROM DocVersion WHERE ID IN (?, ?)"
    files = execute_query(doc_files_sql, (old_id, new_id))
    file_map = {str(row['ID']): row['FileName'] for row in files}

    if str(old_id) not in file_map or str(new_id) not in file_map:
        flash("找不到指定的PDF", "error")
        return redirect(url_for('bp_mapping.mapping_page'))

    old_pdf_path = f"{VERSION_Folder}/{old_id}.pdf"
    new_pdf_path = f"{VERSION_Folder}/{new_id}.pdf"

    record_id = "map" + uuid.uuid4().hex[:8]
    project_folder = f"{current_app.root_path}/{Mapping_Folder}/{record_id}"
    os.makedirs(project_folder, exist_ok=True)
    
    csv_result = f"{project_folder}/{record_id}.csv"
    diff_pdf_path = f"{project_folder}/{record_id}.pdf"

    # 先寫入資料庫，狀態為 0，DiffPages 為 'PROCESSING'
    sql = """INSERT INTO MappingRecord (RecordID, OldDocID, NewDocID, Creator, Status, IsPublish, DiffPages) VALUES (?, ?, ?, ?, ?, ?, ?)"""
    params = (record_id, old_id, new_id, creator, 0, 0, 'PROCESSING')
    
    if execute_query(sql, params):
        app_obj = current_app._get_current_object()
        thread = threading.Thread(target=run_mapping_background, args=(app_obj, record_id, old_pdf_path, new_pdf_path, csv_result, diff_pdf_path))
        thread.start()      
        return jsonify({"status": "success", "message": "版本比對開始執行！"})
    else:
        return jsonify({"status": "error", "message": "比對過程中發生錯誤"})

@bp_mapping.route("/mapping_tool", methods=["POST"])
@login_required
def mapping_tool():
    data = request.json
    action = data.get("action")
    record_id = data.get("record_id")

    if action == "delete":
        sql_find_history = "SELECT ResultName FROM NoteTransferHistory WHERE MappingID = ?"
        history_files = execute_query(sql_find_history, (record_id,))
        
        for h in history_files:
            h_path = os.path.join(Note_Folder, h['ResultName'])
            if os.path.exists(h_path):
                os.remove(h_path) 
        execute_query("DELETE FROM NoteTransferHistory WHERE MappingID = ?", (record_id,))

        project_folder = os.path.join(Mapping_Folder, record_id)
        csv_path = os.path.join(project_folder, f"{record_id}.csv")
        pdf_path = os.path.join(project_folder, f"{record_id}.pdf")
        if os.path.exists(csv_path):
            os.remove(csv_path)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if os.path.exists(project_folder) and not os.listdir(project_folder):
            os.rmdir(project_folder)

        if execute_query("DELETE FROM MappingRecord WHERE RecordID = ?", (record_id,)):
            return jsonify({"success": True, "message": "比對紀錄及其相關轉移紀錄已全數刪除"})
        
        return jsonify({"success": False, "message": "資料庫刪除失敗"}), 500

    elif action == "toggle_publish":
        publish_status = data.get("publish") 
        sql = "UPDATE MappingRecord SET IsPublish = ? WHERE RecordID = ?"
        if execute_query(sql, (publish_status, record_id)):
            return jsonify({"success": True, "message": "發布狀態已更新"})
        return jsonify({"success": False, "message": "更新失敗"}), 500
    return jsonify({"success": False, "message": "無效操作"}), 400


@bp_mapping.route("/mapping/action", methods=["POST"])
@login_required
def mapping_action():
    action = request.form.get("action")
    record_id = request.form.get("record_id")

    if action == "preview":
        pdf_type = request.form.get("type") 
        sql = """SELECT MappingRecord.OldDocID, MappingRecord.NewDocID FROM MappingRecord WHERE MappingRecord.RecordID = ?"""
        result = execute_query(sql, (record_id,))[0]
        pdf_id = result["OldDocID"] if pdf_type == "old" else result["NewDocID"]
        return send_from_directory(os.path.join(current_app.root_path, VERSION_Folder), f"{pdf_id}.pdf", as_attachment=False)

    elif action == "download":
        filename = f"{record_id}.csv"
        folder_path = os.path.join(current_app.root_path, Mapping_Folder, record_id)
        if os.path.exists(os.path.join(folder_path, filename)):
            return send_from_directory(folder_path, filename, as_attachment=True, download_name=filename)
        return send_from_directory(os.path.join(current_app.root_path, Mapping_Folder), filename, as_attachment=True, download_name=filename)

    elif action == "download_diff":
        filename = f"{record_id}.pdf"
        folder_path = os.path.join(current_app.root_path, Mapping_Folder, record_id)
        if os.path.exists(os.path.join(folder_path, filename)):
            return send_from_directory(folder_path, filename, as_attachment=True, download_name="差異比對結果.pdf")
        return send_from_directory(os.path.join(current_app.root_path, Mapping_Folder), filename, as_attachment=True, download_name="差異比對結果.pdf")
    
    elif action == "load_csv":
        csv_name = request.form.get("csv_name")
        record_id = os.path.splitext(csv_name)[0]
        
        folder_path = os.path.join(current_app.root_path, Mapping_Folder, record_id)
        file_path = os.path.join(folder_path, csv_name)
        if not os.path.exists(file_path):
            file_path = os.path.join(current_app.root_path, Mapping_Folder, csv_name)
            
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        return "找不到 CSV", 404

@bp_mapping.route("/mapping/status/<record_id>", methods=["GET"])
@login_required
def mapping_status(record_id):
    sql = "SELECT Status, DiffPages FROM MappingRecord WHERE RecordID = ?"
    result = execute_query(sql, (record_id,))
    if result:
        return jsonify({"success": True, "Status": result[0]["Status"], "DiffPages": result[0]["DiffPages"]})
    return jsonify({"success": False}), 404