import fitz 
import os
import json
import base64
import re
import io
import uuid
import pdfplumber 
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, session
from modules.auth import login_required
from modules.db import execute_query, fetch_all

notes_bp = Blueprint('annotation_edit', __name__)

UPLOAD_Folder = "static/uploads"
NOTE_Folder = "static/annotation"
FONT_PATH = "C:/Windows/Fonts/msjh.ttc"

def parse_color(color_str):
    if not color_str: 
        return (1, 1, 0) 
    
    if color_str.startswith('rgba'):
        nums = re.findall(r"(\d+\.?\d*)", color_str)
        if len(nums) >= 3:
            return tuple(float(nums[i]) / 255.0 for i in range(3))
            
    elif color_str.startswith('rgb'):
        nums = re.findall(r"(\d+\.?\d*)", color_str)
        if len(nums) >= 3:
            return tuple(float(nums[i]) / 255.0 for i in range(3))
            
    elif color_str.startswith('#'):
        hex_str = color_str.lstrip('#')
        if len(hex_str) == 6:
            return tuple(int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4))          
    return (1, 1, 0)

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


@notes_bp.route("/upload_pdf", methods=["POST"])
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

@notes_bp.route("/get_pdf_content/<doc_id>")
@login_required
def get_pdf_content(doc_id):
    filename = doc_id if doc_id.lower().endswith('.pdf') else f"{doc_id}.pdf"
    pdf_path = os.path.join(UPLOAD_Folder, filename)

    if not os.path.isfile(pdf_path):
        return "PDF not found", 404

    return send_file(pdf_path, mimetype='application/pdf')

@notes_bp.route("/add_blank_page", methods=["POST"])
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

@notes_bp.route("/delete_page", methods=["POST"])
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

@notes_bp.route("/save", methods=["POST"])
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
            
            # 隨意繪圖
            elif o.get("type") == "path":
                abs_points = o.get("abs_points", [])
                if not abs_points: continue
                annot = page.add_polyline_annot(abs_points)
                annot.set_colors(stroke=parse_color(o.get("stroke", "#ffff00")))
                annot.set_opacity(0.5) 
                annot.set_border(width=o.get("strokeWidth", 1) * o.get("scaleX", 1))
                annot.update()

            # 螢光筆
            elif o.get("data_type") == "highlight":
                left = float(o.get("left", 0))
                top = float(o.get("top", 0))
                width = float(o.get("width", 0))
                height = float(o.get("height", 0))

                if width <= 0 or height <= 0:
                    continue

                rect = fitz.Rect(left,top,left + width,top + height)
                rect = rect & page.rect

                if rect.is_empty:
                    continue

                annot = page.add_highlight_annot(rect)
                fill_color = parse_color(o.get("fill", "#ffff00"))
                annot.set_colors(stroke=fill_color)
                annot.set_opacity(0.5)
                annot.update()    

            # 底線
            elif o.get("data_type") == "underline":              
                start_x = float(o.get("left", 0))
                end_x = start_x + float(o.get("width", 0))
                y_pos = float(o.get("top", 0)) + (float(o.get("height", 0)) / 2)
                p1 = fitz.Point(start_x, y_pos)
                p2 = fitz.Point(end_x, y_pos)
                annot = page.add_line_annot(p1, p2)
                stroke_color = parse_color(o.get("fill", "#000000"))
                annot.set_colors(stroke=stroke_color)
                annot.set_border(width=float(o.get("height", 2)))
                annot.update()

    out_buffer = io.BytesIO()
    doc.save(out_buffer)
    doc.close()
    out_buffer.seek(0)
    execute_query("UPDATE Documents SET UploadTime = ? WHERE DocID = ? AND User_ID = ?", (datetime.now(), doc_id, session.get("ID")))
    return send_file(out_buffer, mimetype='application/pdf', as_attachment=True, download_name=f"{os.path.splitext(original_name)[0]}_note.pdf")

@notes_bp.route("/analyze_toc", methods=["POST"])
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