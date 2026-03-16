import fitz
import xml.etree.ElementTree as ET
import os
import pandas as pd
import re
import math

# --- 第二版核心工具函式 ---

def get_rect_distance(r1, r2):
    if r1.intersects(r2): return 0
    dx = max(0, r1.x0 - r2.x1, r2.x0 - r1.x1)
    dy = max(0, r1.y0 - r2.y1, r2.y0 - r1.y1)
    return math.sqrt(dx**2 + dy**2)

def transform_rect(rect_str, dx, dy, old_h, new_h, tag=""):
    if not rect_str: return ""
    try:
        rx0, ry_bot, rx1, ry_top = map(float, rect_str.split(','))
        width, height = rx1 - rx0, ry_top - ry_bot
        nx0 = rx0 + dx
        ny_bot = new_h - ((old_h - ry_bot) + dy)
        expand = 2.0 if tag == "freetext" else 0.0
        nx1, ny_top = nx0 + width + expand, ny_bot + height + expand
        return f"{nx0:.4f},{ny_bot:.4f},{nx1:.4f},{ny_top:.4f}"
    except: return rect_str

def transform_pts(pts_str, dx, dy, old_h, new_h):
    if not pts_str: return ""
    is_gesture = ';' in pts_str
    nums = re.split(r'[;,]', pts_str)
    res = []
    for i in range(0, len(nums)-1, 2):
        try:
            nx = float(nums[i]) + dx
            ny = new_h - ((old_h - float(nums[i+1])) + dy)
            res.append((f"{nx:.4f}", f"{ny:.4f}"))
        except: continue
    return (";" if is_gesture else ",").join([f"{p[0]},{p[1]}" for p in res])

def find_nearest_text_anchor(page, rect):
    words = page.get_text("words")
    if not words: return None, None
    annot_center = ((rect.x0 + rect.x1)/2, (rect.y0 + rect.y1)/2)
    min_dist, best_word = float('inf'), None
    for w in words:
        w_center = ((w[0] + w[2])/2, (w[1] + w[3])/2)
        dist = math.sqrt((annot_center[0]-w_center[0])**2 + (annot_center[1]-w_center[1])**2)
        if dist < min_dist: min_dist, best_word = dist, w
    return (best_word[4], fitz.Rect(best_word[:4])) if best_word else (None, None)

# --- 第二版主程式 (整合 Flask 使用) ---

def migrate_all_to_xfdf(old_pdf_path, new_pdf_path, xfdf_in, xfdf_out, mapping_csv):
    # 開啟 PDF
    old_doc, new_doc = fitz.open(old_pdf_path), fitz.open(new_pdf_path)
    
    # 讀取 CSV
    df = pd.read_csv(mapping_csv, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    mapping = {int(row["Old_Page"]) - 1: int(row["Matched_New_Page"]) - 1 for _, row in df.iterrows()}

    # 讀取 XFDF 字串 (用於最後的正則替換)
    with open(xfdf_in, 'r', encoding='utf-8') as f:
        content = f.read()

    # 解析 XML 結構 (用於座標計算)
    ns = {"ns": "http://ns.adobe.com/xfdf/"}
    tree = ET.parse(xfdf_in)
    root = tree.getroot()

    annots = list(root.findall(".//ns:annots/*", ns))
    # 排序：優先處理 highlight 或 freetext，作為群組參考點
    tag_priority = {"highlight": 0, "freetext": 0, "square": 1, "ink": 2}
    annots.sort(key=lambda x: tag_priority.get(x.tag.split('}')[-1].lower(), 3))

    processed_offsets, mods = {}, {}

    for a in annots:
        tag = a.tag.split('}')[-1].lower()
        name, rect_str, old_page_idx = a.get("name"), a.get("rect"), int(a.get("page") or 0)
        
        if not name or not rect_str or old_page_idx >= len(old_doc): continue

        old_page = old_doc[old_page_idx]
        old_h = old_page.rect.height
        rx0, ry_bot, rx1, ry_top = map(float, rect_str.split(','))
        old_rect = fitz.Rect(rx0, old_h - ry_top, rx1, old_h - ry_bot)

        dx, dy, csv_target, found_group = 0, 0, mapping.get(old_page_idx, old_page_idx), False

        # 1. 群組綁定
        if old_page_idx in processed_offsets:
            for ref_rect, ref_dx, ref_dy in processed_offsets[old_page_idx]:
                if get_rect_distance(old_rect, ref_rect) < 40:
                    dx, dy, found_group = ref_dx, ref_dy, True
                    break

        # 2. AI 錨點對齊
        if not found_group:
            search_key, old_anchor_rect = find_nearest_text_anchor(old_page, old_rect)
            if search_key:
                for p_idx in [csv_target, csv_target-1, csv_target+1]:
                    if 0 <= p_idx < len(new_doc):
                        hits = new_doc[p_idx].search_for(search_key)
                        if hits:
                            best_hit = min(hits, key=lambda h: abs(h.y0 - old_anchor_rect.y0) + abs(h.x0 - old_anchor_rect.x0))
                            dx, dy, csv_target = best_hit.x0 - old_anchor_rect.x0, best_hit.y0 - old_anchor_rect.y0, p_idx
                            break

        # 紀錄位移
        if old_page_idx not in processed_offsets: processed_offsets[old_page_idx] = []
        processed_offsets[old_page_idx].append((old_rect, dx, dy))

        # 存儲修改數據
        new_h = new_doc[csv_target].rect.height
        mods[name] = {
            "page": str(csv_target),
            "rect": transform_rect(rect_str, dx, dy, old_h, new_h, tag),
            "quadpoints": transform_pts(a.get("quadpoints"), dx, dy, old_h, new_h) if a.get("quadpoints") else None,
            "coords": transform_pts(a.get("coords"), dx, dy, old_h, new_h) if a.get("coords") else None,
            "gestures": [transform_pts(g.text, dx, dy, old_h, new_h) for g in a.findall(".//ns:gesture", ns) if g.text]
        }

    # --- 正則替換回寫 ---
    def update_tag_pure(match):
        tag_content = match.group(0)
        name_match = re.search(r'\bname="([^"]+)"', tag_content, flags=re.IGNORECASE)
        if name_match and name_match.group(1) in mods:
            mod = mods[name_match.group(1)]
            tag_content = re.sub(r'\bpage="\d+"', f'page="{mod["page"]}"', tag_content, flags=re.IGNORECASE)
            tag_content = re.sub(r'\brect="[^"]+"', f'rect="{mod["rect"]}"', tag_content, flags=re.IGNORECASE)
            if mod.get("quadpoints"): tag_content = re.sub(r'\bquadpoints="[^"]+"', f'quadpoints="{mod["quadpoints"]}"', tag_content, flags=re.IGNORECASE)
            if mod.get("coords"): tag_content = re.sub(r'\bcoords="[^"]+"', f'coords="{mod["coords"]}"', tag_content, flags=re.IGNORECASE)
        return tag_content

    tags = ['freetext', 'highlight', 'fileattachment', 'ink', 'square', 'stamp', 'circle', 'line', 'strikeout', 'underline', 'text', 'link']
    for t in tags:
        content = re.sub(rf'<(?:[\w-]+:)?{t}\b[^>]*>', update_tag_pure, content, flags=re.IGNORECASE)

    # 處理 Ink 路徑
    def update_ink_gestures(match):
        block = match.group(0)
        name_m = re.search(r'\bname="([^"]+)"', block, flags=re.IGNORECASE)
        if name_m and name_m.group(1) in mods and mods[name_m.group(1)]["gestures"]:
            mod, g_idx = mods[name_m.group(1)], [0]
            def g_repl(m):
                if g_idx[0] < len(mod["gestures"]):
                    res = f"{m.group(1)}{mod['gestures'][g_idx[0]]}{m.group(3)}"
                    g_idx[0] += 1
                    return res
                return m.group(0)
            block = re.sub(r'(<(?:[\w-]+:)?gesture[^>]*>)(.*?)(</(?:[\w-]+:)?gesture>)', g_repl, block, flags=re.DOTALL | re.IGNORECASE)
        return block

    content = re.sub(r'<(?:[\w-]+:)?ink\b.*?</(?:[\w-]+:)?ink>', update_ink_gestures, content, flags=re.DOTALL | re.IGNORECASE)

    with open(xfdf_out, 'w', encoding='utf-8') as f:
        f.write(content)

    old_doc.close(); new_doc.close()