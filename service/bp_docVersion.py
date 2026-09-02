from flask import Blueprint, render_template, request, session, flash, redirect, url_for, send_from_directory, send_file
import os
import uuid
import pymupdf as fitz
from modules.db import execute_query
from modules.auth import login_required

bp_docVersion = Blueprint('bp_docVersion', __name__)
VERSION_Folder = 'tasks/docVersion'

@bp_docVersion.route('/docVersion', methods=['GET', 'POST'])
@login_required
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

        file_uuid = "doc" + uuid.uuid4().hex[:8]
        original_filename = file.filename
        physical_filename = f"{file_uuid}.pdf"
        
        file_path = f"{VERSION_Folder}/{physical_filename}"
        file.save(file_path)
        size = os.path.getsize(file_path) # Bytes
        uploader = session.get("ID") 

        with fitz.open(file_path) as doc:
            pages = doc.page_count

        sql = """ INSERT INTO DocVersion (ID, FileName, Author, Uploader, Size, Pages, Version) VALUES (?, ?, ?, ?, ?, ?, ?) """
        data = (file_uuid, original_filename, author, uploader, size, pages, version)

        if execute_query(sql, data):
            flash('新增成功！', 'success')
        else:
            flash('新增失敗！', 'error')
        return redirect(request.url)
    sort_by = request.args.get('sort_by', 'UploadTime')
    if sort_by not in {'UploadTime', 'FileName', 'Version', 'Author'}:
        sort_by = 'UploadTime'
    sql = f"""SELECT dbo.DocVersion.*, dbo.Users.Name FROM dbo.DocVersion INNER JOIN dbo.Users ON dbo.DocVersion.Uploader = dbo.Users.ID ORDER BY {sort_by} ASC"""
    documents = execute_query(sql)
    return render_template('docVersion.html', documents=documents, current_sort=sort_by)


@bp_docVersion.route('/docVersion_tool/<action>', defaults={'doc_id': None}, methods=['GET', 'POST'])
@bp_docVersion.route('/docVersion_tool/<action>/<doc_id>', methods=['GET', 'POST'])
@login_required
def docVersion_tool(action, doc_id):
    if action == 'download':
        sql = "SELECT FileName FROM DocVersion WHERE ID = ?"
        result = execute_query(sql, (doc_id,))
        if not result:
            flash('找不到檔案', 'error')
            return redirect(url_for('bp_docVersion.docVersion'))
        
        original_filename = result[0]['FileName']
        physical_filename = f"{doc_id}.pdf"
        return send_from_directory(VERSION_Folder, physical_filename, as_attachment=True, download_name=original_filename)

    elif action == 'preview':
        physical_filename = f"{doc_id}.pdf"
        return send_from_directory(VERSION_Folder, physical_filename, as_attachment=False)

    elif action == 'delete' and request.method == 'POST':
        check_sql = """SELECT COUNT(*) AS count FROM dbo.MappingRecord WHERE OldDocID = ? OR NewDocID = ?"""
        check_result = execute_query(check_sql, (doc_id, doc_id))
        
        if check_result and check_result[0]['count'] > 0:
            flash('該檔案存在於比對紀錄中，不可刪除！', 'error')
        else:
            sql_select = "SELECT ID FROM DocVersion WHERE ID = ?"
            result = execute_query(sql_select, (doc_id,))
            physical_filename = f"{doc_id}.pdf"
            file_path = f"{VERSION_Folder}/{physical_filename}"         
            if execute_query("DELETE FROM DocVersion WHERE ID = ?", (doc_id,)):
                if os.path.exists(file_path):
                    os.remove(file_path)
                flash('刪除成功！', 'success')
            else:
                flash('資料庫刪除失敗', 'error')


    elif action == 'edit' and request.method == 'POST':
        edit_id = request.form.get('edit_id')
        new_filename = request.form.get('edit_filename')
        new_version = request.form.get('edit_version')
        new_author = request.form.get('edit_author')
        new_filename = new_filename.strip() 
        if not new_filename.lower().endswith('.pdf'):
            new_filename += '.pdf'

        sql = "UPDATE DocVersion SET FileName = ?, Version = ?, Author = ? WHERE ID = ?"
        if execute_query(sql, (new_filename, new_version, new_author, edit_id)):
            flash('更新成功！', 'success')
        else:
            flash('更新失敗！', 'error')

    elif action == 'batch_delete' and request.method == 'POST':
        doc_ids = request.form.getlist('doc_ids')
        if not doc_ids:
            flash('未選取任何檔案', 'error')
        else:
            success_count = 0
            for did in doc_ids:
                check_sql = """SELECT COUNT(*) AS count FROM dbo.MappingRecord WHERE OldDocID = ? OR NewDocID = ?"""
                check_result = execute_query(check_sql, (did, did))
                
                if check_result and check_result[0]['count'] > 0:
                    continue
                else:
                    sql_select = "SELECT ID FROM DocVersion WHERE ID = ?"
                    result = execute_query(sql_select, (did,))
                    
                    if result:
                        physical_filename = f"{did}.pdf"
                        file_path = f"{VERSION_Folder}/{physical_filename}"
                        
                        if execute_query("DELETE FROM DocVersion WHERE ID = ?", (did,)):
                            if os.path.exists(file_path):
                                os.remove(file_path)
                            success_count += 1
            flash(f'成功刪除 {success_count} 個檔案', 'success')

    return redirect(url_for('bp_docVersion.docVersion'))
