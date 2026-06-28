import fitz
import json
import pandas as pd
import re
import os

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
    return blank_pages, total_pages

def get_json_blank_pages(json_file):
    with open(json_file, 'r', encoding='utf-8') as file:
        data = json.load(file)
    blank_pages = data.get("blank_pages", {})
    old_blanks = blank_pages.get("old_blanks", [])
    return old_blanks

def compare_shifted_pages(old_blanks, new_blanks):
    i = 0 
    j = 0 
    offset = 0
    matched = []
    inserted = []
    
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

def generate_dynamic_template(user_pdf_path, json_path, csv_path, original_template_path, output_template_path, output_csv_path):
    print(f"開始處理: {user_pdf_path}")
    user_blanks, total_user_pages = get_pdf_blank_pages(user_pdf_path)
    sys_old_blanks = get_json_blank_pages(json_path)
    matched_pages, inserted_blanks = compare_shifted_pages(sys_old_blanks, user_blanks)
    print(f"額外新增空白頁: {inserted_blanks}")
    
    original_df = pd.read_csv(csv_path, encoding='utf-8-sig')
    sys_old_to_sys_new = {}
    for _, row in original_df.iterrows():
        if pd.notna(row.get('New_Page')) and str(row.get('New_Page')).strip() != "":
            sys_old_to_sys_new[int(row['Old_Page'])] = int(row['New_Page'])
            
    user_to_sys_old = {}
    sys_old_p = 1
    for user_p in range(1, total_user_pages + 1):
        if user_p in inserted_blanks:
            user_to_sys_old[user_p] = None
        else:
            user_to_sys_old[user_p] = sys_old_p
            sys_old_p += 1


    to_insert_into_template = []
    user_to_base_new = {}
    
    for user_p in range(1, total_user_pages + 1):
        if user_p in inserted_blanks:
            prev_user_p = user_p - 1
            insert_after_new_page = 1
            while prev_user_p > 0:
                if prev_user_p in user_to_base_new and user_to_base_new[prev_user_p] is not None:
                    insert_after_new_page = user_to_base_new[prev_user_p]
                    break
                prev_user_p -= 1
            to_insert_into_template.append({"user_page": user_p, "insert_after": insert_after_new_page})
            user_to_base_new[user_p] = None 
        else:
            s_old = user_to_sys_old[user_p]
            s_new = sys_old_to_sys_new.get(s_old, None)
            user_to_base_new[user_p] = s_new

    doc = fitz.open(original_template_path)
    for ins in sorted(to_insert_into_template, key=lambda x: x['insert_after'], reverse=True):
        idx = ins['insert_after']
        if idx - 1 < len(doc):
            ref = doc[idx - 1]
            w, h = ref.rect.width, ref.rect.height
        else:
            w, h = 595, 842
        doc.insert_page(idx, text="", width=w, height=h)
        print(f"於新版範本第 {idx} 頁後方，插入一張空白頁 (對應使用者第 {ins['user_page']} 頁)")
        
    doc.save(output_template_path)
    print(f"已產出專屬範本 PDF: {output_template_path}")
    doc.close()

    # 計算插入空白頁後的頁碼偏移 (Base New Page -> User Specific New Page)
    insert_positions = sorted(ins['insert_after'] for ins in to_insert_into_template)
    
    def get_shifted_new_page(base_page):
        if base_page is None:
            return None
        return base_page + sum(1 for pos in insert_positions if pos < base_page)
        
    # 建立最終的 CSV (User_Page -> New_Page)
    csv_rows = []
    for user_p in range(1, total_user_pages + 1):
        if user_p in inserted_blanks:
            ins_record = next(x for x in to_insert_into_template if x["user_page"] == user_p)
            base_pos = ins_record["insert_after"]
            order = sum(1 for x in to_insert_into_template if x["insert_after"] == base_pos and x["user_page"] <= user_p)
            shifted_base = get_shifted_new_page(base_pos) 
            
            final_new_p = base_pos + sum(1 for pos in insert_positions if pos < base_pos) + order
            csv_rows.append({
                "Old_Page": user_p, "New_Page": final_new_p,
                "Mode": "User Inserted Blank"
            })
        else:
            base_new = user_to_base_new[user_p]
            final_new = get_shifted_new_page(base_new)
            csv_rows.append({
                "Old_Page": user_p, "New_Page": final_new if final_new else "",
                "Mode": "Content/System Blank"
            })
            
    df_result = pd.DataFrame(csv_rows)
    df_result.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
    print(f"已產出專屬 Mapping CSV: {output_csv_path}")

if __name__ == "__main__":

    pdf_path = r"D:\YLH\notebook_flask\test\語-PDF-XChange測試2-Longform-Manual_Official-version_20250121_Y.pdf"
    json_path = r"D:\YLH\notebook_flask\tasks\docMapResult\mapa952afd3\mapa952afd3.json"
    
    csv_path = r"D:\YLH\notebook_flask\tasks\docMapResult\mapa952afd3\mapa952afd3.csv"
    original_template_path = r"D:\YLH\notebook_flask\tasks\docMapResult\mapa952afd3\mapa952afd3_template.pdf"
    
    output_template_path = r"D:/YLH/notebook_flask/test/User_Specific_Template.pdf"
    output_csv_path = r"D:/YLH/notebook_flask/test/User_Specific_Mapping.csv"

    generate_dynamic_template(pdf_path,json_path,csv_path,original_template_path,output_template_path,output_csv_path)
