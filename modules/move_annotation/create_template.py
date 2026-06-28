import fitz
import pandas as pd
from modules.move_annotation.detect_blankPage import get_pdf_blank_pages, get_json_blank_pages, compare_shifted_pages

def generate_dynamic_template(user_pdf_path, json_path, csv_path, original_template_path, output_template_path, output_csv_path):
    # 掃描使用者 PDF 的空白頁
    user_blanks, total_user_pages = get_pdf_blank_pages(user_pdf_path)
    
    # 取得舊版的空白頁
    sys_old_blanks = get_json_blank_pages(json_path)
    
    # 比對找出筆記額外新增的空白頁
    matched_pages, inserted_blanks = compare_shifted_pages(sys_old_blanks, user_blanks)
    if not inserted_blanks:
        return False

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
            # 找前一個有對應的頁面來決定插入位置
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
    
    # 由後往前插入空白頁，避免頁碼錯亂
    for ins in sorted(to_insert_into_template, key=lambda x: x['insert_after'], reverse=True):
        idx = ins['insert_after']
        if idx - 1 < len(doc):
            ref = doc[idx - 1]
            w, h = ref.rect.width, ref.rect.height
        else:
            w, h = 595, 842
        doc.insert_page(idx, text="", width=w, height=h)

    doc.save(output_template_path)
    doc.close()

    # 計算插入空白頁後的頁碼偏移 (Base New Page -> User Specific New Page)
    insert_positions = sorted(ins['insert_after'] for ins in to_insert_into_template)
    
    def get_shifted_new_page(base_page):
        if base_page is None:
            return None
        return base_page + sum(1 for pos in insert_positions if pos < base_page)
        
    # 建立最終的CSV
    csv_rows = []
    for user_p in range(1, total_user_pages + 1):
        if user_p in inserted_blanks:
            ins_record = next(x for x in to_insert_into_template if x["user_page"] == user_p)
            base_pos = ins_record["insert_after"]
            order = sum(1 for x in to_insert_into_template if x["insert_after"] == base_pos and x["user_page"] <= user_p)
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
    return True