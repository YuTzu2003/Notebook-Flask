import fitz  # PyMuPDF
import os
import re
from difflib import SequenceMatcher
from typing import List, Dict, Tuple


def extract_words(page: fitz.Page) -> List[Dict]:
    words = []
    word_list = page.get_text("words")
    for word in word_list:
        words.append({
            "text": word[4],
            "rect": fitz.Rect(word[:4])
        })
    return words

def is_page_content_identical(page1: fitz.Page, page2: fitz.Page) -> bool:
    """快速檢查兩頁的文字是否完全相同（忽略空白）"""
    text1 = re.sub(r'\s+', '', page1.get_text())
    text2 = re.sub(r'\s+', '', page2.get_text())
    return text1 == text2

def highlight_and_bookmark_diffs(
    base_pdf_path: str,
    target_pdf_path: str,
    mapping: Dict[int, int],
    output_path: str,
    highlight_color: Tuple[float, float, float] = (1, 0, 0)
) -> Tuple[List[int], str]:
    """
    根據 mapping 比較兩個 PDF 的內容。
    將新版有差異的地方加上紅色高亮，並加入書籤。
    儲存為 output_path。
    回傳: (有差異的頁碼清單, 產出的PDF路徑)
    """
    base_doc = fitz.open(base_pdf_path)
    target_doc = fitz.open(target_pdf_path)
    pages_with_diffs = []

    toc = target_doc.get_toc()

    for old_idx, new_idx in mapping.items():
        if old_idx >= len(base_doc) or new_idx >= len(target_doc):
            continue

        base_page = base_doc[old_idx]
        test_page = target_doc[new_idx]

        # 效能優化：快速比對
        if is_page_content_identical(base_page, test_page):
            continue

        base_words = extract_words(base_page)
        test_words = extract_words(test_page)

        base_text = [re.sub(r'\s+', '', word["text"]) for word in base_words]
        test_text = [re.sub(r'\s+', '', word["text"]) for word in test_words]

        matcher = SequenceMatcher(None, base_text, test_text)
        has_diff = False
        for tag, _, _, j1, j2 in matcher.get_opcodes():
            if tag in ("insert", "replace", "delete"):
                has_diff = True
                for idx in range(j1, j2):
                    if idx < len(test_words):
                        rect = test_words[idx]["rect"]
                        highlight = test_page.add_highlight_annot(rect)
                        highlight.set_colors(stroke=highlight_color)
                        highlight.set_info(content=f"內容與原第 {old_idx + 1} 頁不同")
                        highlight.update()

        if has_diff:
            pages_with_diffs.append(new_idx + 1)
            toc.append([1, f"內容差異 (原 p.{old_idx + 1} -> 新 p.{new_idx + 1})", new_idx + 1])

    if pages_with_diffs:
        target_doc.set_toc(toc)

    target_doc.save(output_path)
    base_doc.close()
    target_doc.close()

    return sorted(list(set(pages_with_diffs))), output_path