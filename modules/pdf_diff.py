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


def highlight_differences(
    base_pdf_path: str,
    test_pdf_path: str,
    output_path: str,
    highlight_color: Tuple[float, float, float] = (1, 0, 0)
) -> List[int]:
    base_doc = fitz.open(base_pdf_path)
    test_doc = fitz.open(test_pdf_path)
    pages_with_diffs = []

    for page_num in range(min(len(base_doc), len(test_doc))):
        base_page = base_doc[page_num]
        test_page = test_doc[page_num]

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
                        highlight.update()
        
        if has_diff:
            pages_with_diffs.append(page_num + 1)

    test_doc.save(output_path)
    base_doc.close()
    test_doc.close()
    return pages_with_diffs


def merge_pdfs_side_by_side(
    base_pdf_path: str,
    highlighted_pdf_path: str,
    output_path: str,
    dpi: int = 150
) -> None:
    base_doc = fitz.open(base_pdf_path)
    test_doc = fitz.open(highlighted_pdf_path)
    output_doc = fitz.open()

    for page_num in range(min(len(base_doc), len(test_doc))):
        base_page = base_doc.load_page(page_num)
        test_page = test_doc.load_page(page_num)

        width = base_page.rect.width + test_page.rect.width
        height = max(base_page.rect.height, test_page.rect.height)
        new_page = output_doc.new_page(width=width, height=height)

        # Insert base PDF page
        pix_base = base_page.get_pixmap(dpi=dpi)
        new_page.insert_image(fitz.Rect(0, 0, base_page.rect.width, base_page.rect.height), pixmap=pix_base)

        # Insert test PDF page (highlighted)
        pix_test = test_page.get_pixmap(dpi=dpi)
        new_page.insert_image(
            fitz.Rect(base_page.rect.width, 0, width, test_page.rect.height),
            pixmap=pix_test
        )

    output_doc.save(output_path)
    output_doc.close()
    base_doc.close()
    test_doc.close()


def highlight_and_bookmark_diffs(
    base_pdf_path: str,
    target_pdf_path: str,
    mapping: Dict[int, int],
    highlight_color: Tuple[float, float, float] = (1, 0, 0)
) -> List[int]:
    """
    根據 mapping 比較兩個 PDF 的內容，並在 target_pdf 中標記差異處與新增書籤。
    mapping: {old_page_idx: new_page_idx}
    """
    base_doc = fitz.open(base_pdf_path)
    target_doc = fitz.open(target_pdf_path)
    pages_with_diffs = []

    # 為了避免重複添加書籤，先記錄原本的 TOC
    toc = target_doc.get_toc()

    for old_idx, new_idx in mapping.items():
        if old_idx >= len(base_doc) or new_idx >= len(target_doc):
            continue

        base_page = base_doc[old_idx]
        test_page = target_doc[new_idx]

        base_words = extract_words(base_page)
        test_words = test_words = extract_words(test_page)

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
                        highlight.set_info(content=f"Content difference from original page {old_idx + 1}")
                        highlight.update()
        
        if has_diff:
            pages_with_diffs.append(new_idx + 1)
            toc.append([1, f"內容差異 (原第 {old_idx + 1} 頁 -> 新第 {new_idx + 1} 頁)", new_idx + 1])

    if pages_with_diffs:
        target_doc.set_toc(toc)
        # 使用 incremental=True 以保留原本的註解
        target_doc.saveIncr()

    base_doc.close()
    target_doc.close()
    return sorted(list(set(pages_with_diffs)))


def compare_two_pdfs(base_pdf_path: str,test_pdf_path: str,output_dir: str) -> Tuple[str, List[int]]:
    os.makedirs(output_dir, exist_ok=True)
    highlighted_pdf = os.path.join(output_dir, "highlighted_test.pdf")
    merged_output_pdf = os.path.join(output_dir, "side_by_side_comparison.pdf")
    diff_pages = highlight_differences(base_pdf_path, test_pdf_path, highlighted_pdf, (1, 0, 0))  # red highlight
    merge_pdfs_side_by_side(base_pdf_path, highlighted_pdf, merged_output_pdf)
    return merged_output_pdf, diff_pages


if __name__ == "__main__":
    BASE_PDF = "台灣癌症登記長表手冊__20250121.pdf"
    TEST_PDF = "台灣癌症登記長表手冊_20251224.pdf"
    OUTPUT_DIR = "comparison_output"

    result_pdf, diff_pages = compare_two_pdfs(BASE_PDF, TEST_PDF, OUTPUT_DIR)
    print(f"Comparison complete. Output saved to: {result_pdf}")
    if diff_pages:
        print(f"Differences found on pages: {', '.join(map(str, diff_pages))}")
    else:
        print("No differences found.")