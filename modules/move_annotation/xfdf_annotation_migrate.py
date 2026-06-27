import fitz
import xml.etree.ElementTree as ET
import os
import pandas as pd
import re
import math


def get_rect_distance(r1, r2):
    if r1.intersects(r2):
        return 0
    dx = max(0, r1.x0 - r2.x1, r2.x0 - r1.x1)
    dy = max(0, r1.y0 - r2.y1, r2.y0 - r1.y1)
    return math.sqrt(dx**2 + dy**2)

def transform_rect(rect_str, dx, dy, old_h, new_h, expand=2.0):
    if not rect_str: return ""
    try:
        rx0, ry_bot, rx1, ry_top = map(float, rect_str.split(','))
        width = rx1 - rx0
        height = ry_top - ry_bot
        nx0 = rx0 + dx
        ny_bot = new_h - ((old_h - ry_bot) + dy)
        nx1 = nx0 + width + expand
        ny_top = ny_bot + height + expand
        return f"{nx0:.4f},{ny_bot:.4f},{nx1:.4f},{ny_top:.4f}"
    
    except:
        return rect_str

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
    words = page.get_text("words")
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
        return best_word[4], fitz.Rect(best_word[:4])
    return None, None


def migrate_all_to_xfdf(old_pdf_path, new_pdf_path, xfdf_in, xfdf_out, mapping_csv):
    old_doc = fitz.open(old_pdf_path)
    new_doc = fitz.open(new_pdf_path)
    
    df = pd.read_csv(mapping_csv, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    mapping = {int(row["Old_Page"]) - 1: int(row["Matched_New_Page"]) - 1 for _, row in df.iterrows()}

    with open(xfdf_in, 'r', encoding='utf-8') as f:
        content = f.read()

    ns_url = "http://ns.adobe.com/xfdf/"
    ns = {"ns": ns_url}
    ET.register_namespace('', ns_url)
    tree = ET.parse(xfdf_in)
    root = tree.getroot()

    annots_node = root.find(".//ns:annots", ns)
    annots = list(annots_node) if annots_node is not None else []
    
    tag_priority = {"freetext": 0, "fileattachment": 1, "highlight": 1, "ink": 1, "square": 1}
    annots.sort(key=lambda x: tag_priority.get(x.tag.split('}')[-1].lower(), 2))

    processed_offsets = {}
    mods = {} 

    print(f"\n{'註解類型':<12} | {'頁碼遷移':<12} | {'對齊狀態':<10} | {'錨點摘要'}")
    print("-" * 100)

    for a in annots:
        tag = a.tag.split('}')[-1].lower()
        if tag not in ("stamp", "highlight", "freetext", "square", "ink", "text", "link", "circle", "line", "underline", "strikeout", "fileattachment"):
            continue

        name = a.get("name")
        if not name: continue

        old_page_idx = int(a.get("page") or 0)
        rect_str = a.get("rect")
        if not rect_str or old_page_idx >= len(old_doc): continue

        csv_target = mapping.get(old_page_idx, old_page_idx)
        old_page = old_doc[old_page_idx]
        old_h = old_page.rect.height
        rx0, ry_bot, rx1, ry_top = map(float, rect_str.split(','))
        old_rect = fitz.Rect(rx0, old_h - ry_top, rx1, old_h - ry_bot)

        dx, dy, found_group = 0, 0, False
        status = "CSV保底"

        if tag in ("highlight", "fileattachment", "ink", "square"):
            if old_page_idx in processed_offsets:
                for ref_rect, ref_dx, ref_dy, ref_tag in processed_offsets[old_page_idx]:
                    if get_rect_distance(old_rect, ref_rect) < 40:
                        dx, dy = ref_dx, ref_dy
                        status = "群組綁定"
                        found_group = True
                        break

        search_key = None
        if not found_group:
            search_key, old_anchor_rect = find_nearest_text_anchor(old_page, old_rect)
            if search_key:
                for p_idx in [csv_target, csv_target-1, csv_target+1]:
                    if p_idx < 0 or p_idx >= len(new_doc): continue
                    dest_page = new_doc[p_idx]
                    hits = dest_page.search_for(search_key)
                    if hits:
                        best_hit = min(hits, key=lambda h: abs(h.y0 - old_anchor_rect.y0) + abs(h.x0 - old_anchor_rect.x0))
                        dx = best_hit.x0 - old_anchor_rect.x0
                        dy = best_hit.y0 - old_anchor_rect.y0
                        csv_target = p_idx 
                        status = "AI鄰近對齊"
                        break

        if old_page_idx not in processed_offsets: processed_offsets[old_page_idx] = []
        processed_offsets[old_page_idx].append((old_rect, dx, dy, tag))

        print(f"{tag:<12} | {old_page_idx+1:>4} -> {csv_target+1:>4} | {status:<10} | [{search_key or '無'}]")

        new_h = new_doc[csv_target].rect.height
        mod_data = {
            "page": str(csv_target),
            "rect": transform_rect(rect_str, dx, dy, old_h, new_h)
        }

        if a.get("quadpoints"): mod_data["quadpoints"] = transform_pts(a.get("quadpoints"), dx, dy, old_h, new_h)
        if a.get("coords"): mod_data["coords"] = transform_pts(a.get("coords"), dx, dy, old_h, new_h)

        gestures = a.findall(".//ns:gesture", ns)
        if gestures:
            mod_data["gestures"] = [transform_pts(g.text, dx, dy, old_h, new_h) for g in gestures if g.text]

        mods[name] = mod_data


    def update_tag_pure(match):
        tag_content = match.group(0)
        name_match = re.search(r'\bname="([^"]+)"', tag_content, flags=re.IGNORECASE)
        if name_match:
            name = name_match.group(1)
            if name in mods:
                mod = mods[name]
                tag_content = re.sub(r'\bpage="\d+"', f'page="{mod["page"]}"', tag_content, flags=re.IGNORECASE)
                tag_content = re.sub(r'\brect="[\d\.,\-]+"', f'rect="{mod["rect"]}"', tag_content, flags=re.IGNORECASE)
                if "quadpoints" in mod:
                    tag_content = re.sub(r'\bquadpoints="[\d\.,\-]+"', f'quadpoints="{mod["quadpoints"]}"', tag_content, flags=re.IGNORECASE)
                if "coords" in mod:
                    tag_content = re.sub(r'\bcoords="[\d\.,\-]+"', f'coords="{mod["coords"]}"', tag_content, flags=re.IGNORECASE)
        return tag_content

    tags_to_replace = ['freetext', 'highlight', 'fileattachment', 'ink', 'square', 'stamp', 'circle', 'line', 'strikeout', 'underline', 'text', 'link']
    for t in tags_to_replace:
        content = re.sub(rf'<(?:[\w-]+:)?{t}\b[^>]*>', update_tag_pure, content, flags=re.IGNORECASE)

    def update_ink_gestures(match):
        block = match.group(0)
        name_m = re.search(r'\bname="([^"]+)"', block, flags=re.IGNORECASE)
        if name_m and name_m.group(1) in mods and "gestures" in mods[name_m.group(1)]:
            mod = mods[name_m.group(1)]
            g_idx = [0]
            def g_repl(m):
                if g_idx[0] < len(mod["gestures"]):
                    res = f"{m.group(1)}{mod['gestures'][g_idx[0]]}{m.group(3)}"
                    g_idx[0] += 1
                    return res
                return m.group(0)
            block = re.sub(r'(<(?:[\w-]+:)?gesture[^>]*>)(.*?)(</(?:[\w-]+:)?gesture>)', g_repl, block, flags=re.DOTALL | re.IGNORECASE)
        return block

    content = re.sub(r'<(?:[\w-]+:)?ink\b.*?</(?:[\w-]+:)?ink>', update_ink_gestures, content, flags=re.DOTALL | re.IGNORECASE)

    def fix_font_family(match):
        font_name = match.group(1).strip()
        font_name = font_name.replace("'", "").replace('"', "")

        if "微軟正黑體" in font_name or "Microsoft JhengHei" in font_name:
            font_name = "Microsoft JhengHei"
        return f"font-family:'{font_name}';"
        
    content = re.sub(r'font-family:\s*([^;>]+);', fix_font_family, content, flags=re.IGNORECASE)
    with open(xfdf_out, 'w', encoding='utf-8') as f:
        f.write(content)

    old_doc.close(); new_doc.close()