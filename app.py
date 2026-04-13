import fitz 
import os
import json
from flask import Flask, flash, redirect, render_template, request, jsonify, send_from_directory, session, url_for
from modules.auth import auth_bp, login_required
import uuid
from modules.db import execute_query, fetch_all
from modules.annotation_edit import notes_bp
from modules.mapping import UseMapping
from modules.pdf_annotation_migrate import migrate_all_to_pdf

app = Flask(__name__)

UPLOAD_Folder = "static/uploads"
NOTE_Folder = "static/annotation"
Mapping_Folder = "static/docMapResult"
VERSION_Folder = 'static/docVersion'
Note_Folder = 'static/note'
Note_Upload = 'static/note/upload'
Note_Transfer = 'static/note/Transfer'


app.secret_key = "replace-with-a-secret-key"
app.register_blueprint(auth_bp)
app.register_blueprint(notes_bp)

@app.route("/")
@login_required
def index():
    user_id = session.get("ID")
    sql = """SELECT DocID, OriginalName, UploadTime, Pages FROM Documents  WHERE User_ID = ? ORDER BY UploadTime DESC"""
    documents = fetch_all(sql, (user_id,))
    return render_template("index.html", documents=documents)

@app.route("/edit")
@login_required
def edit_page():
    return render_template("edit.html")

@app.route("/doc_tool", methods=["POST"])
@login_required
def doc_tool():
    data = request.json
    action, doc_id = data.get("action"), data.get("doc_id")
    user_id = session.get("ID")
    rows = fetch_all("SELECT * FROM Documents WHERE DocID = ? AND User_ID = ?", (doc_id, user_id))
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
            with open(json_path, "r", encoding="utf-8") as jf:
                mods = json.load(jf)

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
    return jsonify({"success": False, "message": "error"}), 400

@app.route('/docVersion', methods=['GET', 'POST'])
def docVersion():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('未上傳檔案', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('檔案名稱為空', 'error') 
            return redirect(request.url)

        os.makedirs(VERSION_Folder, exist_ok=True)
        version = request.form.get('version')
        author = request.form.get('author')
        filename = file.filename
        file_uuid = str(uuid.uuid4())         
        file_path = f"{VERSION_Folder}/{filename}"
        file.save(file_path)
        size = os.path.getsize(file_path) # Bytes
        uploader = session.get("ID") 

        with fitz.open(file_path) as doc:
            pages = doc.page_count

        sql = """ INSERT INTO DocVersion (ID, FileName, Author, Uploader, Size, Pages, Version) VALUES (?, ?, ?, ?, ?, ?, ?) """
        data = (file_uuid, filename, author, uploader, size, pages, version)

        if execute_query(sql, data):
            flash('新增成功！', 'success')
        else:
            flash('新增失敗！', 'error')
        
        return redirect(request.url)
    
    sort_by = request.args.get('sort_by', 'UploadTime')
    sql = f"""SELECT dbo.DocVersion.*, dbo.Users.Name FROM dbo.DocVersion INNER JOIN dbo.Users ON dbo.DocVersion.Uploader = dbo.Users.ID ORDER BY {sort_by} ASC"""
    documents = fetch_all(sql)
    return render_template('docVersion.html', documents=documents, current_sort=sort_by)


@app.route('/docVersion_tool/<action>', defaults={'doc_id': None}, methods=['GET', 'POST'])
@app.route('/docVersion_tool/<action>/<doc_id>', methods=['GET', 'POST'])
def docVersion_tool(action, doc_id):
    if action == 'download':
        sql = "SELECT FileName FROM DocVersion WHERE ID = ?"
        result = fetch_all(sql, (doc_id,))
        return send_from_directory(VERSION_Folder, result[0]['FileName'], as_attachment=True)

    elif action == 'preview':
        sql = "SELECT FileName FROM DocVersion WHERE ID = ?"
        result = fetch_all(sql, (doc_id,))
        return send_from_directory(VERSION_Folder, result[0]['FileName'], as_attachment=False)

    elif action == 'delete' and request.method == 'POST':
        check_sql = """SELECT COUNT(*) AS count FROM dbo.MappingRecord WHERE OldDocID = ? OR NewDocID = ?"""
        check_result = fetch_all(check_sql, (doc_id, doc_id))
        
        if check_result and check_result[0]['count'] > 0:
            flash('該檔案存在於比對紀錄中，不可刪除！', 'error')
        else:
            sql_select = "SELECT FileName FROM DocVersion WHERE ID = ?"
            result = fetch_all(sql_select, (doc_id,))
            
            if result:
                filename = result[0]['FileName']
                file_path = f"{VERSION_Folder}/{filename}"
                
                if execute_query("DELETE FROM DocVersion WHERE ID = ?", (doc_id,)):
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    flash('刪除成功！', 'success')
                else:
                    flash('資料庫刪除失敗', 'error')
            else:
                flash('找不到該檔案', 'error')

    elif action == 'edit' and request.method == 'POST':
        edit_id = request.form.get('edit_id')
        new_filename = request.form.get('edit_filename')
        new_version = request.form.get('edit_version')
        new_author = request.form.get('edit_author')

        new_filename = new_filename.strip() 
        if not new_filename.lower().endswith('.pdf'):
            new_filename += '.pdf'

        # 從資料庫抓出舊檔名
        sql_select = "SELECT FileName FROM DocVersion WHERE ID = ?"
        result = fetch_all(sql_select, (edit_id,))
            
        old_filename = result[0]['FileName']

        if old_filename != new_filename:
            os.rename(f"{VERSION_Folder}/{old_filename}", f"{VERSION_Folder}/{new_filename}")

        sql = "UPDATE DocVersion SET FileName = ?, Version = ?, Author = ? WHERE ID = ?"
        if execute_query(sql, (new_filename, new_version, new_author, edit_id)):
            flash('更新成功！', 'success')
        else:
            flash('更新失敗！', 'error')

    else:
        flash('無效的操作', 'error')
    return redirect(url_for('docVersion'))
@app.route("/mapping", methods=["GET"])
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

@app.route("/mapping/doc_mapping", methods=["POST"])
def doc_mapping():

    old_id = request.form.get("old_pdf_id")
    new_id = request.form.get("new_pdf_id")
    creator = session.get("ID")

    doc_files_sql = "SELECT ID, FileName FROM DocVersion WHERE ID IN (?, ?)"
    files = fetch_all(doc_files_sql, (old_id, new_id))
    file_map = {str(row['ID']): row['FileName'] for row in files}

    if str(old_id) not in file_map or str(new_id) not in file_map:
        flash("找不到指定的PDF", "error")
        return redirect(url_for('mapping_page'))


    old_pdf_path = f"{VERSION_Folder}/{file_map[str(old_id)]}"
    new_pdf_path = f"{VERSION_Folder}/{file_map[str(new_id)]}"
    csv_filename = f"{uuid.uuid4()}.csv"

    os.makedirs(Mapping_Folder, exist_ok=True)
    csv_result = f"{Mapping_Folder}/{csv_filename}"
    result_df = UseMapping(old_pdf_path, new_pdf_path, csv_result)

    is_success = 1 if not result_df.empty else 0
    status_msg = "比對完成" if is_success else "比對失敗或無結果"
    flash_category = "success" if is_success else "error"

    sql = """INSERT INTO MappingRecord (OldDocID, NewDocID, ResultName, Creator, Status, IsPublish) VALUES (?, ?, ?, ?, ?, ?)"""
    params = (
        old_id,
        new_id,
        csv_filename, 
        creator,
        is_success,     # Status
        0               # IsPublish
    )

    if execute_query(sql, params):
        return jsonify({"status": "success", "message": "版本比對完成！"})
    else:
        return jsonify({"status": "error", "message": "比對過程中發生資料庫錯誤"})

@app.route("/mapping_tool", methods=["POST"])
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


@app.route("/mapping/action", methods=["POST"])
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
        return send_from_directory(Mapping_Folder, result[0]['ResultName'], as_attachment=True, mimetype="text/csv")
    
    elif action == "load_csv":
        csv_name = request.form.get("csv_name")
        file_path = os.path.join(Mapping_Folder, csv_name)
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        return "找不到 CSV", 404


# @app.route("/move")
# @login_required
# def move_page():
#     return render_template("move.html")


# notes.html 用的比對紀錄

@app.route("/notes", methods=["GET"])
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


# # notes_xfdf.html 用的比對紀錄
# @app.route("/notes_xfdf", methods=["GET"])
# def notes_xfdf_page():
#     # 只取已發布的比對紀錄
#     sql_history = """
#         SELECT MappingRecord.RecordID,
#                DocVersion_Old.FileName AS OldFileName,
#                DocVersion_Old.Version AS OldVersion,
#                DocVersion_New.FileName AS NewFileName,
#                DocVersion_New.Version AS NewVersion,
#                MappingRecord.ResultName,
#                MappingRecord.Status,
#                MappingRecord.CreateTime,
#                Users.Name AS CreatorName
#         FROM MappingRecord
#         INNER JOIN Users ON MappingRecord.Creator = Users.ID
#         LEFT JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID
#         LEFT JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
#         WHERE MappingRecord.IsPublish = 1
#         ORDER BY MappingRecord.CreateTime ASC
#     """
#     mapping_history = fetch_all(sql_history)  
#     history = mapping_history  

#     return render_template("notes_xfdf.html", mapping_history=mapping_history, history=history)

@app.route("/annotation/migrate_pdf", methods=["POST"])
def migrate_pdf_api():
    try:
        pdf_with_notes = request.files["old_pdf"]
        mapping_id = request.form.get("mapping_id")
        user_id = session.get("ID")

        if not mapping_id:
            return jsonify({"status": "error", "message": "未選擇版本比對紀錄"})

        sql = """
        SELECT 
            DocVersion_Old.FileName AS old_file, 
            DocVersion_New.FileName AS new_file, 
            MappingRecord.ResultName AS csv_file
        FROM MappingRecord
        LEFT JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID
        LEFT JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
        WHERE MappingRecord.RecordID = ?
        """

        TransferID = str(uuid.uuid4())
        row = fetch_all(sql, (mapping_id,))[0]

        target_new_pdf_path = os.path.join(VERSION_Folder, row['new_file'])
        mapping_csv_path = os.path.join(Mapping_Folder, row['csv_file'])

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
            output_pdf=output_path
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

# @app.route("/annotation/migrate", methods=["POST"])
# def migrate_annotation():
#     try:

#         # 使用者上傳的 XFDF
#         xfdf = request.files["xfdf"]
#         mapping_id = request.form.get("mapping_id")

#         if not mapping_id:
#             return jsonify({"status": "error", "message": "未選擇版本比對紀錄"})

#         # 從資料庫取對應的舊版、新版 PDF 與 mapping CSV
#         sql = """
#         SELECT 
#             DocVersion_Old.FileName AS old_file, 
#             DocVersion_New.FileName AS new_file, 
#             MappingRecord.ResultName AS csv_file
#         FROM MappingRecord
#         LEFT JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID
#         LEFT JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
#         WHERE MappingRecord.RecordID = ?
#         """
#         row = fetch_all(sql, (mapping_id,))
#         if not row:
#             return jsonify({"status": "error", "message": "找不到比對紀錄"})

#         row = row[0]

#         old_pdf_path = os.path.join(VERSION_Folder, row['old_file'])
#         new_pdf_path = os.path.join(VERSION_Folder, row['new_file'])
#         mapping_csv_path = os.path.join(Mapping_Folder, row['csv_file'])

#         # 原始檔名
#         original_name = xfdf.filename

#         # 拆檔名與副檔名
#         name, ext = os.path.splitext(original_name)

#         # 新檔名：加上 _轉移
#         new_filename = f"{name}_轉移{ext}"

#         # 存使用者上傳檔
#         xfdf_path = os.path.join(PDF_xfdf_Folder, original_name)
#         xfdf.save(xfdf_path)

#         # 轉移後輸出檔
#         output = os.path.join(PDF_xfdf_Folder, new_filename)

#         # 呼叫轉移函式
#         migrate_all_to_xfdf(
#             old_pdf_path,
#             new_pdf_path,
#             xfdf_path,
#             output,
#             mapping_csv_path
#         )

#         return jsonify({
#         "status": "success",
#         "filename": new_filename})

#     except Exception as e:
#         print("ERROR:", e)
#         return jsonify({
#             "status": "error",
#             "message": str(e)
#         })

        
@app.route("/annotation/migrate_existing_json", methods=["POST"])
def migrate_existing_json():
    try:
        json_filename = request.form.get("json_filename")
        mapping_id = request.form.get("mapping_id")

        if not json_filename or not mapping_id:
            return jsonify({"status": "error", "message": "缺少資料"})

        sql = """
        SELECT 
            DocVersion_Old.FileName AS old_file, 
            DocVersion_New.FileName AS new_file, 
            MappingRecord.ResultName AS csv_file
        FROM MappingRecord
        LEFT JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID
        LEFT JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
        WHERE MappingRecord.RecordID = ?
        """
        row = fetch_all(sql, (mapping_id,))
        if not row:
            return jsonify({"status": "error", "message": "找不到比對紀錄"})

        row = row[0]

        old_pdf_path = os.path.join(VERSION_Folder, row['old_file'])
        new_pdf_path = os.path.join(VERSION_Folder, row['new_file'])
        mapping_csv_path = os.path.join(Mapping_Folder, row['csv_file'])

        json_path = os.path.join(app.root_path, "static", "annotation", json_filename)

        name, ext = os.path.splitext(json_filename)
        new_json_name = f"{name}_轉移{ext}"
        output_json_path = os.path.join(app.root_path, "static", "annotation", new_json_name)

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
    
@app.route('/download_pdf/<filename>')
@login_required 
def download_pdf(filename):
    sql = """SELECT SourceFileName FROM Hospital.dbo.NoteTransferHistory WHERE ResultName = ?"""
    result = fetch_all(sql, (filename,))

    if result:
        source_file_name = result[0]['SourceFileName']
        base_name = os.path.splitext(source_file_name)[0]

    return send_from_directory(Note_Transfer,filename, as_attachment=True,download_name=f"{base_name}_Move.pdf")


@app.route("/notes_tool", methods=["POST"])
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
      
if __name__ == "__main__":
    app.run(debug=True,host="0.0.0.0",port=5001)
    # app.run(debug=True,host="0.0.0.0",port=51000,ssl_context=('server.crt', 'server.key'))