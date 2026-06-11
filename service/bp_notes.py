from flask import Blueprint, render_template, request, jsonify, session, send_from_directory, current_app
import os
import uuid
from modules.auth import login_required
from modules.db import execute_query, fetch_all
from modules.pdf_annotation_migrate import migrate_all_to_pdf

bp_notes = Blueprint('bp_notes', __name__)

VERSION_Folder = 'static/docVersion'
Mapping_Folder = "static/docMapResult"
Note_Folder = 'static/note'
Note_Upload = 'static/note/upload'
Note_Transfer = 'static/note/Transfer'

@bp_notes.route("/notes", methods=["GET"])
@login_required
def notes_page():
    user_id = session.get("ID")
    sort_by = request.args.get('sort_by', 'CreateTime')   
    sort_map = {
        'SourceFileName': {'col': 'H.SourceFileName', 'dir': 'ASC'},
        'Version':        {'col': 'V_Old.Version',    'dir': 'ASC'},
        'CreateTime':     {'col': 'H.CreateTime',     'dir': 'ASC'}
    }
    
    config = sort_map.get(sort_by, sort_map['CreateTime'])
    order_col = config['col']
    order_dir = config['dir']

    sql_mapping = """
        SELECT M.RecordID, V1.Version AS OldVersion, V2.Version AS NewVersion 
        FROM MappingRecord M
        JOIN DocVersion V1 ON M.OldDocID = V1.ID
        JOIN DocVersion V2 ON M.NewDocID = V2.ID
        WHERE M.IsPublish = 1
    """
    mapping_history = fetch_all(sql_mapping)
    
    sql_history = f"""
        SELECT 
            H.TransferID, H.SourceFileName, H.ResultName, H.CreateTime,
            V_Old.Version AS OldV, V_New.Version AS NewV
        FROM Hospital.dbo.NoteTransferHistory H
        LEFT JOIN MappingRecord M ON H.MappingID = M.RecordID
        LEFT JOIN DocVersion V_Old ON M.OldDocID = V_Old.ID
        LEFT JOIN DocVersion V_New ON M.NewDocID = V_New.ID
        WHERE H.UserID = ?
        ORDER BY {order_col} {order_dir}
    """
    history = fetch_all(sql_history, (user_id,))
    
    return render_template("notes.html", mapping_history=mapping_history, history=history,current_sort=sort_by)


@bp_notes.route("/annotation/migrate_pdf", methods=["POST"])
def migrate_pdf_api():
    try:
        pdf_with_notes = request.files["old_pdf"]
        mapping_id = request.form.get("mapping_id")
        user_id = session.get("ID")

        if not mapping_id:
            return jsonify({"status": "error", "message": "未選擇版本比對紀錄"})

        sql = """
        SELECT 
            MappingRecord.NewDocID,
            MappingRecord.DiffPages AS diff_pages
        FROM MappingRecord
        WHERE MappingRecord.RecordID = ?
        """

        TransferID = str(uuid.uuid4())
        row = fetch_all(sql, (mapping_id,))[0]

        # 根據要求，使用乾淨的新版 PDF 作為底本
        target_new_pdf_path = os.path.join(VERSION_Folder, f"{row['NewDocID']}.pdf")
        mapping_csv_path = os.path.join(Mapping_Folder, mapping_id, f"{mapping_id}.csv")
        diff_pages_str = row.get('diff_pages', '')

        os.makedirs(Note_Folder, exist_ok=True)
        os.makedirs(Note_Upload, exist_ok=True)
        os.makedirs(Note_Transfer, exist_ok=True)
        user_pdf_path = f"{Note_Upload}/{TransferID}.pdf"
        pdf_with_notes.save(user_pdf_path)

        output_filename =  f"{TransferID}_Move.pdf"
        output_path = f"{Note_Transfer}/{output_filename}"

        migrate_all_to_pdf(
            old_pdf=user_pdf_path,           
            new_pdf=target_new_pdf_path,     
            csv_mapping=mapping_csv_path,    
            output_pdf=output_path,
            diff_pages_str=diff_pages_str
        )

        user_id = session.get("ID") 
        sql_insert = """
            INSERT INTO Hospital.dbo.NoteTransferHistory (TransferID, UserID, MappingID, SourceFileName,ResultName)
            VALUES (?, ?, ?, ?, ?)
        """
        execute_query(sql_insert, (TransferID, user_id, mapping_id, pdf_with_notes.filename, output_filename))

        return jsonify({"status": "success", "filename": output_filename})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
  
@bp_notes.route("/annotation/migrate_existing_json", methods=["POST"])
def migrate_existing_json():
    try:
        json_filename = request.form.get("json_filename")
        mapping_id = request.form.get("mapping_id")

        if not json_filename or not mapping_id:
            return jsonify({"status": "error", "message": "缺少資料"})

        sql = """
        SELECT 
            MappingRecord.OldDocID, 
            MappingRecord.NewDocID
        FROM MappingRecord
        WHERE MappingRecord.RecordID = ?
        """
        row = fetch_all(sql, (mapping_id,))
        if not row:
            return jsonify({"status": "error", "message": "找不到比對紀錄"})

        row = row[0]

        old_pdf_path = os.path.join(VERSION_Folder, f"{row['OldDocID']}.pdf")
        new_pdf_path = os.path.join(VERSION_Folder, f"{row['NewDocID']}.pdf")
        mapping_csv_path = os.path.join(Mapping_Folder, mapping_id, f"{mapping_id}.csv")

        json_path = os.path.join(current_app.root_path, "static", "annotation", json_filename)

        name, ext = os.path.splitext(json_filename)
        new_json_name = f"{name}_轉移{ext}"
        output_json_path = os.path.join(current_app.root_path, "static", "annotation", new_json_name)

        '''
        migrate_with_json_output(
            old_pdf_path,
            new_pdf_path,
            json_path,
            mapping_csv_path,
            None,
            output_json_path
        )
        '''
        
        return jsonify({
            "status": "success",
            "json_filename": new_json_name
        })

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"status": "error", "message": str(e)})
    
@bp_notes.route('/download_pdf/<filename>')
@login_required 
def download_pdf(filename):
    sql = """SELECT SourceFileName FROM Hospital.dbo.NoteTransferHistory WHERE ResultName = ?"""
    result = fetch_all(sql, (filename,))

    if result:
        source_file_name = result[0]['SourceFileName']
        base_name = os.path.splitext(source_file_name)[0]

    return send_from_directory(Note_Transfer,filename, as_attachment=True,download_name=f"{base_name}_Move.pdf")


@bp_notes.route("/notes_tool", methods=["POST"])
@login_required
def notes_tool():
    data = request.json
    action = data.get("action")
    transfer_id = data.get("transfer_id")
    user_id = session.get("ID")

    if action == "delete":
        sql = "SELECT TransferID,ResultName FROM NoteTransferHistory WHERE TransferID = ? AND UserID = ?"
        res = fetch_all(sql, (transfer_id, user_id))
        
        if res:
            if execute_query("DELETE FROM NoteTransferHistory WHERE TransferID = ? AND UserID = ?", (transfer_id, user_id)):
                
                pdf_upload = f"{Note_Upload}/{res[0]['TransferID']}.pdf"
                if os.path.exists(pdf_upload):
                    os.remove(pdf_upload)
                
                pdf_Transfer = f"{Note_Transfer}/{res[0]['TransferID']}_Move.pdf"
                if os.path.exists(pdf_Transfer):
                    os.remove(pdf_Transfer)

                return jsonify({"success": True, "message": "刪除成功"})
        
        return jsonify({"success": False, "message": "刪除失敗"}), 500
    
    return jsonify({"success": False, "message": "無效操作"}), 400
