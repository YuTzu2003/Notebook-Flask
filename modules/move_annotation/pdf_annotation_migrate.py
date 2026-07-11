import os
import re
import math
import statistics
import fitz
import pdfrw
import pandas as pd
from rapidfuzz import fuzz, process

MANUAL_ADJUST_X = 0.0
MANUAL_ADJUST_Y = 0.0

# 頁面章節/部位掃描與判定
def get_pdf_sections(doc):
    sections = []
    current_section = None
    for page in doc:
        text = page.get_text()
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        is_app_b = False
        for line in lines[:3]:
            if "附錄B" in line or "Appendix B" in line:
                is_app_b = True
                break          
        if is_app_b:
            match_start = False
            organ_name = ""
            for i in range(len(lines) - 2):
                l1 = lines[i]
                l2 = lines[i+1]
                l3 = lines[i+2]
                if l1.isdigit() and re.match(r'^C\d+.*C\d+', l3):
                    organ_name = l2
                    match_start = True
                    break
                elif re.match(r'^C\d+.*C\d+', l2) and not l1.isdigit() and "附錄B" not in l1:
                    organ_name = l1
                    match_start = True
                    break
            if match_start:
                current_section = organ_name
        else:
            current_section = None  
        sections.append(current_section)
    return sections


def sections_match(sec1, sec2):
    if not sec1 or not sec2:
        return sec1 == sec2
    s1 = sec1.lower().replace(" ", "").replace("/", "").replace("-", "")
    s2 = sec2.lower().replace(" ", "").replace("/", "").replace("-", "")
    return (s1 in s2) or (s2 in s1)


# 錨點演算法輔助函式
def get_word_score(w, annot_center, annot_rect):
    w_rect = fitz.Rect(w[:4])
    dist = math.sqrt(((w_rect.x0 + w_rect.x1)/2 - annot_center[0])**2 + ((w_rect.y0 + w_rect.y1)/2 - annot_center[1])**2)
    if annot_rect.intersects(w_rect):
        dist *= 0.3
    text = w[4].strip()
    if len(text) < 2:
        dist += 1000
    if text.isdigit():
        dist += 200  
    return dist

def filtered_median(values, max_deviation=15):
    if not values:
        return 0
    med = statistics.median(values)
    filtered = [v for v in values if abs(v - med) < max_deviation]
    return statistics.median(filtered) if filtered else med

# 空間幾何與錨點比對定位
def find_precise_offset(page_old, page_new, old_rect, processed_offsets, words_cache=None):
    for entry in processed_offsets:
        if len(entry) == 5:
            ref_rect, ref_dx, ref_dy, ref_target_idx, is_direct = entry
            if not is_direct:
                continue
        else:
            ref_rect, ref_dx, ref_dy, ref_target_idx = entry
        if abs(old_rect.x0 - ref_rect.x0) < 50 and abs(old_rect.y0 - ref_rect.y0) < 120:
            return ref_dx, ref_dy, ref_target_idx, "群組", 999 
        
    def get_words(p):
        if words_cache is not None:
            key = (id(p.parent), p.number)
            if key not in words_cache:
                words_cache[key] = p.get_text("words")
            return words_cache[key]
        return p.get_text("words")

    words_old = get_words(page_old)
    if not words_old: return 0, 0, None, "無舊文保底", 0
    
    words_new = get_words(page_new)
    if not words_new: return 0, 0, None, "無新文保底", 0
    freetext_rects_old = [annot.rect for annot in page_old.annots() if annot.type[1] == 'FreeText']
    if freetext_rects_old:
        filtered_words_old = []
        for w in words_old:
            w_rect = fitz.Rect(w[:4])
            is_ft = False
            for r in freetext_rects_old:
                if w_rect.intersects(r):
                    intersect = w_rect & r
                    if intersect.get_area() / w_rect.get_area() > 0.5:
                        is_ft = True
                        break
            if not is_ft:
                filtered_words_old.append(w)
        words_old = filtered_words_old

    freetext_rects_new = [annot.rect for annot in page_new.annots() if annot.type[1] == 'FreeText']
    if freetext_rects_new:
        filtered_words_new = []
        for w in words_new:
            w_rect = fitz.Rect(w[:4])
            is_ft = False
            for r in freetext_rects_new:
                if w_rect.intersects(r):
                    intersect = w_rect & r
                    if intersect.get_area() / w_rect.get_area() > 0.5:
                        is_ft = True
                        break
            if not is_ft:
                filtered_words_new.append(w)
        words_new = filtered_words_new

    # 對舊版文字進行打分，選出離註解最近且最適合的 12 個單詞作為候選錨點
    annot_center = ((old_rect.x0 + old_rect.x1)/2, (old_rect.y0 + old_rect.y1)/2)
    sorted_words = sorted(words_old, key=lambda w: get_word_score(w, annot_center, old_rect))
    candidate_anchors = sorted_words[:12] 

    offsets_x = []
    offsets_y = []
    new_texts = [nw[4].strip() for nw in words_new]

    # 在新版頁面中搜尋這 12 個錨點
    for cw in candidate_anchors:
        text = cw[4].strip()
        if len(text) < 3: continue 
        
        cw_rect_old = fitz.Rect(cw[:4])
        hits = page_new.search_for(text)
        
        # 如果無法精準搜尋，啟動模糊相似度搜尋 (Fuzzy Match)
        if (not hits or len(hits) > 3) and len(text) >= 3:
            matches = process.extract(text, new_texts, scorer=fuzz.ratio, limit=3)
            for m_text, score, idx in matches:
                if score > 85:
                    nw_rect = fitz.Rect(words_new[idx][:4])
                    # 空間鄰近篩選：只接受垂直距離在頁面高度 50% 以內的匹配，避免飛到其他頁首頁尾
                    if abs(nw_rect.y0 - cw_rect_old.y0) < page_new.rect.height * 0.5:
                        hits.append(nw_rect)

        if hits:
            # 挑選空間上最接近的匹配項計算偏移
            best_hit = min(hits, key=lambda h: abs(h.y0 - cw_rect_old.y0) + abs(h.x0 - cw_rect_old.x0))
            dx = best_hit.x0 - cw_rect_old.x0
            dy = best_hit.y0 - cw_rect_old.y0
            # 位移過大（大於頁面尺寸 40%）視為異常，不予採信
            if abs(dx) < page_new.rect.width * 0.4 and abs(dy) < page_new.rect.height * 0.4:
                offsets_x.append(dx)
                offsets_y.append(dy)

    # 根據匹配錨點數量決定置信度狀態
    if len(offsets_x) >= 2:
        return filtered_median(offsets_x), filtered_median(offsets_y), None, "精準AI", len(offsets_x)
    elif len(offsets_x) == 1:
        return offsets_x[0], offsets_y[0], None, "弱AI", 1

    return 0, 0, None, "兜底零位移", 0

# 全文 context 模糊比對演算法 (適用於劃線、螢光筆)
def find_text_based_position(page_old, page_new, old_rect_f, rawdict_cache=None, words_cache=None, old_quadpoints=None):
    def get_page_chars(page):
        if rawdict_cache is not None:
            key = (id(page.parent), page.number)
            if key in rawdict_cache:
                return rawdict_cache[key]
        raw = page.get_text("rawdict")
        chars = []
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    for char in span.get("chars", []):
                        c = char.get("c")
                        bbox = char.get("bbox")
                        if c and bbox:
                            c_clean = c.strip()
                            if c_clean:
                                chars.append((bbox[0], bbox[1], bbox[2], bbox[3], c_clean))
        if rawdict_cache is not None:
            rawdict_cache[(id(page.parent), page.number)] = chars
        return chars

    def get_words(p):
        if words_cache is not None:
            key = (id(p.parent), p.number)
            if key not in words_cache:
                words_cache[key] = p.get_text("words")
            return words_cache[key]
        return p.get_text("words")

    # 1. 提取舊頁面中被標記覆蓋的字元
    old_chars = get_page_chars(page_old)
    
    quad_rects = []
    old_h = page_old.rect.height
    if old_quadpoints:
        try:
            pts = [float(x) for x in old_quadpoints]
            for i in range(0, len(pts), 8):
                if i + 7 < len(pts):
                    line_pts = pts[i:i+8]
                    xs = line_pts[0::2]
                    ys = line_pts[1::2]
                    quad_rects.append(fitz.Rect(min(xs), old_h - max(ys), max(xs), old_h - min(ys)))
        except Exception as e:
            print("Error parsing old_quadpoints in find_text_based_position:", e)

    covered_indices = []
    for idx, c in enumerate(old_chars):
        c_rect = fitz.Rect(c[:4])
        is_covered = False
        if quad_rects:
            for qr in quad_rects:
                if qr.intersects(c_rect):
                    overlap = qr & c_rect
                    if overlap.get_area() / max(c_rect.get_area(), 1) > 0.3:
                        is_covered = True
                        break
        else:
            if old_rect_f.intersects(c_rect):
                overlap = old_rect_f & c_rect
                if overlap.get_area() / max(c_rect.get_area(), 1) > 0.3:
                    is_covered = True
        
        if is_covered:
            covered_indices.append(idx)

    if not covered_indices:
        return None

    # 2. 獲取新頁面字元
    new_chars = get_page_chars(page_new)
    if not new_chars:
        return None

    # --- 全頁字元對齊對位模組 (Global Page-Level Alignment with Space/Case Normalization) ---
    def build_normalized_mapping(char_list):
        import unicodedata
        norm_str = ""
        index_map = []
        for idx, c in enumerate(char_list):
            char_text = c[4]
            # 過濾控制字元、項目符號及隱形字元
            if char_text.strip() and char_text not in ['\uf09f', '\u2022', '\xad', '\u200b']:
                # 1. NFKC 標準化 (將全形英文/數字轉換為半形，並將複合字元分解為標準形式)
                norm_c = unicodedata.normalize('NFKC', char_text).lower()
                # 2. 標點符號與括號標準化，消除新舊版因為字型或輸入法不同導致的對位落差
                norm_c = norm_c.replace('（', '(').replace('）', ')')
                norm_c = norm_c.replace('：', ':').replace('；', ';')
                norm_c = norm_c.replace('，', ',').replace('。', '.')
                norm_c = norm_c.replace('、', ',')
                if norm_c:
                    # 保留首個字元以確保 1-to-1 索引長度對齊
                    norm_str += norm_c[0]
                    index_map.append(idx)
        return norm_str, index_map

    old_norm_str, old_index_map = build_normalized_mapping(old_chars)
    new_norm_str, new_index_map = build_normalized_mapping(new_chars)
    
    import difflib
    matcher = difflib.SequenceMatcher(None, old_norm_str, new_norm_str, autojunk=False)
    matching_blocks = matcher.get_matching_blocks()
    
    covered_norm_indices = [i for i, x in enumerate(old_index_map) if x in covered_indices]
    mapped_norm_indices = []
    for x in covered_norm_indices:
        for a, b, size in matching_blocks:
            if a <= x < a + size:
                mapped_norm_indices.append(b + (x - a))
                break
                
    if not mapped_norm_indices:
        return None
        
    mapped_orig_indices = [new_index_map[x] for x in mapped_norm_indices]
    matched = [new_chars[x] for x in mapped_orig_indices]
    matched.sort(key=lambda x: (x[1], x[0])) # 確保按閱讀順序排序

    if not matched:
        return None

    # --- 雙重驗證過濾器 (False Positive Validator) ---
    # 1. 確保匹配比例足夠高 (>= 60%)
    match_rate = len(mapped_norm_indices) / max(len(covered_norm_indices), 1)
    if match_rate < 0.60:
        return None

    # 2. 針對短字句 (長度小於 6) 限制垂直位移，防止高頻率重複單字錯位
    norm_len = len(covered_norm_indices)
    if norm_len < 6:
        y_new_center = (min(c[1] for c in matched) + max(c[3] for c in matched)) / 2
        covered = [old_chars[x] for x in covered_indices]
        y_old_center = (min(c[1] for c in covered) + max(c[3] for c in covered)) / 2
        if abs(y_new_center - y_old_center) > 150:
            return None

    new_words = get_words(page_new)
    english_word_rects = [fitz.Rect(w[:4]) for w in new_words if not any('\u4e00' <= char <= '\u9fff' for char in w[4])]
    
    expanded_matched = []
    for c in matched:
        c_x0, c_y0, c_x1, c_y1, char_text = c
        c_rect = fitz.Rect(c_x0, c_y0, c_x1, c_y1)
        best_word = None
        for w_rect in english_word_rects:
            if c_rect.intersects(w_rect):
                overlap = c_rect & w_rect
                if overlap.get_area() / max(c_rect.get_area(), 1) > 0.5:
                    best_word = w_rect
                    break
        if best_word:
            expanded_matched.append((min(c_x0, best_word.x0), c_y0, max(c_x1, best_word.x1), c_y1, char_text))
        else:
            expanded_matched.append(c)
    matched = expanded_matched

    new_h = page_new.rect.height

    # 將匹配字元依行分組 (小於 10pt 視為同行，容忍上下標/公式等引起的微小垂直位移)
    lines = []
    current_line = [matched[0]]
    for w in matched[1:]:
        if abs(w[1] - current_line[-1][1]) < 10:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
    lines.append(current_line)

    quads = []
    all_rects = []

    for line_words in lines:
        x0 = min(w[0] for w in line_words)
        y0 = min(w[1] for w in line_words)
        x1 = max(w[2] for w in line_words)
        y1 = max(w[3] for w in line_words)
        all_rects.append(fitz.Rect(x0, y0, x1, y1))

        # 輸出 PDF 座標四邊形（左上、右上、左下、右下）
        quads.extend([
            x0, new_h - y0,   # top-left
            x1, new_h - y0,   # top-right
            x0, new_h - y1,   # bottom-left
            x1, new_h - y1,   # bottom-right
        ])

    # 計算聯集包圍矩形
    union_rect = all_rects[0]
    for rect in all_rects[1:]:
        union_rect |= rect

    pdf_rect = [union_rect.x0, new_h - union_rect.y1, union_rect.x1, new_h - union_rect.y0]

    # 計算舊頁面中覆蓋矩形
    covered = [old_chars[x] for x in covered_indices]
    x0_old = min(c[0] for c in covered)
    y0_old = min(c[1] for c in covered)
    x1_old = max(c[2] for c in covered)
    y1_old = max(c[3] for c in covered)
    old_h = page_old.rect.height
    pdf_rect_old = [x0_old, old_h - y1_old, x1_old, old_h - y0_old]

    return quads, pdf_rect, pdf_rect_old


# PDF Main Pipeline
def migrate_all_to_pdf(old_pdf, new_pdf, csv_mapping, output_pdf, diff_pages_str=""):
    PN = pdfrw.PdfName
    reader_old = pdfrw.PdfReader(old_pdf)
    reader_new = pdfrw.PdfReader(new_pdf)
    doc_old, doc_new = fitz.open(old_pdf), fitz.open(new_pdf)   
    df = pd.read_csv(csv_mapping, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    mapping = {}
    reverse_mapping = {}
    for _, r in df.iterrows():
        if pd.notna(r.get("New_Page")) and str(r.get("New_Page")).strip() != "":
            old_p = int(r["Old_Page"]) - 1
            new_p = int(r["New_Page"]) - 1
            mapping[old_p] = new_p
            reverse_mapping[new_p] = old_p
    old_sections = get_pdf_sections(doc_old)
    new_sections = get_pdf_sections(doc_new)

    processed_offsets_map = {}
    rawdict_cache = {}
    words_cache = {}

    for old_idx, new_idx in mapping.items():
        if old_idx >= len(doc_old) or new_idx >= len(doc_new): continue
        p_old_f, p_new_f = doc_old[old_idx], doc_new[new_idx]
        p_new_p = reader_new.pages[new_idx]

        annots = reader_old.pages[old_idx].Annots
        if not annots: continue
        if not p_new_p.Annots: p_new_p.Annots = pdfrw.PdfArray()
        if old_idx not in processed_offsets_map: processed_offsets_map[old_idx] = []
        for annot in annots:
            if not annot.get('/Rect'): continue
            subtype = annot.get('/Subtype')
            r = [float(x) for x in annot['/Rect']]
            old_h = p_old_f.rect.height
            old_rect_f = fitz.Rect(r[0], old_h - r[3], r[2], old_h - r[1])
            target_new_idx = new_idx
            dx, dy = 0, 0
            text_result = None
            overlaps_freetext = False
            freetext_idx = None
            if subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly', '/Square', '/Circle', '/Redact', '/Text']:
                for oidx, other_annot in enumerate(annots):
                    if other_annot == annot:
                        continue
                    if other_annot.get('/Subtype') == '/FreeText':
                        other_r = [float(x) for x in other_annot['/Rect']]
                        other_rect_f = fitz.Rect(other_r[0], old_h - other_r[3], other_r[2], old_h - other_r[1])
                        if old_rect_f.intersects(other_rect_f):
                            intersect = old_rect_f & other_rect_f
                            if intersect.get_area() / max(min(old_rect_f.get_area(), other_rect_f.get_area()), 1) > 0.05:
                                overlaps_freetext = True
                                freetext_idx = oidx
                                break

            ft_dx, ft_dy, ft_target_idx = None, None, None
            if overlaps_freetext and freetext_idx is not None:
                ft_annot = annots[freetext_idx]
                ft_r = [float(x) for x in ft_annot['/Rect']]
                ft_rect_f = fitz.Rect(ft_r[0], old_h - ft_r[3], ft_r[2], old_h - ft_r[1])
                found_ft = False
                for entry in processed_offsets_map[old_idx]:
                    ref_rect, ref_dx, ref_dy, ref_target_idx, is_direct = entry
                    if abs(ft_rect_f.x0 - ref_rect.x0) < 5 and abs(ft_rect_f.y0 - ref_rect.y0) < 5:
                        found_ft = True
                        ft_dx, ft_dy, ft_target_idx = ref_dx, ref_dy, ref_target_idx
                        break
                
                if not found_ft:
                    ft_dx, ft_dy, ft_target_idx, ft_status, ft_match_count = find_precise_offset(
                        p_old_f, p_new_f, ft_rect_f, processed_offsets_map[old_idx], words_cache
                    )
                    if ft_target_idx is None:
                        ft_target_idx = new_idx
                    processed_offsets_map[old_idx].append((ft_rect_f, ft_dx, ft_dy, ft_target_idx, True))

            # 文字內容精準對位 (適用於文字標註、外框等)
            if overlaps_freetext and ft_dx is not None:
                dx = ft_dx
                dy = ft_dy
                target_new_idx = ft_target_idx
            else:
                if not overlaps_freetext and subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly', '/Square', '/Circle', '/Redact']:
                    old_quadpoints = annot.get(PN('QuadPoints'))
                    text_result = find_text_based_position(p_old_f, p_new_f, old_rect_f, rawdict_cache, words_cache, old_quadpoints)
                    if not text_result:
                        # 提取標記覆蓋的舊版字串，僅在字串長度大於或等於 6 個字時才允許跨頁搜尋，防範短字詞跳頁誤判
                        annot_text = p_old_f.get_text("text", clip=old_rect_f).strip().replace('\n', '')
                        annot_text_clean = "".join([c for c in annot_text if c.strip() and c not in ['\uf09f', '\u2022']])
                        if len(annot_text_clean) >= 6:
                            for offset in [1, -1, 2]:
                                cand_idx = new_idx + offset
                                if 0 <= cand_idx < len(doc_new):
                                    if not sections_match(old_sections[old_idx], new_sections[cand_idx]):
                                        continue
                                    res = find_text_based_position(p_old_f, doc_new[cand_idx], old_rect_f, rawdict_cache, words_cache, old_quadpoints)
                                    if res:
                                        text_result = res
                                        target_new_idx = cand_idx
                                        break
                    if text_result:
                        new_quads, new_rect, pdf_rect_old = text_result
                        left_pad = r[0] - pdf_rect_old[0]
                        right_pad = r[2] - pdf_rect_old[2]
                        bottom_pad = r[1] - pdf_rect_old[1]
                        top_pad = r[3] - pdf_rect_old[3]
                        
                        if subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly']:
                            annot[PN('QuadPoints')] = pdfrw.PdfArray([pdfrw.PdfObject(f"{x:.4f}") for x in new_quads])
                            x0_min = min(new_quads[0::2])
                            y0_min = min(new_quads[1::2])
                            x1_max = max(new_quads[0::2])
                            y1_max = max(new_quads[1::2])
                            new_rect_annot = [x0_min, y0_min, x1_max, y1_max]
                        else:
                            new_rect_annot = [
                                new_rect[0] + left_pad,
                                new_rect[1] + bottom_pad,
                                new_rect[2] + right_pad,
                                new_rect[3] + top_pad
                            ]
                        
                        dx = new_rect_annot[0] - r[0]
                        dy = r[1] - new_rect_annot[1]

                        w_old = r[2] - r[0]
                        h_old = r[3] - r[1]
                        w_new = new_rect_annot[2] - new_rect_annot[0]
                        h_new = new_rect_annot[3] - new_rect_annot[1]

                # 無文字對位結果時，採用錨點比對或繼承群組位移
                status = "未群組"
                if not text_result:
                    # 對於螢光筆、底線等標記，若無法匹配到文字，直接留在原本的物理位置 (原地)，不要隨錨點或群組位移偏移
                    if subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly']:
                        target_new_idx = new_idx
                        cand_p_new = doc_new[target_new_idx]
                        dx = (cand_p_new.rect.x0 - p_old_f.rect.x0)
                        dy = (cand_p_new.rect.y0 - p_old_f.rect.y0)
                    else:
                        text_dx, text_dy, group_target_idx, status, match_count = find_precise_offset(p_old_f, p_new_f, old_rect_f, processed_offsets_map[old_idx], words_cache)                  
                        if status == "群組" and group_target_idx is not None:
                            target_new_idx = group_target_idx
                            dx = text_dx
                            dy = text_dy
                        else:
                            best_match_count = -1
                            best_dx, best_dy = 0, 0
                            best_target_idx = new_idx
                            for offset in [0, 1, -1, 2]:
                                cand_idx = new_idx + offset
                                if 0 <= cand_idx < len(doc_new):
                                    if not sections_match(old_sections[old_idx], new_sections[cand_idx]):
                                        continue
                                    cand_p_new = doc_new[cand_idx]
                                    cand_dx, cand_dy, _, cand_status, cand_match_count = find_precise_offset(p_old_f, cand_p_new, old_rect_f, [], words_cache)
                                    if cand_status in ["精準AI", "弱AI"]:
                                        if cand_match_count > best_match_count:
                                            best_match_count = cand_match_count
                                            best_dx = cand_dx
                                            best_dy = cand_dy
                                            best_target_idx = cand_idx
                            
                            if best_match_count == -1:
                                target_new_idx = new_idx
                                cand_p_new = doc_new[target_new_idx]
                                dx = (cand_p_new.rect.x0 - p_old_f.rect.x0)
                                dy = (cand_p_new.rect.y0 - p_old_f.rect.y0)
                            else:
                                target_new_idx = best_target_idx
                                cand_p_new = doc_new[target_new_idx]
                                dx = best_dx + (cand_p_new.rect.x0 - p_old_f.rect.x0)
                                dy = best_dy + (cand_p_new.rect.y0 - p_old_f.rect.y0)
            is_direct = (text_result is not None) or (status != "群組")
            processed_offsets_map[old_idx].append((old_rect_f, dx, dy, target_new_idx, is_direct))

            # 註解屬性清理與平移寫入：
            # 1. 對於 FreeText，保留 /AP 與 /DA 屬性以完整顯示中文字型。
            # 2. 對於螢光筆與底線等，刪除舊的 /AP 外觀流，強迫 PDF 閱讀器根據新的 /QuadPoints 重新生成正確的畫筆外觀，避免劃一大片。
            if subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly']:
                for key in ['/AP', '/RD', '/IT']:
                    if annot.get(key):
                        del annot[key]

            new_rect = [r[0] + dx, r[1] - dy, r[2] + dx, r[3] - dy]
            if text_result:
                new_rect = new_rect_annot
            annot.Rect = pdfrw.PdfArray([pdfrw.PdfObject(f"{x:.4f}") for x in new_rect])

            # QuadPoints、Vertices與箭頭端點
            if not text_result or subtype not in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly']:
                for key_name in ['QuadPoints', 'Vertices', 'L']:
                    val = annot.get(PN(key_name))
                    if val:
                        pts = [float(x) for x in val]
                        new_pts = [pdfrw.PdfObject(f"{(pts[i]+dx if i%2==0 else pts[i]-dy):.4f}") for i in range(len(pts))]
                        annot[PN(key_name)] = pdfrw.PdfArray(new_pts)

            # InkList畫筆跡劃線
            il = annot.get('/InkList')
            if il:
                new_ink = pdfrw.PdfArray()
                for path in il:
                    pts = [float(x) for x in path]
                    new_path = [pdfrw.PdfObject(f"{(pts[i]+dx if i%2==0 else pts[i]-dy):.4f}") for i in range(len(pts))]
                    new_ink.append(pdfrw.PdfArray(new_path))
                annot.InkList = new_ink
            p_target_p = reader_new.pages[target_new_idx]
            if annot.get('/P'):
                annot.P = p_target_p
            if not p_target_p.Annots:
                p_target_p.Annots = pdfrw.PdfArray()
            p_target_p.Annots.append(annot)
    writer = pdfrw.PdfWriter()
    writer.write(output_pdf, reader_new)
    doc_old.close()
    doc_new.close()

    # 目錄書籤：頁碼差異自動插入提示書籤
    if diff_pages_str:
        diff_pages = [int(p) for p in str(diff_pages_str).split(",") if p.strip()]
        if diff_pages:
            final_doc = fitz.open(output_pdf)
            toc = final_doc.get_toc()

            for p in diff_pages:
                new_idx = p - 1
                old_idx = reverse_mapping.get(new_idx, None)
                if old_idx is not None:
                    toc.append([1, f"內容變更 (原 p.{old_idx + 1} -> 新 p.{p})", p])
                else:
                    toc.append([1, f"新增內容 (新 p.{p})", p])

            final_doc.set_toc(toc)
            tmp_pdf = output_pdf + ".tmp.pdf"
            final_doc.save(tmp_pdf)
            final_doc.close()
            os.replace(tmp_pdf, output_pdf)