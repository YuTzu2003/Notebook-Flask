import io
import zipfile

from flask import Blueprint, render_template, request, jsonify, send_file, session, send_from_directory, current_app
import os
import uuid
import shutil
from modules.auth import login_required
from modules.db import execute_query
from modules.move_annotation.pdf_annotation_migrate import migrate_all_to_pdf
import threading
import time
import os

migrate_semaphore = threading.Semaphore(3)
bp_notes = Blueprint('bp_notes', __name__)
VERSION_Folder = 'static/docVersion'
Mapping_Folder = "static/docMapResult"
Note_Folder = 'static/note'

def run_migrate_background(app, transfer_id, old_pdf_path, new_pdf_path, csv_mapping, output_pdf, diff_pages_str, output_filename):
    with app.app_context():
        migrate_semaphore.acquire()
        try:
            migrate_all_to_pdf(old_pdf=old_pdf_path,new_pdf=new_pdf_path,csv_mapping=csv_mapping,output_pdf=output_pdf,diff_pages_str=diff_pages_str)
            time.sleep(1.5)
            sql = "UPDATE Hospital.dbo.NoteTransferHistory SET ResultName = ? WHERE TransferID = ?"
            execute_query(sql, (output_filename, transfer_id))
            
        except Exception as e:
            print("Background Migrate Error:", e)
            sql = "UPDATE Hospital.dbo.NoteTransferHistory SET ResultName = 'ERROR' WHERE TransferID = ?"
            execute_query(sql, (transfer_id,))
        finally:
            migrate_semaphore.release()

@bp_notes.route("/notes", methods=["GET"])
@login_required
def notes_page():
    user_id = session.get("ID")
    sort_by = request.args.get('sort_by', 'CreateTime')   
    sort_map = {
        'SourceFileName': {'col': 'H.SourceFileName', 'dir': 'ASC'},
        'Version':        {'col': 'V_Old.Version',    'dir': 'ASC'},
        'CreateTime':     {'col': 'H.CreateTime',     'dir': 'DESC'}
    }
    
    config = sort_map.get(sort_by, sort_map['CreateTime'])
    order_col = config['col']
    order_dir = config['dir']

    sql_mapping = """SELECT M.RecordID, V1.Version AS OldVersion, V2.Version AS NewVersion FROM MappingRecord M
                    JOIN DocVersion V1 ON M.OldDocID = V1.ID
                    JOIN DocVersion V2 ON M.NewDocID = V2.ID
                    WHERE M.IsPublish = 1"""
    mapping_history = execute_query(sql_mapping)
    
    sql_history = f"""SELECT H.TransferID, H.SourceFileName,H.ResultName,H.CreateTime,V_Old.Version AS OldV, V_New.Version AS NewV
                    FROM Hospital.dbo.NoteTransferHistory H
                    LEFT JOIN MappingRecord M ON H.MappingID = M.RecordID
                    LEFT JOIN DocVersion V_Old ON M.OldDocID = V_Old.ID
                    LEFT JOIN DocVersion V_New ON M.NewDocID = V_New.ID
                    WHERE H.UserID = ?
                    ORDER BY {order_col} {order_dir}
                """
    history = execute_query(sql_history, (user_id,))
    return render_template("notes.html", mapping_history=mapping_history, history=history,current_sort=sort_by)


@bp_notes.route("/annotation/migrate_pdf", methods=["POST"])
def migrate_pdf_api():
    try:
        pdf_with_notes = request.files["old_pdf"]
        mapping_id = request.form.get("mapping_id")
        user_id = session.get("ID")

        if not mapping_id:
            return jsonify({"status": "error", "message": "未選擇版本比對紀錄"})

        sql = """SELECT MappingRecord.NewDocID,MappingRecord.DiffPages AS diff_pages FROM MappingRecord WHERE MappingRecord.RecordID = ?"""
        TransferID = "note" + uuid.uuid4().hex[:8]
        row = execute_query(sql, (mapping_id,))[0]
        target_new_pdf_path = os.path.join(VERSION_Folder, f"{row['NewDocID']}.pdf")
        mapping_csv_path = os.path.join(Mapping_Folder, mapping_id, f"{mapping_id}.csv")
        diff_pages_str = row.get('diff_pages', '')

        note_dir = os.path.join("static/note", TransferID if TransferID.startswith("note") else f"note{TransferID}")
        os.makedirs(note_dir, exist_ok=True)
        
        original_filename = pdf_with_notes.filename
        user_pdf_path = os.path.join(note_dir, original_filename)
        pdf_with_notes.save(user_pdf_path)

        output_filename = f"Move_{original_filename}"
        output_path = os.path.join(note_dir, output_filename)

        # 先寫入資料庫，標記為 PROCESSING
        sql_insert = """INSERT INTO Hospital.dbo.NoteTransferHistory (TransferID, UserID, MappingID, SourceFileName, ResultName) VALUES (?, ?, ?, ?, ?)"""
        execute_query(sql_insert, (TransferID, user_id, mapping_id, pdf_with_notes.filename, 'PROCESSING'))

        app_obj = current_app._get_current_object()
        thread = threading.Thread(target=run_migrate_background, args=(app_obj, TransferID, user_pdf_path, target_new_pdf_path, mapping_csv_path, output_path, diff_pages_str, output_filename))
        thread.start()
        return jsonify({"status": "success", "message": "開始執行！"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
  
@bp_notes.route("/notes/action", methods=["GET", "POST"])
@login_required
def notes_action():
    if request.method == "GET":
        action = request.args.get("action")
        if action == "download_pdf":
            filename = request.args.get("filename")
            sql = """SELECT SourceFileName, TransferID FROM Hospital.dbo.NoteTransferHistory WHERE ResultName = ?"""
            result = execute_query(sql, (filename,))

            if result:
                source_file_name = result[0]['SourceFileName']
                transfer_id = result[0]['TransferID']
                base_name = os.path.splitext(source_file_name)[0]
                note_dir = os.path.join(current_app.root_path, "static/note", transfer_id if transfer_id.startswith("note") else f"note{transfer_id}")
                download_name = filename if filename.startswith("Move_") else f"{base_name}_Move.pdf"
                
                return send_from_directory(note_dir, filename, as_attachment=True, download_name=download_name)
            return "File not found", 404
        return "Bad Request", 400

    elif request.method == "POST":
        user_id = session.get("ID")
        if request.is_json:
            data = request.json
            action = data.get("action")
            transfer_id = data.get("transfer_id")
            
            if action == "delete":
                sql = "SELECT TransferID,ResultName FROM NoteTransferHistory WHERE TransferID = ? AND UserID = ?"
                res = execute_query(sql, (transfer_id, user_id))
                
                if res:
                    if execute_query("DELETE FROM NoteTransferHistory WHERE TransferID = ? AND UserID = ?", (transfer_id, user_id)):
                        note_dir = os.path.join(current_app.root_path, "static/note", transfer_id if transfer_id.startswith("note") else f"note{transfer_id}")
                        if os.path.exists(note_dir):
                            shutil.rmtree(note_dir)
                        return jsonify({"success": True, "message": "刪除成功"})
                return jsonify({"success": False, "message": "刪除失敗"}), 500
            
        else:
            action = request.form.get("action")
            transfer_ids = request.form.getlist("doc_ids")
            
            if action == "batch_delete":
                success_count = 0
                for tid in transfer_ids:
                    sql = "SELECT TransferID,ResultName FROM NoteTransferHistory WHERE TransferID = ? AND UserID = ?"
                    res = execute_query(sql, (tid, user_id))
                    if res:
                        if execute_query("DELETE FROM NoteTransferHistory WHERE TransferID = ? AND UserID = ?", (tid, user_id)):
                            note_dir = os.path.join(current_app.root_path, "static/note", tid if tid.startswith("note") else f"note{tid}")
                            if os.path.exists(note_dir):
                                shutil.rmtree(note_dir)
                            success_count += 1
                from flask import flash, redirect, url_for
                flash(f'成功刪除 {success_count} 筆紀錄', 'success')
                return redirect(url_for('bp_notes.notes_page'))

            elif action == "batch_download":
                memory_file = io.BytesIO()
                with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for tid in transfer_ids:
                        sql = "SELECT SourceFileName, ResultName FROM NoteTransferHistory WHERE TransferID = ? AND UserID = ?"
                        res = execute_query(sql, (tid, user_id))
                        if res:
                            source_file_name = res[0]['SourceFileName']
                            result_name = res[0]['ResultName']
                            if result_name and result_name not in ['PROCESSING', 'ERROR']:
                                base_name = os.path.splitext(source_file_name)[0]
                                download_name = result_name if result_name.startswith("Move_") else f"{base_name}_Move.pdf"
                                note_dir = os.path.join(current_app.root_path, "static/note", tid if tid.startswith("note") else f"note{tid}")
                                file_path = os.path.join(note_dir, result_name)
                                if os.path.exists(file_path):
                                    zf.write(file_path, download_name)
                memory_file.seek(0)
                return send_file(memory_file,mimetype='application/zip',as_attachment=True,download_name='batch_notes_download.zip')         
            return redirect(url_for('bp_notes.notes_page'))

@bp_notes.route("/notes/status/<transfer_id>", methods=["GET"])
@login_required
def notes_status(transfer_id):
    sql = "SELECT ResultName FROM Hospital.dbo.NoteTransferHistory WHERE TransferID = ?"
    result = execute_query(sql, (transfer_id,))
    if result:
        return jsonify({"success": True, "ResultName": result[0]["ResultName"]})
    return jsonify({"success": False}), 404