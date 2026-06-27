import fitz

pdf_file = r"D:/YLH/notebook_flask/test/00編_手冊SSF2018v7全1140114修訂柔 .pdf"

def check_blank_page(pdf_path, page_num,header_ratio=0.08,footer_ratio=0.08):
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]

    annots = page.annots()
    has_notes = annots is not None and len(list(annots))>0
    annots = page.annots()
    if annots:
        for annot in list(annots):
            try:
                page.delete_annot(annot)
            except RuntimeError:
                pass

    width = page.rect.width
    height = page.rect.height
    clip = fitz.Rect(0,height * header_ratio,width,height * (1-footer_ratio))

    text = page.get_text("text", clip=clip)
    clean_text = "".join(text.split())
    is_original_blank = (clean_text == "")
    if is_original_blank:
        if has_notes:
            print(f"page:{page_num} (空白頁加上筆記)")
        else:
            print(f"page:{page_num} (純空白頁)")
    doc.close()

doc = fitz.open(pdf_file)
total_pages = len(doc)
doc.close()

for p in range(1, total_pages + 1):
    check_blank_page(pdf_file, p)