from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, send_from_directory
import os
import uuid
from modules.auth import login_required
from modules.db import execute_query, fetch_all
from modules.mapping import UseMapping

bp_mapping = Blueprint('bp_mapping', __name__)

VERSION_Folder = 'static/docVersion'
Mapping_Folder = "static/docMapResult"
Note_Folder = 'static/note'

@bp_mapping.route("/mapping", methods=["GET"])
def mapping_page():
    sql = "SELECT ID,FileName,Version FROM DocVersion ORDER BY UploadTime DESC"
    docVersion = fetch_all(sql)
    sql_history = """
                    SELECT  MappingRecord.RecordID, Users.Name, DocVersion_Old.FileName AS OldFileName, DocVersion_Old.Version AS OldVersion, 
                            DocVersion_New.FileName AS NewFileName, DocVersion_New.Version AS NewVersion,MappingRecord.ResultName,MappingRecord.Status, dbo.MappingRecord.CreateTime, 
                            MappingRecord.IsPublish
                    FROM MappingRecord INNER JOIN Users ON MappingRecord.Creator = Users.ID 
                    LEFT OUTER JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID 
                    LEFT OUTER JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
                    ORDER BY dbo.MappingRecord.CreateTime ASC
                """
    history = fetch_all(sql_history)
    return render_template('mapping.html',files=docVersion,history=history)

@bp_mapping.route("/mapping/doc_mapping", methods=["POST"])
def doc_mapping():

    old_id = request.form.get("old_pdf_id")
    new_id = request.form.get("new_pdf_id")
    creator = session.get("ID")

    doc_files_sql = "SELECT ID, FileName FROM DocVersion WHERE ID IN (?, ?)"
    files = fetch_all(doc_files_sql, (old_id, new_id))
    file_map = {str(row['ID']): row['FileName'] for row in files}

    if str(old_id) not in file_map or str(new_id) not in file_map:
        flash("找不到指定的PDF", "error")
        return redirect(url_for('bp_mapping.mapping_page'))


    old_pdf_path = f"{VERSION_Folder}/{file_map[str(old_id)]}"
    new_pdf_path = f"{VERSION_Folder}/{file_map[str(new_id)]}"
    
    unique_id = str(uuid.uuid4())
    project_folder = f"{Mapping_Folder}/{unique_id}"
    os.makedirs(project_folder, exist_ok=True)
    
    csv_filename = f"{unique_id}/{unique_id}.csv"
    diff_pdf_filename = f"{unique_id}/{unique_id}_diff.pdf"

    csv_result = f"{Mapping_Folder}/{csv_filename}"
    diff_pdf_path = f"{Mapping_Folder}/{diff_pdf_filename}"
    
    result_df, diff_pages = UseMapping(old_pdf_path, new_pdf_path, csv_result, diff_pdf_path)

    is_success = 1 if not result_df.empty else 0
    diff_pages_str = ",".join(map(str, diff_pages)) if diff_pages else ""

    sql = """INSERT INTO MappingRecord (OldDocID, NewDocID, ResultName, Creator, Status, IsPublish, DiffPages, DiffPdfName) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
    params = (
        old_id,
        new_id,
        csv_filename, 
        creator,
        is_success,
        1,
        diff_pages_str,
        diff_pdf_filename
    )

    if execute_query(sql, params):
        return jsonify({"status": "success", "message": "版本比對完成！"})
    else:
        return jsonify({"status": "error", "message": "比對過程中發生資料庫錯誤"})

@bp_mapping.route("/mapping_tool", methods=["POST"])
@login_required
def mapping_tool():
    data = request.json
    action = data.get("action")
    record_id = data.get("record_id")

    if action == "delete":
        sql_find_history = "SELECT ResultName FROM NoteTransferHistory WHERE MappingID = ?"
        history_files = fetch_all(sql_find_history, (record_id,))
        
        for h in history_files:
            h_path = os.path.join(Note_Folder, h['ResultName'])
            if os.path.exists(h_path):
                os.remove(h_path) 
        
        execute_query("DELETE FROM NoteTransferHistory WHERE MappingID = ?", (record_id,))

        sql_select_mapping = "SELECT ResultName FROM MappingRecord WHERE RecordID = ?"
        mapping_result = fetch_all(sql_select_mapping, (record_id,))
        
        if mapping_result:
            csv_filename = mapping_result[0]["ResultName"]
            csv_path = os.path.join(Mapping_Folder, csv_filename)
            if os.path.exists(csv_path):
                os.remove(csv_path) 

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
        sql = """
            SELECT DocVersion_Old.FileName AS OldFileName, DocVersion_New.FileName AS NewFileName
            FROM MappingRecord
            LEFT JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID
            LEFT JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
            WHERE MappingRecord.RecordID = ?
        """
        result = fetch_all(sql, (record_id,))[0]
        pdf_name = result["OldFileName"] if pdf_type == "old" else result["NewFileName"]
        return send_from_directory(VERSION_Folder, pdf_name, as_attachment=False)

    elif action == "download":
        sql = "SELECT ResultName FROM MappingRecord WHERE RecordID = ?"
        result = fetch_all(sql, (record_id,))
        if result and result[0]['ResultName']:
            rel_path = result[0]['ResultName']
            folder = os.path.join(Mapping_Folder, os.path.dirname(rel_path))
            filename = os.path.basename(rel_path)
            return send_from_directory(folder, filename, as_attachment=True, download_name=filename)
        return "找不到檔案", 404

    elif action == "download_diff":
        sql = "SELECT DiffPdfName FROM MappingRecord WHERE RecordID = ?"
        result = fetch_all(sql, (record_id,))
        if result and result[0]['DiffPdfName']:
            rel_path = result[0]['DiffPdfName']
            folder = os.path.join(Mapping_Folder, os.path.dirname(rel_path))
            filename = os.path.basename(rel_path)
            return send_from_directory(folder, filename, as_attachment=True, download_name="差異比對結果.pdf")
        return "找不到差異檔案", 404
    
    elif action == "load_csv":
        csv_name = request.form.get("csv_name")
        file_path = os.path.join(Mapping_Folder, csv_name)
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        return "找不到 CSV", 404
