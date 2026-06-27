import fitz  # PyMuPDF
import os
import re
from rapidfuzz.distance import Levenshtein
from typing import List, Dict, Tuple


def extract_words(page: fitz.Page) -> List[Dict]:
    words = []
    word_list = page.get_text("words")
    for word in word_list:
        words.append({"text": word[4],"rect": fitz.Rect(word[:4])})
    return words

def is_page_content_identical(page1: fitz.Page, page2: fitz.Page) -> bool:
    text1 = re.sub(r'\s+', '', page1.get_text())
    text2 = re.sub(r'\s+', '', page2.get_text())
    return text1 == text2

def group_and_merge_rects(rects: List[fitz.Rect], line_height_threshold: float = 5.0, horizontal_gap_threshold: float = 20.0) -> List[fitz.Rect]:
    if not rects:
        return []

    sorted_rects = sorted(rects, key=lambda r: r.y0)  
    lines = []
    current_line = [sorted_rects[0]]
    
    for r in sorted_rects[1:]:
        if abs(r.y0 - current_line[0].y0) <= line_height_threshold:
            current_line.append(r)
        else:
            lines.append(current_line)
            current_line = [r]
    lines.append(current_line)
    
    merged_rects = []
    for line in lines:
        line = sorted(line, key=lambda r: r.x0)
        curr_rect = line[0]
        for r in line[1:]:
            if r.x0 <= curr_rect.x1 + horizontal_gap_threshold:
                curr_rect = curr_rect | r
            else:
                merged_rects.append(curr_rect)
                curr_rect = r
        merged_rects.append(curr_rect)
        
    return merged_rects

def highlight_and_bookmark_diffs(base_pdf_path: str,target_pdf_path: str,mapping: Dict[int, int],output_path: str,highlight_color: Tuple[float, float, float] = (1, 0, 0)) -> Tuple[List[int], str]:
    base_doc = fitz.open(base_pdf_path)
    target_doc = fitz.open(target_pdf_path)
    pages_with_diffs = []
    toc = target_doc.get_toc()
    for old_idx, new_idx in mapping.items():
        if old_idx >= len(base_doc) or new_idx >= len(target_doc):
            continue

        base_page = base_doc[old_idx]
        test_page = target_doc[new_idx]

        if is_page_content_identical(base_page, test_page):
            continue

        base_words = extract_words(base_page)
        test_words = extract_words(test_page)

        base_text = [re.sub(r'\s+', '', word["text"]) for word in base_words]
        test_text = [re.sub(r'\s+', '', word["text"]) for word in test_words]

        opcodes = Levenshtein.opcodes(base_text, test_text)
        has_diff = False
        diff_rects = []
        for tag, _, _, j1, j2 in opcodes:
            if tag in ("insert", "replace", "delete"):
                has_diff = True
                for idx in range(j1, j2):
                    if idx < len(test_words):
                        diff_rects.append(test_words[idx]["rect"])

        if has_diff:
            pages_with_diffs.append(new_idx + 1)
            toc.append([1, f"內容差異 (原 p.{old_idx + 1} -> 新 p.{new_idx + 1})", new_idx + 1])
            if len(test_words) > 0 and len(diff_rects) / len(test_words) > 0.6:
                rect = fitz.Rect(10, 10, test_page.rect.width - 10, test_page.rect.height - 10)
                highlight = test_page.add_rect_annot(rect)
                highlight.set_colors(stroke=highlight_color)
                highlight.set_border(width=3)
                highlight.set_info(content=f"本頁內容相較於原第 {old_idx + 1} 頁有重大修改/完全重寫")
                highlight.update()
            else:
                # 合併同行相鄰的標記，顯著降低 PDF 標註物件數量，加速儲存與下載
                merged_rects = group_and_merge_rects(diff_rects)
                for rect in merged_rects:
                    highlight = test_page.add_highlight_annot(rect)
                    highlight.set_colors(stroke=highlight_color)
                    highlight.set_info(content=f"內容與原第 {old_idx + 1} 頁不同")
                    highlight.update()

    if pages_with_diffs:
        target_doc.set_toc(toc)

    target_doc.save(output_path)
    base_doc.close()
    target_doc.close()

    return sorted(list(set(pages_with_diffs))), output_path