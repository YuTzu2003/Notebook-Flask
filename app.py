import fitz 
import pandas as pd
import os
import json
import base64
import re
import io
import pdfplumber 
from flask import Flask, flash, redirect, render_template, request, jsonify, send_file, send_from_directory, session, url_for
from modules.auth import auth_bp, login_required
import uuid
from modules.db import execute_query, fetch_all
from modules.mapping import UseMapping

app = Flask(__name__)
UPLOAD_Folder = "static/uploads"
NOTE_Folder = "static/annotation"
Mapping_Folder = "static/docMapResult"
VERSION_Folder = 'static/docVersion'
FONT_PATH = "C:/Windows/Fonts/msjh.ttc" 
app.secret_key = "replace-with-a-secret-key"

def parse_color(color_str):
    if not color_str: return (0, 0, 0)
    if color_str.startswith('rgb'):
        nums = re.findall(r"\d+\.?\d*", color_str)
        if len(nums) >= 3:
            return tuple(float(nums[i]) / 255.0 for i in range(3))
    hex_str = color_str.lstrip('#')
    if len(hex_str) == 6:
        return tuple(int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    return (0, 0, 0)

def parse_page_range(range_str):
    pages = []
    if not range_str: return []
    parts = range_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                pages.extend(range(start, end + 1))
            except: pass
        else:
            try:
                pages.append(int(part))
            except: pass
    return sorted(list(set(pages)))

def clean_text(text):
    if not text: return ""
    return text.replace("\n", "").replace("\r", "").strip()


# 掛載登入模組
app.register_blueprint(auth_bp)
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

@app.route("/upload_pdf", methods=["POST"])
@login_required
def upload_pdf():
    f = request.files.get("pdf")
    if not f: 
        return "No PDF", 400

    user_id = session.get("ID")
    original_name = f.filename
    
    doc_uuid = str(uuid.uuid4())
    storage_name = f"{doc_uuid}.pdf" # 系統存檔名
    pdf_path = os.path.join(UPLOAD_Folder, storage_name)
    f.save(pdf_path)

    # 頁數與尺寸
    doc = fitz.open(pdf_path)
    width, height = doc[0].rect.width, doc[0].rect.height
    total_pages = len(doc)
    doc.close()

    sql = """INSERT INTO Documents (DocID, User_ID, OriginalName, StorageName, Pages) VALUES (?, ?, ?, ?, ?) """
    execute_query(sql, (doc_uuid, user_id, original_name, storage_name, total_pages))

    json_path = os.path.join(UPLOAD_Folder, doc_uuid + ".json")
    mods = {}
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as jf:
            mods = json.load(jf)

    doc = fitz.open(pdf_path)
    toc_simple = doc.get_toc() 
    doc.close()

    return jsonify({
        "doc_id": doc_uuid,      
        "pdf_name": storage_name, 
        "original_name": original_name,
        "total_pages": total_pages,
        "width": width, 
        "height": height, 
        "mods": mods,
        "has_embedded_toc": len(toc_simple) > 0
    })

@app.route("/get_page_image/<doc_id>/<int:page_num>")
def get_page_image(doc_id, page_num):
    filename = doc_id if doc_id.lower().endswith('.pdf') else f"{doc_id}.pdf"
    pdf_path = os.path.join(UPLOAD_Folder, filename)

    if not os.path.isfile(pdf_path):
        return "PDF not found", 404

    try:
        with fitz.open(pdf_path) as doc:
            if not (0 <= page_num < len(doc)):
                return "Page out of range", 404

            pix = doc[page_num].get_pixmap(matrix=fitz.Matrix(2, 2))
            img_io = io.BytesIO(pix.tobytes("png"))
            
        return send_file(img_io, mimetype='image/png')
    except Exception as e:
        return f"Error processing PDF: {str(e)}", 500

@app.route("/add_blank_page", methods=["POST"])
@login_required
def add_blank_page():
    data = request.json
    doc_id, insert_after, current_mods = data.get("doc_id"), data.get("insert_after"), data.get("all_modifications", {})
    user_id = session.get("ID")
    rows = fetch_all("SELECT StorageName FROM Documents WHERE DocID = ? AND User_ID = ?", (doc_id, user_id))
    pdf_path = os.path.join(UPLOAD_Folder, rows[0]['StorageName'])
    temp_path = pdf_path + ".tmp"
    try:
        doc = fitz.open(pdf_path)
        target_idx = insert_after + 1
        doc.insert_page(target_idx, width=doc[0].rect.width, height=doc[0].rect.height)
        doc.save(temp_path)
        doc.close()
        os.replace(temp_path, pdf_path)
        new_total = len(fitz.open(pdf_path))
        execute_query("UPDATE Documents SET Pages = ? WHERE DocID = ? AND User_ID = ?", (new_total, doc_id, user_id))
        new_mods = {str(int(k)+1 if int(k)>=target_idx else k): v for k, v in current_mods.items()}
        with open(os.path.join(NOTE_Folder, f"{doc_id}.json"), "w", encoding="utf-8") as f:
            json.dump(new_mods, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True, "new_total_pages": new_total, "mods": new_mods})
    except Exception as e: return jsonify({"success": False, "message": str(e)}), 500

@app.route("/delete_page", methods=["POST"])
@login_required
def delete_page():
    data = request.json
    doc_id, page_idx, current_mods = data.get("doc_id"), data.get("page_idx"), data.get("all_modifications", {})
    user_id = session.get("ID")
    rows = fetch_all("SELECT StorageName FROM Documents WHERE DocID = ? AND User_ID = ?", (doc_id, user_id))
    pdf_path = os.path.join(UPLOAD_Folder, rows[0]['StorageName'])
    temp_path = pdf_path + ".tmp"
    try:
        doc = fitz.open(pdf_path)
        if len(doc) <= 1: return jsonify({"success": False, "message": "不可刪除最後一頁"}), 400
        doc.delete_page(page_idx)
        doc.save(temp_path)
        doc.close()
        os.replace(temp_path, pdf_path)
        new_total = len(fitz.open(pdf_path))
        execute_query("UPDATE Documents SET Pages = ? WHERE DocID = ? AND User_ID = ?", (new_total, doc_id, user_id))
        new_mods = {str(int(k)-1 if int(k)>page_idx else k): v for k, v in current_mods.items() if int(k) != page_idx}
        with open(os.path.join(NOTE_Folder, f"{doc_id}.json"), "w", encoding="utf-8") as f:
            json.dump(new_mods, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True, "new_total_pages": new_total, "mods": new_mods})
    except Exception as e: return jsonify({"success": False, "message": str(e)}), 500

@app.route("/save", methods=["POST"])
@login_required
def save():
    data = request.json
    doc_id, original_name, all_mods = data.get("doc_id"), data.get("original_name", "note.pdf"), data["all_modifications"]
    with open(os.path.join(NOTE_Folder, f"{doc_id}.json"), "w", encoding="utf-8") as jf:
        json.dump(all_mods, jf, ensure_ascii=False, indent=2)
    
    doc = fitz.open(os.path.join(UPLOAD_Folder, f"{doc_id}.pdf"))
    for p_idx_str, objs in all_mods.items():
        idx = int(p_idx_str)
        if idx >= len(doc): continue
        page = doc[idx]
        for o in objs:
            # 便籤
            if o.get("data_type") == "sticky":
                if o.get("noteImage"):       
                    img_data = base64.b64decode(o["noteImage"].split(",", 1)[1])
                    file_annot = page.add_file_annot(fitz.Point(o["left"], o["top"]), img_data, "anno.png")     
                    file_annot.set_name("Tag")
                    file_annot.set_colors(stroke=(1, 0.6, 0.2))
                    file_annot.set_info(content=o.get("noteText"),  title="附件")
                    file_annot.update()

                else:
                    annot = page.add_text_annot(fitz.Point(o["left"], o["top"]), o.get("noteText", ""))
                    annot.set_colors(stroke=(1.0, 0.9, 0.2))
                    annot.set_info(content=o.get("noteText", ""), title="筆記")
                    annot.update()

            # 文字
            elif o.get("type") in ["i-text", "text", "textbox"] and o.get("data_type") != "sticky":
                page.insert_text((o["left"], o["top"] + float(o.get("fontSize", 20))), o.get("text", ""), fontsize=float(o.get("fontSize", 20)), fontfile=FONT_PATH, fontname="china-ss", color=parse_color(o.get("fill", "#000000")))
            
            # 圖片
            elif o.get("type") == "image":
                img_data = base64.b64decode(o["src"].split(",", 1)[1])
                page.insert_image(fitz.Rect(o["left"], o["top"], o["left"] + o["width"]*o.get("scaleX", 1), o["top"] + o["height"]*o.get("scaleY", 1)), stream=img_data)
            
            elif o.get("type") == "path":
                points = o.get("abs_points", [])
                
                if points:
                    annot = page.add_ink_annot([points])                 
                    stroke_color = parse_color(o.get("stroke", "#061fbd"))
                    annot.set_colors(stroke=stroke_color)
                    width = o.get("strokeWidth", 3) 
                    annot.set_border(width=width)
                    annot.set_opacity(o.get("opacity", 0.5))
                    annot.update()

    out_buffer = io.BytesIO()
    doc.save(out_buffer)
    doc.close()
    out_buffer.seek(0)
    return send_file(out_buffer, mimetype='application/pdf', as_attachment=True, download_name=f"{os.path.splitext(original_name)[0]}_note.pdf")

@app.route("/analyze_toc", methods=["POST"])
def analyze_toc():
    data = request.json
    filename = data.get("pdf_name")
    toc_str = data.get("toc_pages", "")
    offset = int(data.get("offset", 0))
    
    pdf_path = os.path.join(UPLOAD_Folder, filename)
    toc_pages = parse_page_range(toc_str)

    if not toc_pages:
        return jsonify({"error": "請輸入目錄所在的頁碼範圍"}), 400
    toc_list = []
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        for p_num in toc_pages:
            if p_num > total_pages: continue
            
            page = pdf.pages[p_num - 1] 
            text = page.extract_text()
            if not text: continue
            
            for line in text.split("\n"):
                match = re.search(r'^(.*?)\s+(\d+)$', line.strip())
                if match:
                    raw_title = match.group(1)
                    page_ref = int(match.group(2))
                    title = re.sub(r'[.．。\s]+$', '', raw_title).strip()

                    if title and not title.isdigit() and len(title) > 1:
                        toc_list.append({
                            "title": title, 
                            "page": page_ref,
                            "jump_page": page_ref + offset 
                        })

    if not toc_list:
            return jsonify({"error": "在指定頁面找不到目錄格式的文字"}), 400

    return jsonify({"success": True, "data": toc_list})


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

    # old_file = file_map[str(old_id)]
    # new_file = file_map[str(new_id)]
    

    # old_pdf_path = os.path.join(VERSION_Folder, old_file)
    # new_pdf_path = os.path.join(VERSION_Folder, new_file)
    old_pdf_path = f"{VERSION_Folder}/{file_map[str(old_id)]}"
    new_pdf_path = f"{VERSION_Folder}/{file_map[str(new_id)]}"
    csv_filename = f"{uuid.uuid4()}.csv"

    # csv_result = os.path.join(Mapping_Folder, csv_filename)
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
        flash("比對已執行，但在寫入資料庫時發生錯誤。", "error")
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
        
if __name__ == "__main__":
    app.run(debug=True, port=5001)