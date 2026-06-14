import pdfrw
import fitz
import pandas as pd
import math
import statistics
import os
import re
from rapidfuzz import fuzz, process

MANUAL_ADJUST_X = 0.0
MANUAL_ADJUST_Y = 0.0


def get_pdf_sections(doc):
    """掃描 PDF，自動判定各個頁面對應的部位章節"""
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
    """比對兩個部位名稱是否相同（支援相似/子字串匹配）"""
    if not sec1 or not sec2:
        return sec1 == sec2
    s1 = sec1.lower().replace(" ", "").replace("/", "").replace("-", "")
    s2 = sec2.lower().replace(" ", "").replace("/", "").replace("-", "")
    return (s1 in s2) or (s2 in s1)


def get_word_score(w, annot_center, annot_rect):
    """計算單詞作為錨點的優劣分數：越低越好"""
    w_rect = fitz.Rect(w[:4])
    dist = math.sqrt(((w_rect.x0 + w_rect.x1)/2 - annot_center[0])**2 + 
                     ((w_rect.y0 + w_rect.y1)/2 - annot_center[1])**2)
    if annot_rect.intersects(w_rect):
        dist *= 0.3
    
    text = w[4].strip()
    if len(text) < 2:
        dist += 1000 
    if text.isdigit():
        dist += 200 
        
    return dist

def filtered_median(values, max_deviation=15):
    """F: 過濾離群值後取中位數，避免少數錯誤錨點干擾結果"""
    if not values:
        return 0
    med = statistics.median(values)
    filtered = [v for v in values if abs(v - med) < max_deviation]
    return statistics.median(filtered) if filtered else med

def find_precise_offset(page_old, page_new, old_rect, processed_offsets, words_cache=None):
    for entry in processed_offsets:
        if len(entry) == 5:
            ref_rect, ref_dx, ref_dy, ref_target_idx, is_direct = entry
            if not is_direct:
                continue
        else:
            ref_rect, ref_dx, ref_dy, ref_target_idx = entry
            
        if abs(old_rect.x0 - ref_rect.x0) < 50 and abs(old_rect.y0 - ref_rect.y0) < 120:
            return ref_dx, ref_dy, ref_target_idx, "群組", 999  # 群組享有最高優先權

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

    # Filter out words that belong to FreeText annotations (user typed notes)
    # since their content does not belong to the background manual text.
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

    annot_center = ((old_rect.x0 + old_rect.x1)/2, (old_rect.y0 + old_rect.y1)/2)
    sorted_words = sorted(words_old, key=lambda w: get_word_score(w, annot_center, old_rect))
    candidate_anchors = sorted_words[:12] 

    offsets_x = []
    offsets_y = []
    new_texts = [nw[4].strip() for nw in words_new]

    for cw in candidate_anchors:
        text = cw[4].strip()
        if len(text) < 3: continue 
        
        cw_rect_old = fitz.Rect(cw[:4])
        hits = page_new.search_for(text)
        if (not hits or len(hits) > 3) and len(text) >= 3:
            matches = process.extract(text, new_texts, scorer=fuzz.ratio, limit=3)
            for m_text, score, idx in matches:
                if score > 85:
                    nw_rect = fitz.Rect(words_new[idx][:4])
                    # D: 空間鄰近篩選 — 只接受垂直距離在頁面高度 50% 以內的匹配
                    if abs(nw_rect.y0 - cw_rect_old.y0) < page_new.rect.height * 0.5:
                        hits.append(nw_rect)

        if hits:
            best_hit = min(hits, key=lambda h: abs(h.y0 - cw_rect_old.y0) + abs(h.x0 - cw_rect_old.x0))
            dx = best_hit.x0 - cw_rect_old.x0
            dy = best_hit.y0 - cw_rect_old.y0
            if abs(dx) < page_new.rect.width * 0.4 and abs(dy) < page_new.rect.height * 0.4:
                offsets_x.append(dx)
                offsets_y.append(dy)

    if len(offsets_x) >= 2:
        return filtered_median(offsets_x), filtered_median(offsets_y), None, "精準AI", len(offsets_x)
    elif len(offsets_x) == 1:
        return offsets_x[0], offsets_y[0], None, "弱AI", 1

    return 0, 0, None, "兜底零位移", 0


def find_text_based_position(page_old, page_new, old_rect_f, rawdict_cache=None, words_cache=None):
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
    covered_indices = []
    for idx, c in enumerate(old_chars):
        c_rect = fitz.Rect(c[:4])
        if old_rect_f.intersects(c_rect):
            overlap = old_rect_f & c_rect
            if overlap.get_area() / max(c_rect.get_area(), 1) > 0.3:
                covered_indices.append(idx)

    if not covered_indices:
        return None

    # 找出核心覆蓋文字的起訖點
    start_idx = covered_indices[0]
    end_idx = covered_indices[-1]
    covered = old_chars[start_idx:end_idx + 1]

    # 2. 核心改進：建立含有前後文(Context)的舊版目標字串，用來解決重複句子的問題
    context_len = 6
    ctx_start = max(0, start_idx - context_len)
    ctx_end = min(len(old_chars), end_idx + 1 + context_len)
    
    old_pattern_str = "".join([c[4] for c in old_chars[ctx_start:ctx_end]])
    len_prefix = start_idx - ctx_start
    len_core = (end_idx - start_idx) + 1

    # 3. 獲取新頁面字元
    new_chars = get_page_chars(page_new)
    if not new_chars:
        return None

    new_str = "".join([c[4] for c in new_chars])
    
    best_match_start = -1
    best_match_end = -1
    best_metric = -9999.0

    # 4. 先嘗試新版有沒有完全一模一樣的字串 (包含前後文)
    exact_idx = new_str.find(old_pattern_str)
    if exact_idx != -1:
        # 新版可能有多處完全相同的背景字，用距離來判定最接近哪一個
        for start_char_idx in range(len(new_chars) - len(old_pattern_str) + 1):
            cand_str = "".join([nc[4] for nc in new_chars[start_char_idx : start_char_idx + len(old_pattern_str)]])
            if cand_str == old_pattern_str:
                cand_x0 = new_chars[start_char_idx + len_prefix][0]
                cand_y0 = new_chars[start_char_idx + len_prefix][1]
                dist = abs(cand_x0 - old_rect_f.x0) + abs(cand_y0 - old_rect_f.y0)
                metric = 1.0 - (dist / 10000.0)
                if metric > best_metric:
                    best_metric = metric
                    best_match_start = start_char_idx
                    best_match_end = start_char_idx + len(old_pattern_str)
                    
    # 5. 如果完全匹配不到，代表新舊版之間多了逗號「，」或空格！啟動滑動視窗模糊比對
    if best_match_start == -1:
        window_size = len(old_pattern_str)
        for start in range(len(new_chars) - window_size + 3):
            for delta in [-2, -1, 0, 1, 2]: # 彈性伸縮視窗長度，容忍新版多出標點符號
                end = start + window_size + delta
                if end > len(new_chars) or end <= start:
                    continue
                    
                new_cand_str = "".join([nc[4] for nc in new_chars[start:end]])
                
                # 模糊比對整句話（含前後文）
                score = fuzz.ratio(old_pattern_str, new_cand_str) / 100.0
                
                # 加入距離懲罰，防止網底亂飛到其他頁首頁尾
                cand_x0 = new_chars[start][0]
                cand_y0 = new_chars[start][1]
                dist = abs(cand_x0 - old_rect_f.x0) + abs(cand_y0 - old_rect_f.y0)
                metric = score - (dist / 8000.0)
                
                if score > 0.82 and metric > best_metric: # 門檻設為 82%
                    best_metric = metric
                    best_match_start = start
                    best_match_end = end

    if best_match_start < 0:
        return None

    # 6. 從新頁面的匹配區間中，等比例切出黃色網底對應的核心文字
    total_matched_chars = new_chars[best_match_start:best_match_end]
    ratio_start = len_prefix / len(old_pattern_str)
    ratio_core = len_core / len(old_pattern_str)
    
    new_core_start = int(len(total_matched_chars) * ratio_start)
    new_core_end = new_core_start + int(len(total_matched_chars) * ratio_core)
    
    new_core_start = max(0, min(new_core_start, len(total_matched_chars) - 1))
    new_core_end = max(new_core_start + 1, min(new_core_end, len(total_matched_chars)))
    
    matched = total_matched_chars[new_core_start:new_core_end]
    if not matched:
        return None

    # --- WORD EXPANSION LOGIC ---
    new_words = get_words(page_new)
    expanded_matched = []
    for c in matched:
        c_x0, c_y0, c_x1, c_y1, char_text = c
        c_rect = fitz.Rect(c_x0, c_y0, c_x1, c_y1)
        best_word = None
        for w in new_words:
            if any('\u4e00' <= char <= '\u9fff' for char in w[4]):
                continue
            w_rect = fitz.Rect(w[:4])
            if c_rect.intersects(w_rect):
                overlap = c_rect & w_rect
                if overlap.get_area() / c_rect.get_area() > 0.5:
                    best_word = w_rect
                    break
        if best_word:
            expanded_matched.append((min(c_x0, best_word.x0), c_y0, max(c_x1, best_word.x1), c_y1, char_text))
        else:
            expanded_matched.append(c)
    matched = expanded_matched
    # ----------------------------

    new_h = page_new.rect.height

    # 按行分組
    lines = []
    current_line = [matched[0]]
    for w in matched[1:]:
        if abs(w[1] - current_line[-1][1]) < 6:  # 稍微放寬至 6pt 判定同行
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

        quads.extend([
            x0, new_h - y0,   # top-left
            x1, new_h - y0,   # top-right
            x0, new_h - y1,   # bottom-left
            x1, new_h - y1,   # bottom-right
        ])

    # 計算包圍矩形
    union_rect = all_rects[0]
    for rect in all_rects[1:]:
        union_rect |= rect

    pdf_rect = [union_rect.x0, new_h - union_rect.y1, union_rect.x1, new_h - union_rect.y0]

    # 計算舊頁面中 covers 矩形
    x0_old = min(c[0] for c in covered)
    y0_old = min(c[1] for c in covered)
    x1_old = max(c[2] for c in covered)
    y1_old = max(c[3] for c in covered)
    old_h = page_old.rect.height
    pdf_rect_old = [x0_old, old_h - y1_old, x1_old, old_h - y0_old]

    return quads, pdf_rect, pdf_rect_old


def migrate_all_to_pdf(old_pdf, new_pdf, csv_mapping, output_pdf, diff_pages_str=""):
    PN = pdfrw.PdfName
    reader_old = pdfrw.PdfReader(old_pdf)
    reader_new = pdfrw.PdfReader(new_pdf)
    doc_old, doc_new = fitz.open(old_pdf), fitz.open(new_pdf)

    if not os.path.exists(csv_mapping):
        print(f"找不到對應表：{csv_mapping}")
        return

    df = pd.read_csv(csv_mapping, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    mapping = {int(r["Old_Page"]) - 1: int(r["Matched_New_Page"]) - 1 for _, r in df.iterrows()}

    # 紀錄舊版對應到新版，用於後續書籤文字
    reverse_mapping = {int(r["Matched_New_Page"]) - 1: int(r["Old_Page"]) - 1 for _, r in df.iterrows()}

    # 提取舊版與新版的部位章節對應
    old_sections = get_pdf_sections(doc_old)
    new_sections = get_pdf_sections(doc_new)

    processed_offsets_map = {}
    rawdict_cache = {}
    words_cache = {}

    for old_idx, new_idx in mapping.items():
        if old_idx >= len(doc_old) or new_idx >= len(doc_new): continue
        p_old_f, p_new_f = doc_old[old_idx], doc_new[new_idx]
        p_new_p = reader_new.pages[new_idx]
        page_origin_dx = p_new_f.rect.x0 - p_old_f.rect.x0
        page_origin_dy = p_new_f.rect.y0 - p_old_f.rect.y0

        annots = reader_old.pages[old_idx].Annots
        if not annots: continue
        if not p_new_p.Annots: p_new_p.Annots = pdfrw.PdfArray()
        if old_idx not in processed_offsets_map: processed_offsets_map[old_idx] = []

        # Check overlaps and lazy-evaluate FreeText annotations in the original order.
        for annot in annots:
            if not annot.get('/Rect'): continue

            subtype = annot.get('/Subtype')
            r = [float(x) for x in annot['/Rect']]
            old_h = p_old_f.rect.height
            old_rect_f = fitz.Rect(r[0], old_h - r[3], r[2], old_h - r[1])

            target_new_idx = new_idx
            dx, dy = 0, 0
            text_result = None
            scale_x, scale_y = 1.0, 1.0

            # Check if this annotation overlaps with any FreeText annotation on the old page
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
                            # Lower threshold and use min area to ensure robust overlap detection
                            if intersect.get_area() / max(min(old_rect_f.get_area(), other_rect_f.get_area()), 1) > 0.05:
                                overlaps_freetext = True
                                freetext_idx = oidx
                                break

            # If overlaps with a FreeText, ensure the FreeText's offset is already calculated.
            # If not yet calculated, lazy evaluate it now and store it in processed_offsets_map.
            ft_dx, ft_dy, ft_target_idx = None, None, None
            if overlaps_freetext and freetext_idx is not None:
                ft_annot = annots[freetext_idx]
                ft_r = [float(x) for x in ft_annot['/Rect']]
                ft_rect_f = fitz.Rect(ft_r[0], old_h - ft_r[3], ft_r[2], old_h - ft_r[1])
                
                # Check if this FreeText offset has already been computed
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

            # 1. 優先嘗試文字定位 (適用於文字標註、外框等)
            if overlaps_freetext and ft_dx is not None:
                dx = ft_dx
                dy = ft_dy
                target_new_idx = ft_target_idx
            else:
                if not overlaps_freetext and subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly', '/Square', '/Circle', '/Redact']:
                    text_result = find_text_based_position(p_old_f, p_new_f, old_rect_f, rawdict_cache, words_cache)
                    if not text_result:
                        # 嘗試在鄰近頁面（+1, -1, +2）搜尋
                        for offset in [1, -1, 2]:
                            cand_idx = new_idx + offset
                            if 0 <= cand_idx < len(doc_new):
                                if not sections_match(old_sections[old_idx], new_sections[cand_idx]):
                                    continue
                                res = find_text_based_position(p_old_f, doc_new[cand_idx], old_rect_f, rawdict_cache, words_cache)
                                if res:
                                    text_result = res
                                    target_new_idx = cand_idx
                                    break
                    if text_result:
                        new_quads, new_rect, pdf_rect_old = text_result
                        
                        # Calculate padding in old coordinates
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

                        # Calculate scales for /AP scaling
                        w_old = r[2] - r[0]
                        h_old = r[3] - r[1]
                        w_new = new_rect_annot[2] - new_rect_annot[0]
                        h_new = new_rect_annot[3] - new_rect_annot[1]
                        scale_x = w_new / w_old if w_old > 0 else 1.0
                        scale_y = h_new / h_old if h_old > 0 else 1.0

                # 2. 如果沒有文字定位結果，則走 AI 錨點比對或群組
                status = "未群組"
                if not text_result:
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
                                # 傳入空 array，不使用之前記錄的群組位移，以便純粹評估該頁面的錨點匹配數
                                cand_dx, cand_dy, _, cand_status, cand_match_count = find_precise_offset(p_old_f, cand_p_new, old_rect_f, [], words_cache)
                                if cand_status in ["精準AI", "弱AI"]:
                                    if cand_match_count > best_match_count:
                                        best_match_count = cand_match_count
                                        best_dx = cand_dx
                                        best_dy = cand_dy
                                        best_status = cand_status
                                        best_dx, best_dy = cand_dx, cand_dy
                                        best_target_idx = cand_idx
                        
                        if best_match_count == -1:
                            target_new_idx = new_idx
                            cand_p_new = doc_new[target_new_idx]
                            cand_origin_dx = cand_p_new.rect.x0 - p_old_f.rect.x0
                            cand_origin_dy = cand_p_new.rect.y0 - p_old_f.rect.y0
                            dx = cand_origin_dx + MANUAL_ADJUST_X
                            dy = cand_origin_dy + MANUAL_ADJUST_Y
                            dx = (cand_p_new.rect.x0 - p_old_f.rect.x0)
                            dy = (cand_p_new.rect.y0 - p_old_f.rect.y0)
                        else:
                            target_new_idx = best_target_idx
                            cand_p_new = doc_new[target_new_idx]
                            cand_origin_dx = cand_p_new.rect.x0 - p_old_f.rect.x0
                            cand_origin_dy = cand_p_new.rect.y0 - p_old_f.rect.y0
                            dx = best_dx + cand_origin_dx + MANUAL_ADJUST_X
                            dy = best_dy + cand_origin_dy + MANUAL_ADJUST_Y
                            dx = best_dx + (cand_p_new.rect.x0 - p_old_f.rect.x0)
                            dy = best_dy + (cand_p_new.rect.y0 - p_old_f.rect.y0)

            # 3. 記錄到偏移量地圖中
            is_direct = (text_result is not None) or (status != "群組")
            processed_offsets_map[old_idx].append((old_rect_f, dx, dy, target_new_idx, is_direct))

            # 4. 處理 FreeText 註解的特殊 DA 設定，其餘註解保留並平移 AP
            if subtype == '/FreeText':
                for key in ['/AP', '/RD', '/IT']:
                    if annot.get(key): del annot[key]
                annot.DA = pdfrw.PdfObject("( /Helv 12 Tf 1 0 0 rg )") 
            else:
                pass

            # 5. 更新註解 Rect
            new_rect = [r[0] + dx, r[1] - dy, r[2] + dx, r[3] - dy]
            if text_result:
                new_rect = new_rect_annot
            annot.Rect = pdfrw.PdfArray([pdfrw.PdfObject(f"{x:.4f}") for x in new_rect])

            # 6. 如果不是文字對位（或是有文字對位但保留舊 QuadPoints），更新 QuadPoints、Vertices 與 L 坐標 (L 用於 Line/箭頭)
            if not text_result or subtype not in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly']:
                for key_name in ['QuadPoints', 'Vertices', 'L']:
                    val = annot.get(PN(key_name))
                    if val:
                        pts = [float(x) for x in val]
                        new_pts = [pdfrw.PdfObject(f"{(pts[i]+dx if i%2==0 else pts[i]-dy):.4f}") for i in range(len(pts))]
                        annot[PN(key_name)] = pdfrw.PdfArray(new_pts)

            # 7. 更新 InkList 畫筆跡坐標
            il = annot.get('/InkList')
            if il:
                new_ink = pdfrw.PdfArray()
                for path in il:
                    pts = [float(x) for x in path]
                    new_path = [pdfrw.PdfObject(f"{(pts[i]+dx if i%2==0 else pts[i]-dy):.4f}") for i in range(len(pts))]
                    new_ink.append(pdfrw.PdfArray(new_path))
                annot.InkList = new_ink

            # 8. 將註解寫入目標頁面
            p_target_p = reader_new.pages[target_new_idx]
            # 更新註解對應的頁面引用，避免跨文件引用的懸空指針導致註解無法編輯
            if annot.get('/P'):
                annot.P = p_target_p
            if not p_target_p.Annots:
                p_target_p.Annots = pdfrw.PdfArray()
            p_target_p.Annots.append(annot)

    writer = pdfrw.PdfWriter()
    writer.write(output_pdf, reader_new)
    doc_old.close()
    doc_new.close()

    # 處理書籤：如果在比對階段有發現差異頁碼，則將其加入最終輸出的 PDF 書籤中
    if diff_pages_str:
        try:
            diff_pages = [int(p) for p in str(diff_pages_str).split(",") if p.strip()]
            if diff_pages:
                final_doc = fitz.open(output_pdf)
                toc = final_doc.get_toc()

                # 加入一個主書籤節點，讓差異頁面可以收合
                diff_root_added = False

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
        except Exception as e:
            print(f"添加差異書籤失敗: {e}")