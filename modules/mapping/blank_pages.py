import fitz
import pandas as pd
import re

def handle_blank_pages(old_blanks, new_blanks, content_df, new_pdf_path, output_pdf):
    old_to_new = {int(r['Old_Page']): int(r['New_Page']) for _, r in content_df.iterrows()}
    matched, to_insert = [], []
    available = set(new_blanks)

    for bp in sorted(old_blanks):
        prev_new = next((old_to_new[p] for p in range(bp - 1, 0, -1) if p in old_to_new), None)
        max_p = max(old_to_new.keys()) if old_to_new else bp
        next_new = next((old_to_new[p] for p in range(bp + 1, max_p + 2) if p in old_to_new), None)

        lo = prev_new or 1
        hi = next_new or lo + 5
        target = (prev_new + 1) if prev_new else lo
        best = min((nb for nb in available if lo <= nb <= hi), key=lambda nb: abs(nb - target), default=None)

        if best is not None:
            matched.append({"old_page": bp, "new_page": best})
            available.discard(best)
        else:
            to_insert.append({"old_page": bp,"insert_after": prev_new if prev_new else (next_new - 1 if next_new else 1)})

    # 插入空白頁到 PDF
    doc = fitz.open(new_pdf_path)
    original_total = len(doc)

    for ins in sorted(to_insert, key=lambda x: x['insert_after'], reverse=True):
        idx = ins['insert_after']
        if idx - 1 < len(doc):
            ref = doc[idx - 1]
            w, h = ref.rect.width, ref.rect.height
        else:
            w, h = 595, 842
        doc.insert_page(idx, text="", width=w, height=h)

    doc.save(output_pdf)
    new_total = len(doc)
    doc.close()

    # 頁碼偏移
    positions = sorted(ins['insert_after'] for ins in to_insert)
    page_shift_map = {}
    for p in range(1, original_total + 1):
        page_shift_map[p] = p + sum(1 for pos in positions if pos < p)

    return matched, to_insert, page_shift_map, new_total

def get_blanks(pdf_path, header_ratio=0.1, footer_ratio=0.1):
    doc = fitz.open(pdf_path)
    blanks = []
    for i, page in enumerate(doc):
        w, h = page.rect.width, page.rect.height
        clip = fitz.Rect(0, h * header_ratio, w, h * (1 - footer_ratio))
        text = re.sub(r'\s+', ' ', page.get_text("text", clip=clip)).strip()
        if not text:
            blanks.append(i + 1)
    doc.close()
    return blanks