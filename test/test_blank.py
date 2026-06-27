import fitz
import json

# 筆記PDF偵測空白頁
def get_pdf_blank_pages(pdf_file, header_ratio=0.08, footer_ratio=0.08):
    def check_blank_page(doc, page_num):
        page = doc[page_num - 1]
        annots = page.annots()
        if annots:
            for annot in list(annots):
                try:
                    page.delete_annot(annot)
                except RuntimeError:
                    pass

        width = page.rect.width
        height = page.rect.height
        clip = fitz.Rect(0, height * header_ratio, width, height * (1 - footer_ratio))
        text = page.get_text("text", clip=clip)
        clean_text = "".join(text.split())
        return clean_text == ""

    doc = fitz.open(pdf_file)
    total_pages = len(doc)   
    blank_pages = []

    for p in range(1, total_pages + 1):
        if check_blank_page(doc, p):
            blank_pages.append(p) 
    doc.close()
    return blank_pages

# 原始文件JSON空白頁碼
def get_json_blank_pages(json_file):
    with open(json_file, 'r', encoding='utf-8') as file:
        data = json.load(file)

    blank_pages = data.get("blank_pages", {})
    old_blanks = blank_pages.get("old_blanks", [])
    return old_blanks

# 頁碼偏移並比對
def compare_shifted_pages(old_blanks, new_blanks):
    i = 0 
    j = 0 
    offset = 0
    
    matched = []    # 原有空白頁對應(原始文件頁碼,筆記頁碼)
    inserted = []   # 新增的空白筆記頁(筆記頁碼)
    
    while i < len(old_blanks) and j < len(new_blanks):
        expected_new_page = old_blanks[i] + offset
        current_new_page = new_blanks[j]
        
        if current_new_page == expected_new_page:
            matched.append((old_blanks[i], current_new_page))
            i += 1
            j += 1
        elif current_new_page < expected_new_page:
            inserted.append(current_new_page)
            offset += 1
            j += 1
        else:
            offset -= 1
            i += 1
    while j < len(new_blanks):
        inserted.append(new_blanks[j])
        j += 1           
    return matched, inserted

if __name__ == "__main__":
    pdf_path = r"D:/YLH/notebook_flask/test/00編_手冊SSF2018v7全1140114修訂柔 .pdf"
    json_path = r"D:\YLH\notebook_flask\test\map5101aceb.json"

    old_list = get_json_blank_pages(json_path)
    new_list = get_pdf_blank_pages(pdf_path)
    matched_pages, new_pages = compare_shifted_pages(old_list, new_list)

    for old_p, new_p in matched_pages:
        print(f"原始文件:P.{old_p} ===> 筆記:P.{new_p}")
    print(f"\n新增空白頁:{new_pages}")