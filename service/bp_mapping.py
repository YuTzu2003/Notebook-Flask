from flask import Blueprint, render_template, request, jsonify,session, flash, redirect, url_for, send_from_directory, current_app
import os
import uuid
from modules.auth import login_required
from modules.db import execute_query
from modules.mapping.mapping import UseMapping as process_and_match_pdfs
from modules.mapping.pdf_diff import highlight_and_bookmark_diffs
import threading
import json

bp_mapping = Blueprint('bp_mapping', __name__)
VERSION_Folder = 'tasks/docVersion'
Mapping_Folder = "tasks/docMapResult"
Note_Folder = 'tasks/note'

@bp_mapping.route("/mapping", methods=["GET"])
@login_required
def mapping_page():
    sql = "SELECT ID,FileName,Version FROM DocVersion ORDER BY UploadTime DESC"
    docVersion = execute_query(sql)
    sql_history = """
                    SELECT  MappingRecord.RecordID, Users.Name, DocVersion_Old.FileName AS OldFileName, DocVersion_Old.Version AS OldVersion, 
                            DocVersion_New.FileName AS NewFileName, DocVersion_New.Version AS NewVersion, MappingRecord.Status, dbo.MappingRecord.CreateTime, 
                            MappingRecord.IsPublish
                    FROM MappingRecord INNER JOIN Users ON MappingRecord.Creator = Users.ID 
                    LEFT OUTER JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID 
                    LEFT OUTER JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
                    ORDER BY dbo.MappingRecord.CreateTime DESC
                """
    history = execute_query(sql_history)
    for row in history:
        rid = row['RecordID']
        json_path = os.path.join(current_app.root_path, Mapping_Folder, rid, f"{rid}.json")
        row['DiffPages'] = 'ERROR' 
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as jf:
                    data = json.load(jf)
                    row['DiffPages'] = data.get("status", "ERROR")
            except Exception:
                pass
        else:
            if row['Status'] == 1:
                row['DiffPages'] = 'SUCCESS'
            else:
                row['DiffPages'] = 'PROCESSING'
    return render_template('mapping.html',files=docVersion,history=history)


mapping_semaphore = threading.Semaphore(3)

from modules.mapping.blank_pages import get_blanks

def run_mapping_background(app, record_id, old_pdf_path, new_pdf_path, csv_result, template_pdf_path):
    with app.app_context():
        mapping_semaphore.acquire()
        try:
            # 取得舊版與新版空白頁碼
            old_blanks = get_blanks(old_pdf_path)
            new_blanks = get_blanks(new_pdf_path)

            # 執行比對及空白頁插入
            project_folder = os.path.dirname(csv_result)
            result_df = process_and_match_pdfs(old_pdf_path, new_pdf_path, csv_result, template_pdf_path)
            content_rows = result_df[result_df['Mode'].str.contains("Local|Global", na=False)]
            mapping_dict = {
                int(row["Old_Page"]) - 1: int(row["New_Page"]) - 1
                for _, row in content_rows.iterrows()
                if row["New_Page"] is not None}

            # 差異比對
            diff_pdf_path = os.path.join(project_folder, f"{record_id}_diff.pdf")
            diff_pages, _ = highlight_and_bookmark_diffs(old_pdf_path, template_pdf_path, mapping_dict, diff_pdf_path)
            is_success = 1 if not result_df.empty else 0

            # 儲存JSON比對(空白頁碼、差異比對頁碼)
            old_id = os.path.splitext(os.path.basename(old_pdf_path))[0]
            new_id = os.path.splitext(os.path.basename(new_pdf_path))[0]
            db_files = execute_query("SELECT ID, FileName, Version FROM DocVersion WHERE ID IN (?, ?)", (old_id, new_id))
            file_info = {str(row['ID']): f"{row['FileName']} (v{row['Version']})" for row in db_files}
            old_name = file_info.get(str(old_id), f"{old_id}.pdf")
            new_name = file_info.get(str(new_id), f"{new_id}.pdf")

            meta_data = {
                "status": "SUCCESS" if is_success == 1 else "ERROR",
                "diff_pages": diff_pages,
                "files_compared": {
                    "old_pdf": old_name,
                    "new_pdf": new_name
                },
                "blank_pages": {
                    "old_blanks": old_blanks,
                    "new_blanks": new_blanks
                }
            }

            json_path = os.path.join(project_folder, f"{record_id}.json")
            with open(json_path, 'w', encoding='utf-8') as jf:
                json.dump(meta_data, jf, ensure_ascii=False, indent=4)
            
            if is_success == 1:
                sql = "UPDATE MappingRecord SET Status = ?, IsPublish = 1 WHERE RecordID = ?"
            else:
                sql = "UPDATE MappingRecord SET Status = ? WHERE RecordID = ?"
            execute_query(sql, (is_success, record_id))
        except Exception as e:
            print("Background Mapping Error:", e)
            try:
                project_folder = os.path.dirname(csv_result)
                json_path = os.path.join(project_folder, f"{record_id}.json")
                meta_data = {"status": "ERROR"}
                if os.path.exists(json_path):
                    with open(json_path, 'r', encoding='utf-8') as jf:
                        try:
                            meta_data = json.load(jf)
                        except Exception:
                            pass
                meta_data["status"] = "ERROR"
                with open(json_path, 'w', encoding='utf-8') as jf:
                    json.dump(meta_data, jf, ensure_ascii=False, indent=4)
            except Exception as je:
                print("Error updating JSON on error state:", je)
            
            sql = "UPDATE MappingRecord SET Status = 0 WHERE RecordID = ?"
            execute_query(sql, (record_id,))
        finally:
            mapping_semaphore.release()

@bp_mapping.route("/mapping/doc_mapping", methods=["POST"])
@login_required
def doc_mapping():
    old_id = request.form.get("old_pdf_id")
    new_id = request.form.get("new_pdf_id")
    creator = session.get("ID")

    doc_files_sql = "SELECT ID, FileName, Version FROM DocVersion WHERE ID IN (?, ?)"
    files = execute_query(doc_files_sql, (old_id, new_id))
    file_map = {str(row['ID']): row['FileName'] for row in files}
    file_info = {str(row['ID']): f"{row['FileName']} (v{row['Version']})" for row in files}

    if str(old_id) not in file_map or str(new_id) not in file_map:
        flash("找不到指定的PDF", "error")
        return redirect(url_for('bp_mapping.mapping_page'))

    old_pdf_path = f"{VERSION_Folder}/{old_id}.pdf"
    new_pdf_path = f"{VERSION_Folder}/{new_id}.pdf"

    record_id = "map" + uuid.uuid4().hex[:8]
    project_folder = f"{current_app.root_path}/{Mapping_Folder}/{record_id}"
    os.makedirs(project_folder, exist_ok=True)
    
    csv_result = f"{project_folder}/{record_id}.csv"
    template_pdf_path = f"{project_folder}/{record_id}_template.pdf"

    # 先寫入資料庫，狀態為 0
    sql = """INSERT INTO MappingRecord (RecordID, OldDocID, NewDocID, Creator, Status, IsPublish) VALUES (?, ?, ?, ?, ?, ?)"""
    params = (record_id, old_id, new_id, creator, 0, 0)
    
    if execute_query(sql, params):
        # 寫入初始 JSON 檔，標記狀態為 PROCESSING
        json_path = os.path.join(project_folder, f"{record_id}.json")
        old_name = file_info.get(str(old_id), f"{old_id}.pdf")
        new_name = file_info.get(str(new_id), f"{new_id}.pdf")
        meta_data = {
            "status": "PROCESSING",
            "diff_pages": [],
            "files_compared": {
                "old_pdf": old_name,
                "new_pdf": new_name
            },
            "blank_pages": {
                "old_blanks": [],
                "new_blanks": []
            }
        }
        with open(json_path, 'w', encoding='utf-8') as jf:
            json.dump(meta_data, jf, ensure_ascii=False, indent=4)

        app_obj = current_app._get_current_object()
        thread = threading.Thread(target=run_mapping_background, args=(app_obj, record_id, old_pdf_path, new_pdf_path, csv_result, template_pdf_path))
        thread.start()      
        return jsonify({"status": "success", "message": "版本比對開始執行！"})
    else:
        return jsonify({"status": "error", "message": "比對過程發生錯誤"})

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
        template_pdf_path = os.path.join(project_folder, f"{record_id}_template.pdf")
        json_path = os.path.join(project_folder, f"{record_id}.json")
        if os.path.exists(csv_path):
            os.remove(csv_path)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if os.path.exists(template_pdf_path):
            os.remove(template_pdf_path)
        if os.path.exists(json_path):
            os.remove(json_path)
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
        filename = f"{record_id}_diff.pdf"
        folder_path = os.path.join(current_app.root_path, Mapping_Folder, record_id)
        if os.path.exists(os.path.join(folder_path, filename)):
            return send_from_directory(folder_path, filename, as_attachment=True, download_name="差異比對結果.pdf")
        old_filename = f"{record_id}.pdf"
        if os.path.exists(os.path.join(folder_path, old_filename)):
            return send_from_directory(folder_path, old_filename, as_attachment=True, download_name="差異比對結果.pdf")
        return send_from_directory(os.path.join(current_app.root_path, Mapping_Folder), filename, as_attachment=True, download_name="差異比對結果.pdf")

    elif action == "batch_delete":
        record_ids = request.form.getlist("doc_ids")
        success_count = 0
        for rid in record_ids:
            sql_find_history = "SELECT ResultName FROM NoteTransferHistory WHERE MappingID = ?"
            history_files = execute_query(sql_find_history, (rid,))
            
            for h in history_files:
                h_path = os.path.join(Note_Folder, h['ResultName'])
                if os.path.exists(h_path):
                    os.remove(h_path) 
            execute_query("DELETE FROM NoteTransferHistory WHERE MappingID = ?", (rid,))

            project_folder = os.path.join(Mapping_Folder, rid)
            csv_path = os.path.join(project_folder, f"{rid}.csv")
            pdf_path = os.path.join(project_folder, f"{rid}.pdf")
            template_pdf_path = os.path.join(project_folder, f"{rid}_template.pdf")
            json_path = os.path.join(project_folder, f"{rid}.json")
            if os.path.exists(csv_path):
                os.remove(csv_path)
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            if os.path.exists(template_pdf_path):
                os.remove(template_pdf_path)
            if os.path.exists(json_path):
                os.remove(json_path)
            if os.path.exists(project_folder) and not os.listdir(project_folder):
                os.rmdir(project_folder)
            if execute_query("DELETE FROM MappingRecord WHERE RecordID = ?", (rid,)):
                success_count += 1
        flash(f'成功刪除 {success_count} 筆紀錄', 'success')
        return redirect(url_for('bp_mapping.mapping_page'))
     
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
        return "找不到CSV", 404

@bp_mapping.route("/mapping/status/<record_id>", methods=["GET"])
@login_required
def mapping_status(record_id):
    sql = "SELECT Status FROM MappingRecord WHERE RecordID = ?"
    result = execute_query(sql, (record_id,))
    if result:
        status_str = 'ERROR'
        rid = record_id
        json_path = os.path.join(current_app.root_path, Mapping_Folder, rid, f"{rid}.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as jf:
                    data = json.load(jf)
                    status_str = data.get("status", "ERROR")
            except Exception:
                pass
        else:
            if result[0]["Status"] == 1:
                status_str = 'SUCCESS'
            else:
                status_str = 'PROCESSING'
        return jsonify({"success": True, "Status": result[0]["Status"], "DiffPages": status_str})
    return jsonify({"success": False}), 404
