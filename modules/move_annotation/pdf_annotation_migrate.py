import os
import re
import math
import statistics
import logging
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
    dx = (w_rect.x0 + w_rect.x1)/2 - annot_center[0]
    dy = (w_rect.y0 + w_rect.y1)/2 - annot_center[1]
    # 加重垂直距離的懲罰 (x5)，鼓勵尋找同一列的文字作為錨點
    dist = math.sqrt(dx**2 + (dy * 5)**2)
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
def find_precise_offset(page_old, page_new, old_rect, processed_offsets, spans_cache=None,
                        allow_group=True, prefer_context=False):
    # FreeText must be located from its own surrounding document text.  Reusing a
    # nearby annotation's movement is quick, but a note can sit beside a repeated
    # label or a table row and then lands in the wrong place.
    if allow_group:
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
        if spans_cache is not None:
            key = (id(p.parent), p.number)
            if key not in spans_cache:
                spans = []
                raw = p.get_text("dict")
                for block in raw.get("blocks", []):
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            t = span.get("text", "").strip()
                            bbox = span.get("bbox")
                            if any('\u4e00' <= c <= '\u9fff' for c in t):
                                t_clean = "".join(t.split())
                                if len(t_clean) >= 3:
                                    spans.append((bbox[0], bbox[1], bbox[2], bbox[3], t_clean))
                            else:
                                words = t.split()
                                idx = 0
                                for w in words:
                                    start_idx = t.find(w, idx)
                                    end_idx = start_idx + len(w)
                                    idx = end_idx
                                    L = len(t)
                                    W = bbox[2] - bbox[0]
                                    word_x0 = bbox[0] + (start_idx / L) * W if L > 0 else bbox[0]
                                    word_x1 = bbox[0] + (end_idx / L) * W if L > 0 else bbox[2]
                                    w_clean = "".join(w.split())
                                    if len(w_clean) >= 3:
                                        spans.append((word_x0, bbox[1], word_x1, bbox[3], w_clean))
                spans_cache[key] = spans
            return spans_cache[key]
        
        spans = []
        raw = p.get_text("dict")
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    bbox = span.get("bbox")
                    if any('\u4e00' <= c <= '\u9fff' for c in t):
                        t_clean = "".join(t.split())
                        if len(t_clean) >= 3:
                            spans.append((bbox[0], bbox[1], bbox[2], bbox[3], t_clean))
                    else:
                        words = t.split()
                        idx = 0
                        for w in words:
                            start_idx = t.find(w, idx)
                            end_idx = start_idx + len(w)
                            idx = end_idx
                            L = len(t)
                            W = bbox[2] - bbox[0]
                            word_x0 = bbox[0] + (start_idx / L) * W if L > 0 else bbox[0]
                            word_x1 = bbox[0] + (end_idx / L) * W if L > 0 else bbox[2]
                            w_clean = "".join(w.split())
                            if len(w_clean) >= 3:
                                spans.append((word_x0, bbox[1], word_x1, bbox[3], w_clean))
        return spans

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
    # Keep all plausible movements for text notes.  The legacy path chooses the
    # nearest occurrence of each word first; that is unreliable when a table has
    # the same word in several rows.  Clustering all surrounding anchors lets the
    # local sentence/row decide the movement instead.
    context_candidates = []
    new_texts = [nw[4].strip() for nw in words_new]

    # 在新版頁面中搜尋這 12 個錨點
    for anchor_index, cw in enumerate(candidate_anchors):
        text = cw[4].strip()
        if len(text) < 3: continue 
        
        cw_rect_old = fitz.Rect(cw[:4])
        hits = page_new.search_for(text)
        
        # 如果無法精準搜尋，啟動模糊相似度搜尋 (Fuzzy Match)
        if (not hits or len(hits) > 3) and len(text) >= 3:
            clean_text = "".join(text.split())
            clean_new_texts = ["".join(nt.split()) for nt in new_texts]
            matches = []
            for i, nt in enumerate(clean_new_texts):
                score = fuzz.partial_ratio(clean_text, nt)
                if score >= 95:
                    # 避免長字串誤配對到極短字串（例如 "22 TURP—cancer..." 誤配對到 "TURP"）
                    # 剝離標點符號後進行長度比對，只有在新字串比舊字串短時，限制其長度比例不能小於 0.5
                    text_alnum = "".join([c for c in clean_text if c.isalnum()])
                    nt_alnum = "".join([c for c in nt if c.isalnum()])
                    if len(nt_alnum) < len(text_alnum):
                        if len(nt_alnum) / len(text_alnum) < 0.5:
                            continue
                    matches.append((new_texts[i], score, i))
            matches = sorted(matches, key=lambda x: x[1], reverse=True)[:3]
            
            for m_text, score, idx in matches:
                nw_rect = fitz.Rect(words_new[idx][:4])
                # 空間鄰近篩選：只接受垂直距離在頁面高度 90% 以內的匹配，以包容跨頁表格大位移，同時過濾無效頁首頁尾
                if abs(nw_rect.y0 - cw_rect_old.y0) < page_new.rect.height * 0.9:
                    hits.append(nw_rect)

        if hits:
            valid_hits = []
            for hit in hits:
                dx = hit.x0 - cw_rect_old.x0
                dy = hit.y0 - cw_rect_old.y0
                # 水平位移過大（大於頁面寬度 40%）視為異常，垂直位移包容度提升至 90%
                if abs(dx) < page_new.rect.width * 0.4 and abs(dy) < page_new.rect.height * 0.9:
                    valid_hits.append((dx, dy))

            if prefer_context:
                context_candidates.extend((dx, dy, anchor_index) for dx, dy in valid_hits)
            elif valid_hits:
                # 非文字筆記保留原本以幾何距離選取的行為。
                dx, dy = min(
                    valid_hits,
                    key=lambda item: abs(item[1]) + abs(item[0])
                )
                offsets_x.append(dx)
                offsets_y.append(dy)

    if prefer_context and context_candidates:
        # 尋找由最多「不同」周邊文字錨點支持的位移群；同一個重複詞
        # 不會因為出現多次就壓過相鄰句子的共同證據。
        best_cluster = []
        for dx0, dy0, _ in context_candidates:
            cluster = [
                item for item in context_candidates
                if abs(item[0] - dx0) < 18 and abs(item[1] - dy0) < 18
            ]
            cluster_unique = len({item[2] for item in cluster})
            best_unique = len({item[2] for item in best_cluster})
            
            if cluster_unique > best_unique:
                best_cluster = cluster
            elif cluster_unique == best_unique and cluster_unique > 0:
                # 相同錨點數時，優先選擇位移量較小的群組，避免跳躍到錯誤的重複段落
                dx_cluster = statistics.median(item[0] for item in cluster)
                dy_cluster = statistics.median(item[1] for item in cluster)
                dx_best = statistics.median(item[0] for item in best_cluster)
                dy_best = statistics.median(item[1] for item in best_cluster)
                if abs(dx_cluster) + abs(dy_cluster) < abs(dx_best) + abs(dy_best):
                    best_cluster = cluster

        unique_anchor_count = len({item[2] for item in best_cluster})
        if unique_anchor_count:
            dx = statistics.median(item[0] for item in best_cluster)
            dy = statistics.median(item[1] for item in best_cluster)
            status = "精準AI" if unique_anchor_count >= 2 else "弱AI"
            return dx, dy, None, status, unique_anchor_count

    # 空間一致性篩選：剔除偏離中位數大於 15 像素的異常錨點位移
    if len(offsets_x) >= 2:
        med_x = statistics.median(offsets_x)
        med_y = statistics.median(offsets_y)
        consistent_pairs = [(dx, dy) for dx, dy in zip(offsets_x, offsets_y) if abs(dx - med_x) < 15 and abs(dy - med_y) < 15]
        
        if len(consistent_pairs) >= 2:
            cx = [p[0] for p in consistent_pairs]
            cy = [p[1] for p in consistent_pairs]
            return statistics.median(cx), statistics.median(cy), None, "精準AI", len(consistent_pairs)
        elif len(consistent_pairs) == 1:
            return consistent_pairs[0][0], consistent_pairs[0][1], None, "弱AI", 1
            
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

    def local_context(page, rect, radius=16):
        """Return nearby reading-order text for choosing between repeated hits."""
        words = page.get_text("words", sort=True)
        if not words:
            return ""
        touched = [
            index for index, word in enumerate(words)
            if rect.intersects(fitz.Rect(word[:4]))
        ]
        if not touched:
            return ""
        start = max(0, min(touched) - radius)
        end = min(len(words), max(touched) + radius + 1)
        return "".join("".join(word[4].split()) for word in words[start:end])

    def row_context(page, rect):
        """Return the text in the table row(s) occupied by an annotation."""
        vertical_padding = max(10, rect.height * 0.35)
        row_words = [
            word for word in page.get_text("words")
            if word[3] >= rect.y0 - vertical_padding and word[1] <= rect.y1 + vertical_padding
        ]
        row_words.sort(key=lambda word: (round(word[1] / 8), word[0]))
        return "".join("".join(word[4].split()) for word in row_words)

    def hit_context_score(source_local, source_row, hit):
        target_local = local_context(page_new, hit)
        target_row = row_context(page_new, hit)
        # In tables, the row signature includes the left-side code.  It is much
        # stronger evidence than a repeated phrase in the definition column.
        return (
            fuzz.ratio(source_row, target_row) * 0.7 +
            fuzz.ratio(source_local, target_local) * 0.2 +
            fuzz.partial_ratio(source_local, target_local) * 0.1
        )

    def result_from_direct_hit(hit, exact_chars=None):
        new_h = page_new.rect.height
        old_h = page_old.rect.height
        old_covered = [old_chars[index] for index in covered_indices]
        old_rect = fitz.Rect(
            min(char[0] for char in old_covered), min(char[1] for char in old_covered),
            max(char[2] for char in old_covered), max(char[3] for char in old_covered)
        )

        # A direct text match may cover several source QuadPoints.  Do not turn
        # them into one large rectangle: derive individual target fragments from
        # the target page's characters so gaps between separately highlighted
        # lines (or columns) remain unhighlighted.
        # For compact-text matches we already know the exact characters that
        # formed the hit.  Using every character inside the hit's bounding box
        # is wrong when a match wraps across rows: the bounding box also covers
        # unrelated text between the two ends of the selection.
        if exact_chars is not None:
            matched_chars = list(exact_chars)
        else:
            matched_chars = []
            for char in new_chars:
                char_rect = fitz.Rect(char[:4])
                if hit.intersects(char_rect):
                    overlap = hit & char_rect
                    if overlap.get_area() / max(char_rect.get_area(), 1) > .3:
                        matched_chars.append(char)

        fragments = []
        if matched_chars:
            matched_chars.sort(key=lambda char: (char[1], char[0]))
            current = [matched_chars[0]]
            for char in matched_chars[1:]:
                previous = current[-1]
                same_line = abs(char[1] - previous[1]) <= 6
                close_enough = char[0] - previous[2] <= max(12, previous[3] - previous[1])
                if same_line and close_enough:
                    current.append(char)
                else:
                    fragments.append(current)
                    current = [char]
            fragments.append(current)
        else:
            fragments = [[(hit.x0, hit.y0, hit.x1, hit.y1, "")]]

        target_rects = [
            fitz.Rect(
                min(char[0] for char in fragment), min(char[1] for char in fragment),
                max(char[2] for char in fragment), max(char[3] for char in fragment)
            )
            for fragment in fragments
        ]
        quads = []
        for rect in target_rects:
            quads.extend([
                rect.x0, new_h - rect.y0,
                rect.x1, new_h - rect.y0,
                rect.x0, new_h - rect.y1,
                rect.x1, new_h - rect.y1,
            ])
        union_rect = target_rects[0]
        for rect in target_rects[1:]:
            union_rect |= rect
        return (
            quads,
            [union_rect.x0, new_h - union_rect.y1, union_rect.x1, new_h - union_rect.y0],
            [old_rect.x0, old_h - old_rect.y1, old_rect.x1, old_h - old_rect.y0]
        )

    def group_direct_hits(hits):
        """Merge adjacent search rectangles that belong to one text occurrence.

        PyMuPDF may return a separate rectangle for each text span even when a
        searched phrase appears only once.  Treating those spans as separate
        occurrences makes the migration fall back to page-level alignment and
        can send a highlight to a later repeated phrase on the same page.
        """
        groups = []
        for hit in sorted(hits, key=lambda rect: (rect.y0, rect.x0)):
            if groups:
                previous = groups[-1]
                same_line = abs(hit.y0 - previous.y0) <= 8 and abs(hit.y1 - previous.y1) <= 8
                adjacent = hit.x0 <= previous.x1 + 30
                if same_line and adjacent:
                    # Rect's in-place union returns a new object in some
                    # PyMuPDF versions, so update the list entry directly.
                    groups[-1] |= hit
                    continue
            groups.append(fitz.Rect(hit))
        return groups

    # First search with the exact characters covered by QuadPoints.  Annotation
    # rectangles commonly include neighbouring characters, so clipping by the
    # rectangle can turn "首次治療前 3 個月內" into "案首次治療前 3 個月內所".
    # Raw characters let us preserve the actual highlighted range while still
    # matching PDFs that differ only in whitespace.
    compact_covered = "".join(old_chars[index][4] for index in covered_indices)
    new_chars = get_page_chars(page_new)
    compact_new = "".join(char[4] for char in new_chars)
    direct_matches = []
    if len(compact_covered) >= 2 and compact_new:
        search_start = 0
        while True:
            found_at = compact_new.find(compact_covered, search_start)
            if found_at < 0:
                break
            matched_chars = new_chars[found_at:found_at + len(compact_covered)]
            direct_matches.append((fitz.Rect(
                min(char[0] for char in matched_chars),
                min(char[1] for char in matched_chars),
                max(char[2] for char in matched_chars),
                max(char[3] for char in matched_chars)
            ), matched_chars))
            search_start = found_at + 1

    if len(direct_matches) == 1:
        hit, exact_chars = direct_matches[0]
        return result_from_direct_hit(hit, exact_chars)
    if len(direct_matches) > 1:
        # Select repeated exact matches using the same surrounding-context
        # evidence as literal searches, but keep the exact matched characters.
        source_context = local_context(page_old, old_rect_f)
        source_row = row_context(page_old, old_rect_f)
        source_x = (old_rect_f.x0 + old_rect_f.x1) / 2 / max(page_old.rect.width, 1)
        source_y = (old_rect_f.y0 + old_rect_f.y1) / 2 / max(page_old.rect.height, 1)
        scored_matches = []
        for hit, exact_chars in direct_matches:
            context_score = hit_context_score(source_context, source_row, hit)
            hit_x = (hit.x0 + hit.x1) / 2 / max(page_new.rect.width, 1)
            hit_y = (hit.y0 + hit.y1) / 2 / max(page_new.rect.height, 1)
            score = context_score - 45 * abs(hit_y - source_y) - 12 * abs(hit_x - source_x)
            scored_matches.append((score, context_score, hit, exact_chars))
        scored_matches.sort(key=lambda item: item[0], reverse=True)
        if scored_matches and scored_matches[0][1] >= 60:
            _, _, hit, exact_chars = scored_matches[0]
            return result_from_direct_hit(hit, exact_chars)

    # Fall back to literal PDF search when the exact marked characters changed.
    # Preserve spaces here: the upper occurrence may contain spaces whereas a
    # lower repeated occurrence does not.
    covered_text = page_old.get_text("text", clip=old_rect_f).strip()
    if not covered_text:
        covered_text = compact_covered
    direct_hits = []
    if len("".join(covered_text.split())) >= 2:
        try:
            direct_hits = page_new.search_for(covered_text)
        except Exception:
            direct_hits = []
        direct_hits = group_direct_hits(direct_hits)
    if len(direct_hits) == 1:
        return result_from_direct_hit(direct_hits[0])
    if len(direct_hits) > 1:
        # Repeated phrases such as "後續追蹤或治療" must not be chosen by
        # vertical position alone.  Compare the surrounding sentence/table row
        # and use the hit with clearly stronger local context.
        source_context = local_context(page_old, old_rect_f)
        source_row = row_context(page_old, old_rect_f)
        source_x = (old_rect_f.x0 + old_rect_f.x1) / 2 / max(page_old.rect.width, 1)
        source_y = (old_rect_f.y0 + old_rect_f.y1) / 2 / max(page_old.rect.height, 1)
        scored_hits = []
        for hit in direct_hits:
            context_score = hit_context_score(source_context, source_row, hit)
            hit_x = (hit.x0 + hit.x1) / 2 / max(page_new.rect.width, 1)
            hit_y = (hit.y0 + hit.y1) / 2 / max(page_new.rect.height, 1)
            # Context identifies the row; normalized coordinates resolve a tie
            # when the same wording appears in otherwise similar rows.
            position_penalty = 45 * abs(hit_y - source_y) + 12 * abs(hit_x - source_x)
            scored_hits.append((context_score - position_penalty, context_score, hit))

        scored_hits.sort(key=lambda item: item[0], reverse=True)
        if scored_hits and scored_hits[0][1] >= 60:
            return result_from_direct_hit(scored_hits[0][2])

    # A revised manual can slightly change a marked expression (for example,
    # "緩和治療" to "緩和性手術").  If the full phrase disappeared, search its
    # longest surviving fragments and accept one only when the surrounding row
    # strongly agrees with the old annotation's context.
    normalized_covered = "".join(covered_text.split())
    # Limit this fallback to genuinely short changed labels.  Enumerating every
    # substring of a long highlighted sentence causes a prohibitive number of PDF
    # searches on large manuals.
    if not direct_hits and 4 <= len(normalized_covered) <= 12:
        source_context = local_context(page_old, old_rect_f)
        source_row = row_context(page_old, old_rect_f)
        fragment_hits = []
        seen_fragments = set()
        minimum_length = max(2, len(normalized_covered) - 3)
        for length in range(len(normalized_covered) - 1, minimum_length - 1, -1):
            for start in range(0, len(normalized_covered) - length + 1):
                fragment = normalized_covered[start:start + length]
                if fragment in seen_fragments:
                    continue
                seen_fragments.add(fragment)
                for hit in page_new.search_for(fragment):
                    score = hit_context_score(source_context, source_row, hit)
                    fragment_hits.append((score, len(fragment), hit))
        if fragment_hits:
            fragment_hits.sort(key=lambda item: (item[0], item[1]), reverse=True)
            best_score, _, best_hit = fragment_hits[0]
            if best_score >= 65:
                return result_from_direct_hit(best_hit)

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

    covered_norm_indices = [i for i, x in enumerate(old_index_map) if x in covered_indices]
    mapped_norm_indices = []

    # A highlight often covers only a short word (for example, a status code in a
    # table).  That word may occur many times on the new page.  First locate it
    # through a unique surrounding text window, then keep only the characters at
    # the original offset inside that window.  This is more reliable than a
    # full-page alignment for repeated words.
    if covered_norm_indices:
        window_start = max(0, min(covered_norm_indices) - 24)
        window_end = min(len(old_norm_str), max(covered_norm_indices) + 25)
        context = old_norm_str[window_start:window_end]
        if len(context) >= 8:
            occurrences = []
            search_start = 0
            while True:
                found_at = new_norm_str.find(context, search_start)
                if found_at < 0:
                    break
                occurrences.append(found_at)
                search_start = found_at + 1
            if len(occurrences) == 1:
                target_start = occurrences[0]
                mapped_norm_indices = [
                    target_start + (index - window_start)
                    for index in covered_norm_indices
                ]

    if not mapped_norm_indices:
        import difflib
        matcher = difflib.SequenceMatcher(None, old_norm_str, new_norm_str, autojunk=False)
        matching_blocks = matcher.get_matching_blocks()
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
    spans_cache = {}

    def find_same_row_reference(note_rect, processed_offsets):
        """Return a direct annotation movement from the same visual row.

        A typed note is often placed to the right of a highlighted code or phrase.
        The rectangles do not overlap horizontally, so ordinary intersection and
        nearby-group checks miss this relationship.
        """
        candidates = []
        for entry in processed_offsets:
            if len(entry) != 5:
                continue
            reference_rect, dx, dy, target_idx, is_direct = entry
            if not is_direct:
                continue
            vertical_gap = max(
                reference_rect.y0 - note_rect.y1,
                note_rect.y0 - reference_rect.y1,
                0
            )
            if vertical_gap > 14:
                continue
            center_gap = abs(
                (reference_rect.y0 + reference_rect.y1) / 2 -
                (note_rect.y0 + note_rect.y1) / 2
            )
            horizontal_gap = max(
                reference_rect.x0 - note_rect.x1,
                note_rect.x0 - reference_rect.x1,
                0
            )
            candidates.append((vertical_gap * 100 + center_gap * 10 + horizontal_gap * 0.01,
                               dx, dy, target_idx))
        if not candidates:
            return None
        _, dx, dy, target_idx = min(candidates, key=lambda item: item[0])
        return dx, dy, target_idx

    def find_code_row_anchor(old_page, note_rect, mapped_new_idx, old_section):
        """Move a typed side note with the nearest table-code row.

        FreeText outside a frame has no reliable text in the PDF content stream.
        In manuals it is commonly written beside a 3-digit table code, so that
        row is a stronger anchor than another annotation elsewhere on the page.
        """
        candidates = []
        # A table code is a reliable anchor only when it is genuinely on the
        # note's row.  A code one or two rows away can incorrectly pull a
        # paragraph-style typed note to a different location on the page.
        max_gap = 10
        for word in old_page.get_text("words", sort=True):
            code_rect = fitz.Rect(word[:4])
            codes = re.findall(r"(?<!\d)\d{3}(?!\d)", word[4])
            # A number is a row anchor only when it is in the document's left
            # code column.  Numbers embedded in paragraph text must not move a
            # nearby typed note.
            if (not codes or code_rect.x1 > note_rect.x0 + 20 or
                    code_rect.x0 > old_page.rect.width * .30):
                continue
            vertical_gap = max(code_rect.y0 - note_rect.y1, note_rect.y0 - code_rect.y1, 0)
            if vertical_gap > max_gap:
                continue
            center_gap = abs(
                (code_rect.y0 + code_rect.y1) / 2 -
                (note_rect.y0 + note_rect.y1) / 2
            )
            candidates.append((vertical_gap * 100 + center_gap, codes[0], code_rect))
        if not candidates:
            return None
        _, code, source_rect = min(candidates, key=lambda item: item[0])

        target_candidates = []
        # A typed note has no text of its own to prove that it belongs on an
        # adjacent page.  Prefer the CSV-mapped page's code row; matching the
        # same three-digit code on a neighbour is a common false positive.
        for offset in [0]:
            target_idx = mapped_new_idx + offset
            if not (0 <= target_idx < len(doc_new)):
                continue
            if not sections_match(old_section, new_sections[target_idx]):
                continue
            target_page = doc_new[target_idx]
            expected_x = source_rect.x0 / max(old_page.rect.width, 1) * target_page.rect.width
            hits = [
                hit for hit in target_page.search_for(code)
                if abs(hit.x0 - expected_x) < target_page.rect.width * .12
            ]
            if hits:
                expected_y = source_rect.y0 / max(old_page.rect.height, 1) * target_page.rect.height
                best_hit = min(hits, key=lambda h: abs(h.y0 - expected_y))
                target_candidates.append((abs(offset), abs(best_hit.y0 - expected_y), target_idx, best_hit))
        if not target_candidates:
            return None
        _, _, target_idx, target_rect = min(target_candidates, key=lambda item: (item[0], item[1]))
        dx = target_rect.x0 - source_rect.x0
        dy = ((target_rect.y0 + target_rect.y1) -
              (source_rect.y0 + source_rect.y1)) / 2
        return dx, dy, target_idx

    def annotation_context(page, annotation_rect, radius=4):
        """Build a small, local text fingerprint around an annotation."""
        words = page.get_text("words", sort=True)
        if not words:
            return ""
        touched = [
            index for index, word in enumerate(words)
            if annotation_rect.intersects(fitz.Rect(word[:4]))
        ]
        if not touched:
            center = ((annotation_rect.x0 + annotation_rect.x1) / 2,
                      (annotation_rect.y0 + annotation_rect.y1) / 2)
            touched = [min(
                range(len(words)),
                key=lambda index: (
                    (words[index][0] + words[index][2]) / 2 - center[0]
                ) ** 2 + ((words[index][1] + words[index][3]) / 2 - center[1]) ** 2
            )]
        start = max(0, min(touched) - radius)
        end = min(len(words), max(touched) + radius + 1)
        return "".join("".join(word[4].split()) for word in words[start:end])

    def context_score(old_page, old_rect, new_page):
        """Score a candidate page by the annotation's surrounding sentence/row."""
        context = annotation_context(old_page, old_rect)
        if len(context) < 6:
            return 0
        candidate = "".join(new_page.get_text("text").split())
        occurrences = candidate.count(context)
        if occurrences == 1:
            return 1000 + len(context)
        # Text can change slightly across versions; retain a soft signal when an
        # exact context is unavailable, without allowing a repeated short word to
        # dominate the decision.
        return fuzz.partial_ratio(context, candidate)

    def find_best_text_match(old_page, mapped_new_idx, old_rect, old_quadpoints, old_section,
                             allow_neighbors):
        """Find an annotation's text on the mapped page or its nearby spill-over pages.

        A document revision can move the content of one old page across several new
        pages.  Do not stop at the CSV's page mapping just because it contains a
        plausible match: compare every nearby candidate and prefer the strongest
        text match.  The CSV mapping remains the tie-breaker, so repeated labels
        do not needlessly jump to another page.
        """
        source_text = old_page.get_text("text", clip=old_rect).strip().replace("\n", "")
        source_text = "".join(c for c in source_text if c.strip() and c not in ['\uf09f', '\u2022'])

        # The CSV page mapping is normally the correct page.  In a page where
        # several notes already land correctly, letting one annotation compare
        # every neighbouring page can make a repeated phrase look marginally
        # better on the next page and move only that note away from its peers.
        # Therefore a real text position on the mapped page wins immediately;
        # neighbouring pages are a fallback only when the text is absent there.
        if 0 <= mapped_new_idx < len(doc_new) and sections_match(
            old_section, new_sections[mapped_new_idx]
        ):
            primary_result = find_text_based_position(
                old_page, doc_new[mapped_new_idx], old_rect,
                rawdict_cache, words_cache, old_quadpoints
            )
            if primary_result:
                return primary_result, mapped_new_idx

        best_result, best_idx, best_score = None, None, float("-inf")
        offsets = [-1, 1, -2, 2, -3, 3] if allow_neighbors else []
        for offset in offsets:
            candidate_idx = mapped_new_idx + offset
            if not (0 <= candidate_idx < len(doc_new)):
                continue
            if not sections_match(old_section, new_sections[candidate_idx]):
                continue

            result = find_text_based_position(
                old_page, doc_new[candidate_idx], old_rect,
                rawdict_cache, words_cache, old_quadpoints
            )
            if not result:
                continue

            candidate_text = "".join(doc_new[candidate_idx].get_text("text").split())
            # Local context has much more weight than the short highlighted word.
            # It lets an old page's overflow content correctly choose the preceding
            # or following new page when a revision changes pagination.
            score = (
                context_score(old_page, old_rect, doc_new[candidate_idx]) * 10 +
                fuzz.partial_ratio(source_text, candidate_text) - abs(offset) * 1.5
            )
            if score > best_score:
                best_result, best_idx, best_score = result, candidate_idx, score

        return best_result, best_idx

    def split_multi_item_square(old_page, old_rect, mapped_new_idx, old_section):
        """Map a multi-row rectangular annotation into one rectangle per new page."""
        # Do not apply this specialised flow to ordinary small boxes or thin
        # line-like rectangles.  Those are single annotations and must retain the
        # existing transfer behaviour.
        if old_rect.width < 200 or old_rect.height < 100:
            return []
        source_items = []
        seen = set()
        for word in old_page.get_text("words", sort=True):
            word_rect = fitz.Rect(word[:4])
            if not old_rect.intersects(word_rect):
                continue
            # Item identifiers live in the left code column.  Numbers in the
            # explanatory text (for example, 100-107) are not separate items.
            if word_rect.x0 > old_rect.x0 + old_rect.width * 0.3:
                continue
            for code in re.findall(r"(?<!\d)\d{3}(?!\d)", word[4]):
                key = (code, round(word_rect.y0, 1))
                if key not in seen:
                    source_items.append({"code": code, "rect": word_rect})
                    seen.add(key)
        # Narrative examples can still be inside the wide frame.  The genuine
        # item IDs share one narrow, left-most code column.
        if source_items:
            code_column_x = min(item["rect"].x0 for item in source_items)
            source_items = [
                item for item in source_items
                if abs(item["rect"].x0 - code_column_x) <= 12
            ]
        source_items.sort(key=lambda item: (item["rect"].y0, item["rect"].x0))
        if len(source_items) < 4:
            return []

        mapped_items = []
        for source_index, item in enumerate(source_items):
            candidates = []
            for offset in [0, -1, 1, -2, 2, -3, 3]:
                candidate_idx = mapped_new_idx + offset
                if not (0 <= candidate_idx < len(doc_new)):
                    continue
                if not sections_match(old_section, new_sections[candidate_idx]):
                    continue
                expected_x = item["rect"].x0 / max(old_page.rect.width, 1) * doc_new[candidate_idx].rect.width
                hits = [
                    hit for hit in doc_new[candidate_idx].search_for(item["code"])
                    if abs(hit.x0 - expected_x) < doc_new[candidate_idx].rect.width * 0.12
                ]
                if hits:
                    expected_y = item["rect"].y0 / max(old_page.rect.height, 1) * doc_new[candidate_idx].rect.height
                    best_hit = min(hits, key=lambda h: abs(h.y0 - expected_y))
                    candidates.append((candidate_idx, abs(best_hit.y0 - expected_y), best_hit))
            if candidates:
                candidates.sort(key=lambda candidate: (abs(candidate[0] - mapped_new_idx), candidate[1]))
                target_idx, _, target_rect = candidates[0]
                mapped_items.append({
                    **item, "source_index": source_index,
                    "target_idx": target_idx, "target_rect": target_rect
                })

        # A wide frame can also contain numbers from explanatory text.  Keep only
        # the consecutive code-column rows that can actually be located nearby in
        # the new document.  This is more reliable than abandoning the whole
        # split because a non-item number has no match.
        if len(mapped_items) < 4:
            return []

        target_sequence = [item["target_idx"] for item in mapped_items]
        # A real pagination split progresses monotonically through the new PDF.
        # Alternating target pages means a repeated code was ambiguous, so it is
        # safer to keep the original single-box behaviour than draw overlaps.
        if any(current < previous for previous, current in zip(target_sequence, target_sequence[1:])):
            return []

        groups = []
        for item in mapped_items:
            if not groups or groups[-1][0]["target_idx"] != item["target_idx"]:
                groups.append([item])
            else:
                groups[-1].append(item)

        # Split only when this is confidently a cross-page multi-item box.  This
        # prevents extra boxes and apparent bold borders on ordinary annotations.
        if len(groups) < 2 or len(groups) > 3 or any(len(group) < 2 for group in groups):
            return []

        rectangles = []
        for group_index, group in enumerate(groups):
            target_idx = group[0]["target_idx"]
            target_page = doc_new[target_idx]
            source_first = group[0]
            source_last = group[-1]
            first_index = source_first["source_index"]
            last_index = source_last["source_index"]

            # Preserve the original horizontal span, adjusted by the code-column
            # shift.  Vertically, expand to the next item boundary so each new
            # rectangle contains the complete table rows on that page.
            x_shift = statistics.median(
                item["target_rect"].x0 - item["rect"].x0 for item in group
            )
            x0 = max(0, old_rect.x0 + x_shift)
            x1 = min(target_page.rect.width, old_rect.x1 + x_shift)
            top_pad = (source_first["rect"].y0 - old_rect.y0 if first_index == 0
                       else min(12, (source_first["rect"].y0 - source_items[first_index - 1]["rect"].y1) / 2))
            y0 = max(0, min(item["target_rect"].y0 for item in group) - top_pad)

            next_group_item = (groups[group_index + 1][0]
                               if group_index + 1 < len(groups) else None)
            # Do not extend a split frame to the page bottom: after a page break
            # that produced a visually oversized box.  Use one half-row below
            # the final code, capped by the source frame's original bottom pad.
            row_gaps = [
                source_items[index + 1]["rect"].y0 - source_items[index]["rect"].y1
                for index in range(first_index, min(last_index + 1, len(source_items) - 1))
                if source_items[index + 1]["rect"].y0 > source_items[index]["rect"].y1
            ]
            half_row = statistics.median(row_gaps) / 2 if row_gaps else 18
            bottom_pad = min(max(10, half_row), max(10, old_rect.y1 - source_last["rect"].y1))
            y1 = min(target_page.rect.height, max(item["target_rect"].y1 for item in group) + bottom_pad)
            rectangles.append((target_idx, fitz.Rect(x0, y0, x1, y1)))
        return rectangles

    def split_code_column_line(old_page, old_rect, mapped_new_idx, old_section):
        """Split a vertical line by the code rows it marks across page breaks."""
        if old_rect.height < 60 or old_rect.width > 20:
            return []
        line_x = (old_rect.x0 + old_rect.x1) / 2
        source_items = []
        for word in old_page.get_text("words", sort=True):
            word_rect = fitz.Rect(word[:4])
            # Do not pull the first code of the next table section into the
            # line merely because its glyph slightly touches the line's Rect.
            if word_rect.y1 < old_rect.y0 - 2 or word_rect.y0 > old_rect.y1 + 2:
                continue
            # The line is drawn through / immediately beside the three-digit
            # code, so ignore narrative text further away on the same row.
            if not (word_rect.x0 - 12 <= line_x <= word_rect.x1 + 12):
                continue
            for code in re.findall(r"(?<!\d)\d{3}(?!\d)", word[4]):
                source_items.append({"code": code, "rect": word_rect})
        if source_items:
            code_column_x = min(item["rect"].x0 for item in source_items)
            source_items = [
                item for item in source_items
                if abs(item["rect"].x0 - code_column_x) <= 12
            ]
            # A vertical separator normally marks one code family (for example
            # 500-532).  Do not let the next 6xx section lengthen that same
            # separator merely because it happens to be in the nearby column.
            prefix_counts = {}
            for item in source_items:
                prefix_counts[item["code"][0]] = prefix_counts.get(item["code"][0], 0) + 1
            dominant_prefix, dominant_count = max(prefix_counts.items(), key=lambda item: item[1])
            if dominant_count >= 3:
                source_items = [
                    item for item in source_items
                    if item["code"].startswith(dominant_prefix)
                ]
        if len(source_items) < 3:
            return []

        mapped_items = []
        for item in source_items:
            candidates = []
            for offset in [0, -1, 1, -2, 2, -3, 3]:
                target_idx = mapped_new_idx + offset
                if not (0 <= target_idx < len(doc_new)):
                    continue
                if not sections_match(old_section, new_sections[target_idx]):
                    continue
                expected_x = (item["rect"].x0 / max(old_page.rect.width, 1) *
                              doc_new[target_idx].rect.width)
                hits = [
                    hit for hit in doc_new[target_idx].search_for(item["code"])
                    if abs(hit.x0 - expected_x) < doc_new[target_idx].rect.width * .12
                ]
                if hits:
                    expected_y = item["rect"].y0 / max(old_page.rect.height, 1) * doc_new[target_idx].rect.height
                    best_hit = min(hits, key=lambda h: abs(h.y0 - expected_y))
                    candidates.append((target_idx, abs(best_hit.y0 - expected_y), best_hit))
            if not candidates:
                continue
            candidates.sort(key=lambda candidate: (abs(candidate[0] - mapped_new_idx), candidate[1]))
            target_idx, _, target_rect = candidates[0]
            mapped_items.append({**item, "target_idx": target_idx, "target_rect": target_rect})
        if len(mapped_items) < 3:
            return []

        groups = []
        for item in mapped_items:
            if not groups or groups[-1][0]["target_idx"] != item["target_idx"]:
                groups.append([item])
            else:
                groups[-1].append(item)
        # A line may stay on one page after reflow.  It still benefits from being
        # rebuilt from its marked code rows instead of receiving a page-level
        # translation.  Split only when the rows genuinely land on more pages.
        if len(groups) > 3 or any(len(group) < 2 for group in groups):
            return []

        lines = []
        for group in groups:
            target_idx = group[0]["target_idx"]
            target_page = doc_new[target_idx]
            # Preserve the line's position inside the code (for example, to the
            # right of the leading "5"), not merely its absolute page x value.
            x_offsets = [line_x - item["rect"].x0 for item in group]
            x = statistics.median(item["target_rect"].x0 for item in group) + statistics.median(x_offsets)
            y0 = min(item["target_rect"].y0 for item in group) - 4
            y1 = max(item["target_rect"].y1 for item in group) + 4
            lines.append((target_idx, fitz.Point(x, max(0, y0)),
                          fitz.Point(x, min(target_page.rect.height, y1))))
        return lines

    def align_vertical_line_by_nearby_codes(old_page, old_rect, mapped_new_idx, old_section):
        """Rebuild a vertical line from nearby table codes.

        This conservative fallback is used when the stricter split logic cannot
        classify a mixed code family.  Each destination page needs at least two
        matching code rows, so an unanchored line is never moved merely because
        one repeated number happens to exist on another page.
        """
        if old_rect.height < 60 or old_rect.width > 20:
            return []

        line_x = (old_rect.x0 + old_rect.x1) / 2
        source_items = []
        for word in old_page.get_text("words", sort=True):
            word_rect = fitz.Rect(word[:4])
            if word_rect.y1 < old_rect.y0 - 2 or word_rect.y0 > old_rect.y1 + 2:
                continue
            if not (word_rect.x0 - 12 <= line_x <= word_rect.x1 + 12):
                continue
            for code in re.findall(r"(?<!\d)\d{3}(?!\d)", word[4]):
                source_items.append((code, word_rect))

        mapped_by_page = {}
        for code, source_rect in source_items:
            candidates = []
            for offset in [0, -1, 1, -2, 2, -3, 3]:
                target_idx = mapped_new_idx + offset
                if not (0 <= target_idx < len(doc_new)):
                    continue
                if not sections_match(old_section, new_sections[target_idx]):
                    continue
                target_page = doc_new[target_idx]
                expected_x = source_rect.x0 / max(old_page.rect.width, 1) * target_page.rect.width
                hits = [
                    hit for hit in target_page.search_for(code)
                    if abs(hit.x0 - expected_x) < target_page.rect.width * .12
                ]
                if hits:
                    hit = min(hits, key=lambda candidate: abs(candidate.x0 - expected_x))
                    candidates.append((abs(offset), target_idx, hit))
            if candidates:
                _, target_idx, hit = min(candidates, key=lambda item: item[0])
                mapped_by_page.setdefault(target_idx, []).append((source_rect, hit))

        lines = []
        for target_idx, pairs in mapped_by_page.items():
            if len(pairs) < 2:
                continue
            target_page = doc_new[target_idx]
            x_offsets = [line_x - source_rect.x0 for source_rect, _ in pairs]
            x = statistics.median(hit.x0 for _, hit in pairs) + statistics.median(x_offsets)
            y0 = max(0, min(hit.y0 for _, hit in pairs) - 4)
            y1 = min(target_page.rect.height, max(hit.y1 for _, hit in pairs) + 4)
            lines.append((target_idx, fitz.Point(x, y0), fitz.Point(x, y1)))
        return sorted(lines, key=lambda item: item[0])

    def align_horizontal_line(old_page, old_rect, mapped_new_idx, old_section):
        """Place a horizontal divider from the text rows immediately around it."""
        if old_rect.width < 120 or old_rect.height > 20:
            return None
        line_y = (old_rect.y0 + old_rect.y1) / 2
        anchors = []
        for word in old_page.get_text("words", sort=True):
            word_rect = fitz.Rect(word[:4])
            if abs((word_rect.y0 + word_rect.y1) / 2 - line_y) > 26:
                continue
            text = "".join(word[4].split())
            if len(text) < 2 or len(text) > 20:
                continue
            anchors.append((text, word_rect))
        if not anchors:
            return None

        page_votes = {}
        page_offsets = {}
        for offset in [0, -1, 1, -2, 2, -3, 3]:
            target_idx = mapped_new_idx + offset
            if not (0 <= target_idx < len(doc_new)):
                continue
            if not sections_match(old_section, new_sections[target_idx]):
                continue
            target_page = doc_new[target_idx]
            offsets = []
            for text, source_rect in anchors:
                hits = target_page.search_for(text)
                if not hits:
                    continue
                # A divider usually spans a whole table; choose the occurrence
                # preserving the anchor's horizontal column.
                expected_x = source_rect.x0 / max(old_page.rect.width, 1) * target_page.rect.width
                hit = min(hits, key=lambda candidate: abs(candidate.x0 - expected_x))
                if abs(hit.x0 - expected_x) > target_page.rect.width * .18:
                    continue
                offsets.append((hit.y0 + hit.y1 - source_rect.y0 - source_rect.y1) / 2)
            if offsets:
                page_votes[target_idx] = len(offsets)
                page_offsets[target_idx] = offsets
        if not page_votes:
            return None

        target_idx = max(
            page_votes,
            key=lambda index: (page_votes[index], -abs(index - mapped_new_idx))
        )
        # One matched label is too weak for a broad divider and risks snapping it
        # to an unrelated repeated phrase.
        if page_votes[target_idx] < 2:
            return None
        target_page = doc_new[target_idx]
        dy = statistics.median(page_offsets[target_idx])
        y = min(max(0, line_y + dy), target_page.rect.height)
        return (
            target_idx,
            fitz.Point(old_rect.x0 / old_page.rect.width * target_page.rect.width, y),
            fitz.Point(old_rect.x1 / old_page.rect.width * target_page.rect.width, y)
        )

    for old_idx, new_idx in mapping.items():
        if old_idx >= len(doc_old) or new_idx >= len(doc_new): continue
        p_old_f, p_new_f = doc_old[old_idx], doc_new[new_idx]
        p_new_p = reader_new.pages[new_idx]

        annots = reader_old.pages[old_idx].Annots
        if not annots: continue
        # CSV provides the starting page; the annotation's local context chooses
        # among that page and nearby overflow pages.
        allow_neighbors = True

        # 第一階段：預掃描本頁的所有文字型筆記，搜集投票錨點
        voting_anchors = [] # 儲存格式：(matched_idx, y_center, weight)
        old_h = p_old_f.rect.height
        for annot in annots:
            if not annot.get('/Rect'): continue
            subtype = annot.get('/Subtype')
            if subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly', '/Square', '/Circle', '/Redact', '/Text']:
                r = [float(x) for x in annot['/Rect']]
                old_rect_f = fitz.Rect(r[0], old_h - r[3], r[2], old_h - r[1])
                y_center = (old_rect_f.y0 + old_rect_f.y1) / 2

                # 取得文字長度，忽略短字以防噪訊影響投票
                annot_text = p_old_f.get_text("text", clip=old_rect_f).strip().replace('\n', '')
                annot_text_clean = "".join([c for c in annot_text if c.strip() and c not in ['\uf09f', '\u2022']])
                weight = len(annot_text_clean)
                if weight < 6:
                    continue # 忽略小於 6 字的短標記參與投票
                
                old_quadpoints = annot.get(PN('QuadPoints'))
                text_result, matched_idx = find_best_text_match(
                    p_old_f, new_idx, old_rect_f, old_quadpoints, old_sections[old_idx],
                    allow_neighbors
                )
                if text_result:
                    voting_anchors.append((matched_idx, y_center, weight))

        # A CSV match can be one page off around a revision's page break.  Let
        # several independently matched annotations correct that *page-level*
        # choice, rather than allowing each annotation to jump separately.  A
        # single match is deliberately not enough to override the CSV.
        consensus_new_idx = new_idx
        if voting_anchors:
            vote_weight = {}
            vote_count = {}
            for matched_idx, _, weight in voting_anchors:
                vote_weight[matched_idx] = vote_weight.get(matched_idx, 0) + weight
                vote_count[matched_idx] = vote_count.get(matched_idx, 0) + 1
            best_vote_idx = max(
                vote_weight,
                key=lambda idx: (vote_weight[idx], vote_count[idx], -abs(idx - new_idx))
            )
            mapped_weight = vote_weight.get(new_idx, 0)
            if (best_vote_idx != new_idx and vote_count[best_vote_idx] >= 2 and
                    vote_weight[best_vote_idx] > mapped_weight * 1.15):
                consensus_new_idx = best_vote_idx
        if not p_new_p.Annots: p_new_p.Annots = pdfrw.PdfArray()
        if old_idx not in processed_offsets_map: processed_offsets_map[old_idx] = []
        for annot in annots:
            if not annot.get('/Rect'): continue
            subtype = annot.get('/Subtype')
            r = [float(x) for x in annot['/Rect']]
            old_h = p_old_f.rect.height
            old_rect_f = fitz.Rect(r[0], old_h - r[3], r[2], old_h - r[1])
            y_center = (old_rect_f.y0 + old_rect_f.y1) / 2

            if subtype == '/Square':
                split_rectangles = split_multi_item_square(
                    p_old_f, old_rect_f, new_idx, old_sections[old_idx]
                )
                if split_rectangles:
                    for target_idx, target_rect in split_rectangles:
                        target_page = reader_new.pages[target_idx]
                        # pdfrw annotation objects cannot be copied with
                        # copy.copy() (their __setstate__ is None).
                        split_annot = pdfrw.PdfDict(annot)
                        page_height = doc_new[target_idx].rect.height
                        split_annot.Rect = pdfrw.PdfArray([
                            pdfrw.PdfObject(f"{value:.4f}") for value in [
                                target_rect.x0, page_height - target_rect.y1,
                                target_rect.x1, page_height - target_rect.y0
                            ]
                        ])
                        if split_annot.get('/P'):
                            split_annot.P = target_page
                        if not target_page.Annots:
                            target_page.Annots = pdfrw.PdfArray()
                        target_page.Annots.append(split_annot)
                    continue

            if subtype == '/Line':
                split_lines = split_code_column_line(
                    p_old_f, old_rect_f, new_idx, old_sections[old_idx]
                )
                if not split_lines:
                    split_lines = align_vertical_line_by_nearby_codes(
                        p_old_f, old_rect_f, new_idx, old_sections[old_idx]
                    )
                if not split_lines:
                    aligned_line = align_horizontal_line(
                        p_old_f, old_rect_f, new_idx, old_sections[old_idx]
                    )
                    split_lines = [aligned_line] if aligned_line else []
                if split_lines:
                    for target_idx, start, end in split_lines:
                        target_page = reader_new.pages[target_idx]
                        split_annot = pdfrw.PdfDict(annot)
                        # Each segment must be a distinct PDF object.  Keeping
                        # the source annotation's indirect reference lets the
                        # writer collapse split line segments back into one,
                        # which is why a line spanning two new pages vanished
                        # or appeared on the wrong page.
                        split_annot.indirect = True
                        page_height = doc_new[target_idx].rect.height
                        # A line's old appearance stream contains drawing
                        # commands at its former coordinates.  Some viewers keep
                        # showing that cached stream until the annotation is
                        # clicked.  Remove it so the moved /L is rendered on the
                        # first open.
                        for key in ['/AP', '/RD', '/BE']:
                            if split_annot.get(key):
                                del split_annot[key]
                        split_annot.L = pdfrw.PdfArray([
                            pdfrw.PdfObject(f"{start.x:.4f}"),
                            pdfrw.PdfObject(f"{page_height - start.y:.4f}"),
                            pdfrw.PdfObject(f"{end.x:.4f}"),
                            pdfrw.PdfObject(f"{page_height - end.y:.4f}")
                        ])
                        # Keep a non-zero rectangle around a vertical line.  A
                        # zero-width /Rect is legal in practice but commonly
                        # gets culled by PDF viewers until they redraw it.
                        rect_pad = max(1.5, abs(end.x - start.x) / 2 + 0.5)
                        split_annot.Rect = pdfrw.PdfArray([
                            pdfrw.PdfObject(f"{min(start.x, end.x) - rect_pad:.4f}"),
                            pdfrw.PdfObject(f"{page_height - max(start.y, end.y) - rect_pad:.4f}"),
                            pdfrw.PdfObject(f"{max(start.x, end.x) + rect_pad:.4f}"),
                            pdfrw.PdfObject(f"{page_height - min(start.y, end.y) + rect_pad:.4f}")
                        ])
                        if split_annot.get('/P'):
                            split_annot.P = target_page
                        if not target_page.Annots:
                            target_page.Annots = pdfrw.PdfArray()
                        target_page.Annots.append(split_annot)
                    continue

            # 使用距離權重局部共識決定當前標記的基準對應頁面
            local_new_idx = consensus_new_idx
            # Do not preemptively switch pages from nearby annotations.  Each
            # annotation first checks its CSV-mapped page, then falls back to a
            # neighbour only if its own text is absent there.
            if False and allow_neighbors and voting_anchors:
                page_scores = {}
                for matched_idx, v_y, weight in voting_anchors:
                    dist = abs(y_center - v_y)
                    # 權重與距離成反比，加入 50.0 的平滑值防止除以零且平衡近鄰影響
                    score = weight / (dist + 50.0)
                    page_scores[matched_idx] = page_scores.get(matched_idx, 0.0) + score
                local_new_idx = max(page_scores, key=page_scores.get)

            p_new_f = doc_new[local_new_idx]
            p_new_p = reader_new.pages[local_new_idx]
            if not p_new_p.Annots: p_new_p.Annots = pdfrw.PdfArray()

            target_new_idx = local_new_idx
            dx, dy = 0, 0
            text_result = None
            if subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly', '/Square', '/Circle', '/Redact']:
                old_quadpoints = annot.get(PN('QuadPoints'))
                text_result, matched_idx = find_best_text_match(
                    p_old_f, local_new_idx, old_rect_f, old_quadpoints, old_sections[old_idx],
                    allow_neighbors
                )
                if text_result:
                    target_new_idx = matched_idx
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

                    # A tiny rectangle often marks one symbol (for example,
                    # "*").  Text extraction can expand that symbol into an
                    # adjacent word; in that case retain the original box size
                    # and use a confirmed annotation on the same row.
                    if subtype == '/Square' and (r[2] - r[0]) < 50:
                        same_row = find_same_row_reference(
                            old_rect_f, processed_offsets_map[old_idx]
                        )
                        proposed_width = new_rect_annot[2] - new_rect_annot[0]
                        if (same_row and same_row[2] == target_new_idx and
                                proposed_width > (r[2] - r[0]) * 1.5 and
                                (abs(dx - same_row[0]) > 6 or
                                 abs(dy - same_row[1]) > 6)):
                            dx, dy = same_row[0], same_row[1]
                            new_rect_annot = [
                                r[0] + dx, r[1] - dy,
                                r[2] + dx, r[3] - dy
                            ]

                    w_old = r[2] - r[0]
                    h_old = r[3] - r[1]
                    w_new = new_rect_annot[2] - new_rect_annot[0]
                    h_new = new_rect_annot[3] - new_rect_annot[1]

                    # Keep a boundary mark with an adjacent note that already
                    # maps to this annotation's CSV target page.
                    if (subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly'] and
                            target_new_idx != new_idx):
                        same_page_neighbor = any(
                            target_idx == new_idx and
                            max(reference_rect.y0 - old_rect_f.y1,
                                old_rect_f.y0 - reference_rect.y1, 0) <= 22
                            for reference_rect, _, _, target_idx, _
                            in processed_offsets_map[old_idx]
                        )
                        if same_page_neighbor:
                            if old_quadpoints:
                                annot[PN('QuadPoints')] = pdfrw.PdfArray([
                                    pdfrw.PdfObject(f"{float(value):.4f}")
                                    for value in old_quadpoints
                                ])
                            text_result = None
                            target_new_idx = new_idx

            # 無文字對位結果時，採用錨點比對或繼承群組位移
            status = "未群組"
            if not text_result:
                if subtype == '/FreeText':
                    code_row = find_code_row_anchor(
                        p_old_f, old_rect_f, local_new_idx,
                        old_sections[old_idx]
                    )
                    same_row = find_same_row_reference(
                        old_rect_f, processed_offsets_map[old_idx]
                    )
                    if code_row:
                        best_dx, best_dy, best_target_idx = code_row
                        best_status = "code-row-anchor"
                    elif same_row:
                        # 同列螢光筆已透過文字重繪成功，直接共用它的位移。
                        # 這能保留「文字寫在被標示內容右側」的語意。
                        best_dx, best_dy, best_target_idx = same_row
                        best_status = "同列錨點"
                    else:
                        # 沒有同列標記時，文字筆記才以自身周邊多個文字
                        # 錨點定位，並在必要時檢查相鄰頁。
                        best_match_count = -1
                        best_dx, best_dy = 0, 0
                        best_target_idx = local_new_idx
                        best_status = "兜底零位移"
                        # Keep ordinary typed notes on their CSV-mapped page.
                        # Unlike highlights, their own text cannot establish a
                        # reliable cross-page match, so a neighbour's similar
                        # paragraph must not move just one note away from the
                        # other notes on the page.
                        offsets = [0]
                        for offset in offsets:
                            cand_idx = local_new_idx + offset
                            if not (0 <= cand_idx < len(doc_new)):
                                continue
                            if not sections_match(old_sections[old_idx], new_sections[cand_idx]):
                                continue
                            cand_dx, cand_dy, _, cand_status, cand_match_count = find_precise_offset(
                                p_old_f, doc_new[cand_idx], old_rect_f, [], spans_cache,
                                allow_group=False, prefer_context=True
                            )
                            # 先以同一組上下文錨點數量取勝；相同時保留距離較近的頁面。
                            if (cand_match_count > best_match_count or
                                (cand_match_count == best_match_count and
                                 abs(offset) < abs(best_target_idx - local_new_idx))):
                                best_match_count = cand_match_count
                                best_dx, best_dy = cand_dx, cand_dy
                                best_target_idx = cand_idx
                                best_status = cand_status

                        # One nearby word is too weak to reposition a typed
                        # note: repeated labels can pull it to an unrelated
                        # part of the page.  Without a code-row or same-row
                        # annotation anchor, require two consistent document
                        # anchors and otherwise retain the original position.
                        if best_match_count < 2:
                            best_dx, best_dy = 0, 0
                            best_target_idx = local_new_idx
                            best_status = "conservative-no-shift"

                    # A FreeText note has no source text that can prove a large
                    # displacement.  If its nearby-word heuristic proposes a
                    # jump of roughly a paragraph or more, it is almost always
                    # following a repeated heading / code rather than the note's
                    # actual row.  Retain the mapped-page position in that case.
                    if (best_target_idx != local_new_idx or abs(best_dy) > 100 or
                            abs(best_dx) > 45):
                        best_dx, best_dy = 0, 0
                        best_target_idx = local_new_idx
                        best_status = "conservative-keep-page-position"

                    target_new_idx = best_target_idx
                    cand_p_new = doc_new[target_new_idx]
                    dx = best_dx + (cand_p_new.rect.x0 - p_old_f.rect.x0)
                    dy = best_dy + (cand_p_new.rect.y0 - p_old_f.rect.y0)
                    status = best_status
                # 對於螢光筆、底線等標記，若無法匹配到文字，直接留在原本的物理位置 (原地)，不要隨錨點或群組位移偏移
                elif subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly']:
                    target_new_idx = local_new_idx
                    cand_p_new = doc_new[target_new_idx]
                    dx = (cand_p_new.rect.x0 - p_old_f.rect.x0)
                    dy = (cand_p_new.rect.y0 - p_old_f.rect.y0)
                else:
                    text_dx, text_dy, group_target_idx, status, match_count = find_precise_offset(p_old_f, p_new_f, old_rect_f, processed_offsets_map[old_idx], spans_cache)                  
                    if status == "群組" and group_target_idx is not None:
                        target_new_idx = group_target_idx
                        dx = text_dx
                        dy = text_dy
                    else:
                        best_match_count = -1
                        best_dx, best_dy = 0, 0
                        best_target_idx = local_new_idx
                        for offset in [0, 1, -1, 2]:
                            cand_idx = local_new_idx + offset
                            if 0 <= cand_idx < len(doc_new):
                                if not sections_match(old_sections[old_idx], new_sections[cand_idx]):
                                    continue
                                cand_p_new = doc_new[cand_idx]
                                cand_dx, cand_dy, _, cand_status, cand_match_count = find_precise_offset(p_old_f, cand_p_new, old_rect_f, [], spans_cache)
                                if cand_status in ["精準AI", "弱AI"]:
                                    if cand_match_count > best_match_count:
                                        best_match_count = cand_match_count
                                        best_dx = cand_dx
                                        best_dy = cand_dy
                                        best_target_idx = cand_idx
                        
                        # 弱錨點防誤跳門檻：只有在跨頁跳轉時，才要求至少要有 3 個一致的錨點以防誤跳。同頁內比對時，哪怕只有 1-2 個錨點一致也允許套用微調位移
                        if best_target_idx != local_new_idx and best_match_count < 3:
                            target_new_idx = local_new_idx
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

            if subtype == '/FreeText':
                logging.info(
                    "FreeText migration: old_page=%s target_page=%s strategy=%s dx=%.1f dy=%.1f",
                    old_idx + 1, target_new_idx + 1, status, dx, dy
                )

            # 註解屬性清理與平移寫入：
            # 1. 對於 FreeText，保留 /AP 與 /DA 屬性以完整顯示中文字型。
            # 2. 對於螢光筆與底線等，刪除舊的 /AP 外觀流，強迫 PDF 閱讀器根據新的 /QuadPoints 重新生成正確的畫筆外觀，避免劃一大片。
            if subtype in ['/Highlight', '/Underline', '/StrikeOut', '/Squiggly', '/Line']:
                for key in ['/AP', '/RD', '/IT']:
                    if annot.get(key):
                        del annot[key]
            elif subtype == '/FreeText' and (abs(dx) > .1 or abs(dy) > .1):
                # PDF-XChange may retain a FreeText appearance stream at the
                # old visual position even after /Rect has moved.  Keep /DA
                # (font settings), but discard the stale appearance so the
                # viewer redraws it in the new rectangle.
                for key in ['/AP']:
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
