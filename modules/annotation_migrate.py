import fitz
import xml.etree.ElementTree as ET
import os
import pandas as pd
import re
import html
import math

# ------------------------- 工具函式 -------------------------

def hex_to_pdf_color(hex_color):
    if not hex_color or hex_color == "transparent": return "0 0 0 rg"
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3: hex_color = ''.join([c*2 for c in hex_color])
    try:
        r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
        return f"{r:.3f} {g:.3f} {b:.3f} rg"
    except: return "0 0 0 rg"

def parse_css_styles(style_str):
    styles = {}
    if not style_str: return styles
    for key, pattern in [('color', r'color:(#[0-9a-fA-F]+)'), ('size', r'font-size:([\d\.]+pt)'), ('family', r'font-family:([^;"]+)')]:
        m = re.search(pattern, style_str)
        if m: styles[key] = m.group(1).split(',')[0].strip().replace("'", "").replace('"', '')
    return styles

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
    if is_gesture: return ";".join([f"{p[0]},{p[1]}" for p in res])
    return ",".join([f"{p[0]},{p[1]}" for p in res])

def find_nearest_text_anchor(page, rect):
    """ 
    AI 核心：如果正下方沒字，尋找全頁面距離最近的文字塊作為錨點 
    """
    words = page.get_text("words") # (x0, y0, x1, y1, "text", ...)
    if not words: return None, None
    
    annot_center = ((rect.x0 + rect.x1)/2, (rect.y0 + rect.y1)/2)
    min_dist = float('inf')
    best_word = None
    
    for w in words:
        w_center = ((w[0] + w[2])/2, (w[1] + w[3])/2)
        dist = math.sqrt((annot_center[0]-w_center[0])**2 + (annot_center[1]-w_center[1])**2)
        if dist < min_dist:
            min_dist = dist
            best_word = w
            
    if best_word:
        # 回傳: 搜尋關鍵字, 該字在舊頁面的座標
        return best_word[4], fitz.Rect(best_word[:4])
    return None, None

# ------------------------- 主程式 -------------------------

def migrate_all_to_xfdf(old_pdf_path, new_pdf_path, xfdf_in, xfdf_out, mapping_csv):
    old_doc = fitz.open(old_pdf_path)
    new_doc = fitz.open(new_pdf_path)
    
    df = pd.read_csv(mapping_csv, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    mapping = {int(row["Old_Page"]) - 1: int(row["Matched_New_Page"]) - 1 for _, row in df.iterrows()}

    ns_url = "http://ns.adobe.com/xfdf/"
    ns = {"ns": ns_url}
    ET.register_namespace('', ns_url)
    tree = ET.parse(xfdf_in)
    root = tree.getroot()

    f_node = root.find("ns:f", ns)
    if f_node is not None: f_node.set("href", os.path.basename(new_pdf_path))
    ids_node = root.find("ns:ids", ns)
    if ids_node is not None: root.remove(ids_node)

    annots = root.findall(".//ns:annots/*", ns)
    
    print(f"\n{'註解類型':<12} | {'頁碼遷移':<12} | {'對齊狀態':<10} | {'錨點摘要'}")
    print("-" * 100)

    for a in annots:
        tag = a.tag.split('}')[-1].lower()
        if tag not in ("stamp", "highlight", "freetext", "square", "ink", "text", "link", "circle", "line", "underline", "strikeout"):
            continue

        old_page_idx = int(a.get("page") or 0)
        rect_str = a.get("rect")
        if not rect_str or old_page_idx >= len(old_doc): continue

        csv_target = mapping.get(old_page_idx, old_page_idx)
        old_page = old_doc[old_page_idx]
        old_h = old_page.rect.height
        rx0, ry_bot, rx1, ry_top = map(float, rect_str.split(','))
        old_rect = fitz.Rect(rx0, old_h - ry_top, rx1, old_h - ry_bot)

        # 🌟 AI 智慧錨點搜尋
        search_key, old_anchor_rect = find_nearest_text_anchor(old_page, old_rect)
        
        dx, dy, found = 0, 0, False
        status = "CSV保底"

        if search_key:
            # 跨頁搜尋範圍 (前後一頁)
            for p_idx in [csv_target, csv_target-1, csv_target+1]:
                if p_idx < 0 or p_idx >= len(new_doc): continue
                dest_page = new_doc[p_idx]
                hits = dest_page.search_for(search_key)
                
                if hits:
                    # 如果有多個命中，挑選與原座標位置最接近的一個
                    best_hit = hits[0]
                    min_d = float('inf')
                    for h in hits:
                        d = abs(h.y0 - old_anchor_rect.y0) + abs(h.x0 - old_anchor_rect.x0)
                        if d < min_d:
                            min_d = d
                            best_hit = h
                    
                    # 計算位移量
                    dx = best_hit.x0 - old_anchor_rect.x0
                    dy = best_hit.y0 - old_anchor_rect.y0
                    found, csv_target = True, p_idx
                    status = "AI鄰近對齊"
                    break

        print(f"{tag:<12} | {old_page_idx+1:>4} -> {csv_target+1:>4} | {status:<10} | [{search_key or '無'}]")

        new_h = new_doc[csv_target].rect.height
        a.set("page", str(csv_target))
        a.set("rect", transform_pts(rect_str, dx, dy, old_h, new_h))
        
        if a.get("quadpoints"): a.set("quadpoints", transform_pts(a.get("quadpoints"), dx, dy, old_h, new_h))
        if a.get("coords"): a.set("coords", transform_pts(a.get("coords"), dx, dy, old_h, new_h))
        
        for g in a.findall(".//ns:gesture", ns):
            if g.text: g.text = transform_pts(g.text, dx, dy, old_h, new_h)

        # 樣式處理 (打字機)
        if tag == "freetext":
            f_color, f_size, f_family = "#000000", "12pt", "Courier New"
            ds_el = a.find("ns:defaultstyle", ns)
            if ds_el is not None and ds_el.text:
                s = parse_css_styles(ds_el.text)
                f_color, f_size, f_family = s.get('color', f_color), s.get('size', f_size), s.get('family', f_family)
            rt_node = a.find("ns:contents-richtext", ns)
            if rt_node is not None:
                rt_str = ET.tostring(rt_node, encoding='unicode')
                colors = re.findall(r'color:(#[0-9a-fA-F]+)', rt_str)
                if colors: f_color = next((c for c in reversed(colors) if c != "#000000"), colors[-1])
                txt = html.unescape(re.sub(r'<[^>]+>', '', rt_str).strip())
                a.remove(rt_node)
            else:
                c_node = a.find(f"{{{ns_url}}}contents")
                txt = c_node.text if c_node is not None else (a.get("contents") or "")

            if "color" in a.attrib: del a.attrib["color"]
            a.set("width", "0")
            a.set("contents", txt)
            new_style = f"font-family:'{f_family}';font-size:{f_size};color:{f_color};background-color:transparent;"
            if ds_el is not None: ds_el.text = new_style
            else: ET.SubElement(a, f"{{{ns_url}}}defaultstyle").text = new_style
            da_el = a.find("ns:defaultappearance", ns)
            new_app = f"{hex_to_pdf_color(f_color)} /F1 {f_size.replace('pt','')} Tf"
            if da_el is not None: da_el.text = new_app
            else: ET.SubElement(a, f"{{{ns_url}}}defaultappearance").text = new_app
            c_el = a.find(f"{{{ns_url}}}contents")
            if c_el is not None: c_el.text = txt
            else: ET.SubElement(a, f"{{{ns_url}}}contents").text = txt

    tree.write(xfdf_out, encoding="utf-8", xml_declaration=True)
    old_doc.close(); new_doc.close()
    print(f"\n✨ v26 遷移完成！已啟用「AI 鄰近錨點搜尋」。")
