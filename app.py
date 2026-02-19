import fitz 
import os
import json
from flask import Flask, flash, redirect, render_template, request, jsonify, send_from_directory, session, url_for
from modules.auth import auth_bp, login_required
import uuid
from modules.db import execute_query, fetch_all
from modules.annotation_edit import notes_bp
from modules.mapping import UseMapping

app = Flask(__name__)

UPLOAD_Folder = "static/uploads"
NOTE_Folder = "static/annotation"
Mapping_Folder = "static/docMapResult"
VERSION_Folder = 'static/docVersion'

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
    pdf_path = os.path.join(UPLOAD_Folder, doc_info['StorageName'])
    json_path = os.path.join(NOTE_Folder, f"{doc_id}.json")

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

        version = request.form.get('version')
        author = request.form.get('author')
        filename = file.filename
        file_uuid = str(uuid.uuid4())         
        file_path = os.path.join(VERSION_Folder, filename)
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
    
    sql = "SELECT dbo.DocVersion.*, dbo.Users.Name FROM dbo.DocVersion INNER JOIN dbo.Users ON dbo.DocVersion.Uploader = dbo.Users.ID"
    documents = fetch_all(sql)
    return render_template('docVersion.html', documents=documents)

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
        sql_select = "SELECT FileName FROM DocVersion WHERE ID = ?"
        result = fetch_all(sql_select, (doc_id,))
     
        filename = result[0]['FileName']
        file_path = os.path.join(VERSION_Folder, filename)
        if execute_query("DELETE FROM DocVersion WHERE ID = ?", (doc_id,)):
            os.remove(file_path)
            flash('刪除成功！', 'success')
        else:
            flash('資料庫刪除失敗', 'error')

    elif action == 'edit' and request.method == 'POST':
        edit_id = request.form.get('edit_id')
        new_version = request.form.get('edit_version')
        new_author = request.form.get('edit_author')

        sql = "UPDATE DocVersion SET Version = ?, Author = ? WHERE ID = ?"
        if execute_query(sql, (new_version, new_author, edit_id)):
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
        flash("找不到指定的PDF文", "error")
        return redirect(url_for('mapping_page'))


    old_pdf_path = f"{VERSION_Folder}/{file_map[str(old_id)]}"
    new_pdf_path = f"{VERSION_Folder}/{file_map[str(new_id)]}"
    csv_filename = f"{uuid.uuid4()}.csv"

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
        flash(f"{status_msg}！", flash_category)
    else:
        flash("發生錯誤。", "error")
    return redirect(url_for('mapping_page')) 

@app.route("/mapping/action", methods=["POST"])
def mapping_action():
    action = request.form.get("action")
    record_id = request.form.get("record_id")

    # ===== 刪除 =====
    if action == "delete":
        sql_select = "SELECT ResultName FROM MappingRecord WHERE RecordID = ?"
        result = fetch_all(sql_select, (record_id,))
        
        if result:
            result_filename = result[0]["ResultName"]
            file_path = os.path.join(Mapping_Folder, result_filename)
            if os.path.exists(file_path):
                os.remove(file_path)

        sql_delete = "DELETE FROM MappingRecord WHERE RecordID = ?"
        if execute_query(sql_delete, (record_id,)):
            flash("刪除成功！", "success")
        else:
            flash("刪除失敗", "error")

        return redirect(url_for("mapping_page"))

    # ===== 發布狀態 =====
    elif action == "toggle_publish":
        publish = request.form.get("publish")

        sql = "UPDATE MappingRecord SET IsPublish = ? WHERE RecordID = ?"
        if execute_query(sql, (publish, record_id)):
            flash("發布狀態已更新！", "success")
        else:
            flash("更新失敗。", "error")

        return redirect(url_for("mapping_page"))

    elif action == "preview":
        pdf_type = request.form.get("type") 
        sql = """
            SELECT MappingRecord.RecordID,
                   DocVersion_Old.FileName AS OldFileName,
                   DocVersion_New.FileName AS NewFileName
            FROM MappingRecord
            LEFT OUTER JOIN DocVersion AS DocVersion_Old ON MappingRecord.OldDocID = DocVersion_Old.ID
            LEFT OUTER JOIN DocVersion AS DocVersion_New ON MappingRecord.NewDocID = DocVersion_New.ID
            WHERE MappingRecord.RecordID = ?
        """
        result_list = fetch_all(sql, (record_id,))
        result = result_list[0]

        pdf_name = result["OldFileName"] if pdf_type == "old" else result["NewFileName"]
        return send_from_directory(VERSION_Folder, pdf_name, as_attachment=False)

    elif action == "download":
        sql = "SELECT RecordID,ResultName FROM MappingRecord WHERE RecordID = ?"
        result = fetch_all(sql, (record_id,))
        return send_from_directory(Mapping_Folder, result[0]['ResultName'], as_attachment=True, mimetype="text/csv")


@app.route("/move")
@login_required
def move_page():
    return render_template("move.html")
      
if __name__ == "__main__":
    app.run(debug=True,host="0.0.0.0",port=5001)