import pdfrw
import fitz
import pandas as pd
import math
import statistics
import os
from rapidfuzz import fuzz, process

MANUAL_ADJUST_X = -4.0  
MANUAL_ADJUST_Y = 0.0


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

def find_precise_offset(page_old, page_new, old_rect, processed_offsets):
    for ref_rect, ref_dx, ref_dy in processed_offsets:
        if abs(old_rect.x0 - ref_rect.x0) < 30 and abs(old_rect.y0 - ref_rect.y0) < 150:
            return ref_dx, ref_dy, "群組"

    words_old = page_old.get_text("words")
    if not words_old: return 0, 0, "無舊文保底"
    
    words_new = page_new.get_text("words")
    if not words_new: return 0, 0, "無新文保底"

    annot_center = ((old_rect.x0 + old_rect.x1)/2, (old_rect.y0 + old_rect.y1)/2)
    sorted_words = sorted(words_old, key=lambda w: get_word_score(w, annot_center, old_rect))
    candidate_anchors = sorted_words[:12] 

    offsets_x = []
    offsets_y = []
    new_texts = [nw[4].strip() for nw in words_new]

    for cw in candidate_anchors:
        text = cw[4].strip()
        if len(text) < 2: continue 
        
        cw_rect_old = fitz.Rect(cw[:4])
        hits = page_new.search_for(text)
        if (not hits or len(hits) > 3) and len(text) >= 3:
            matches = process.extract(text, new_texts, scorer=fuzz.ratio, limit=2)
            for m_text, score, idx in matches:
                if score > 85:
                    hits.append(fitz.Rect(words_new[idx][:4]))

        if hits:
            best_hit = min(hits, key=lambda h: abs(h.y0 - cw_rect_old.y0) + abs(h.x0 - cw_rect_old.x0))
            dx = best_hit.x0 - cw_rect_old.x0
            dy = best_hit.y0 - cw_rect_old.y0
            if abs(dx) < page_new.rect.width * 0.4 and abs(dy) < page_new.rect.height * 0.4:
                offsets_x.append(dx)
                offsets_y.append(dy)

    if len(offsets_x) >= 2:
        return statistics.median(offsets_x), statistics.median(offsets_y), "精準AI"
    elif len(offsets_x) == 1:
        return offsets_x[0], offsets_y[0], "弱AI"

    return 0, 0, "兜底零位移"


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

    processed_offsets_map = {}

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

        for annot in annots:
            if not annot.get('/Rect'): continue

            subtype = annot.get('/Subtype')
            r = [float(x) for x in annot['/Rect']]
            old_h = p_old_f.rect.height
            old_rect_f = fitz.Rect(r[0], old_h - r[3], r[2], old_h - r[1])
            text_dx, text_dy, status = find_precise_offset(p_old_f, p_new_f, old_rect_f, processed_offsets_map[old_idx])
            dx = text_dx + page_origin_dx + MANUAL_ADJUST_X
            dy = text_dy + page_origin_dy + MANUAL_ADJUST_Y

            processed_offsets_map[old_idx].append((old_rect_f, dx, dy))

            if subtype == '/FreeText':
                for key in ['/AP', '/RD', '/IT']:
                    if annot.get(key): del annot[key]
                annot.DA = pdfrw.PdfObject("( /Helv 12 Tf 1 0 0 rg )") 
            elif subtype in ['/Line', '/Highlight', '/Ink', '/Square', '/Underline']:
                if annot.get('/AP') and annot['/AP'].get('/N'):
                    n = annot['/AP']['/N']
                    if isinstance(n, pdfrw.PdfDict):
                        orig_matrix = n.get('/Matrix')
                        if not orig_matrix:
                            n.Matrix = pdfrw.PdfArray([
                                pdfrw.PdfObject('1'), pdfrw.PdfObject('0'), 
                                pdfrw.PdfObject('0'), pdfrw.PdfObject('1'), 
                                pdfrw.PdfObject(f"{dx:.4f}"), pdfrw.PdfObject(f"{-dy:.4f}")
                            ])
                        else:
                            om = [float(x) for x in orig_matrix]
                            n.Matrix = pdfrw.PdfArray([
                                pdfrw.PdfObject(f"{om[0]}"), pdfrw.PdfObject(f"{om[1]}"), 
                                pdfrw.PdfObject(f"{om[2]}"), pdfrw.PdfObject(f"{om[3]}"), 
                                pdfrw.PdfObject(f"{(om[4]+dx):.4f}"), pdfrw.PdfObject(f"{(om[5]-dy):.4f}")
                            ])

            new_rect = [r[0] + dx, r[1] - dy, r[2] + dx, r[3] - dy]
            annot.Rect = pdfrw.PdfArray([pdfrw.PdfObject(f"{x:.4f}") for x in new_rect])

            for key_name in ['QuadPoints', 'Vertices']:
                val = annot.get(PN(key_name))
                if val:
                    pts = [float(x) for x in val]
                    new_pts = [pdfrw.PdfObject(f"{(pts[i]+dx if i%2==0 else pts[i]-dy):.4f}") for i in range(len(pts))]
                    annot[PN(key_name)] = pdfrw.PdfArray(new_pts)

            il = annot.get('/InkList')
            if il:
                new_ink = pdfrw.PdfArray()
                for path in il:
                    pts = [float(x) for x in path]
                    new_path = [pdfrw.PdfObject(f"{(pts[i]+dx if i%2==0 else pts[i]-dy):.4f}") for i in range(len(pts))]
                    new_ink.append(pdfrw.PdfArray(new_path))
                annot.InkList = new_ink

            p_new_p.Annots.append(annot)

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
                final_doc.saveIncr()
                final_doc.close()
        except Exception as e:
            print(f"添加差異書籤失敗: {e}")