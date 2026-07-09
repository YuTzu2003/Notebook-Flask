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

    # 2. 建立含有前後文 (Context) 的舊版目標字串，解決重複文句的對齊困擾
    context_len = 6
    ctx_start = max(0, start_idx - context_len)
    ctx_end = min(len(old_chars), end_idx + 1 + context_len)
    
    old_pattern_str = "".join([c[4] for c in old_chars[ctx_start:ctx_end]])
    len_prefix = start_idx - ctx_start
    len_core = (end_idx - start_idx) + 1

    # 3. 獲取新頁面字元並拼接成長字串
    new_chars = get_page_chars(page_new)
    if not new_chars:
        return None

    new_str = "".join([c[4] for c in new_chars])
    
    best_match_start = -1
    best_match_end = -1
    best_metric = -9999.0

    # 4. 優先嘗試完整上下文的精準子字串匹配
    exact_idx = new_str.find(old_pattern_str)
    if exact_idx != -1:
        # 新版可能有多處相同的背景字，用距離來判定最接近的項
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
                    
    # 5. 若無法精準匹配（可能新舊版增減了標點或空白），啟動滑動視窗進行模糊比對
    if best_match_start == -1:
        window_size = len(old_pattern_str)
        for start in range(len(new_chars) - window_size + 3):
            for delta in [-2, -1, 0, 1, 2]: # 容忍標點符號的增刪
                end = start + window_size + delta
                if end > len(new_chars) or end <= start:
                    continue
                    
                new_cand_str = new_str[start:end] # 效能優化：使用字串切片取代列表生成式
                score = fuzz.ratio(old_pattern_str, new_cand_str) / 100.0
                
                # 計算距離懲罰，防範段落漂移到遙遠的重複句上
                cand_x0 = new_chars[start][0]
                cand_y0 = new_chars[start][1]
                dist = abs(cand_x0 - old_rect_f.x0) + abs(cand_y0 - old_rect_f.y0)
                metric = score - (dist / 8000.0)
                
                if score > 0.82 and metric > best_metric: # 相似度門檻為 82%
                    best_metric = metric
                    best_match_start = start
                    best_match_end = end

    if best_match_start < 0:
        return None

    # 從新頁面的匹配區間中，等比例切出目標核心文字並處理單字展開
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

    # 將匹配字元依行分組 (小於 6pt 視為同行)
    lines = []
    current_line = [matched[0]]
    for w in matched[1:]:
        if abs(w[1] - current_line[-1][1]) < 6:
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
                    text_result = find_text_based_position(p_old_f, p_new_f, old_rect_f, rawdict_cache, words_cache)
                    if not text_result:
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

            # 註解屬性清理與平移寫入：保留 FreeText 的 /AP 與 /DA 屬性以完整顯示中文字型，其餘定位位移與螢光筆等不受影響
            pass

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