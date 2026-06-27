import fitz      
import pdfplumber
import pandas as pd
import numpy as np
import re
import os
from rapidfuzz import process, fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from modules.pdf_diff import highlight_and_bookmark_diffs

# 空白頁偵測
def get_blank_pages(pdf_path, header_ratio=0.08, footer_ratio=0.08):
    blank_pages = set()
    doc = fitz.open(pdf_path)
    for page_num in range(len(doc)):
        page = doc[page_num]
        width = page.rect.width
        height = page.rect.height
        clip = fitz.Rect(0, height * header_ratio, width, height * (1 - footer_ratio))
        text = page.get_text("text", clip=clip)
        clean_text = "".join(text.split())
        if clean_text == "":
            blank_pages.add(page_num + 1)
    doc.close()
    return blank_pages

# 目錄比對
def extract_toc(pdf_path, toc_pages="auto", offset_input="auto", max_search_pages=15):
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if str(toc_pages).lower() == "auto":
            toc_pages_detected = [
                i + 1 for i in range(min(max_search_pages, total_pages))
                if len(re.findall(r'^(.*?)\s+(\d+)$', pdf.pages[i].extract_text() or "", re.MULTILINE)) > 3
            ]
        else:
            toc_pages_detected = [int(p) for p in str(toc_pages).split(",")]

        raw_toc = []
        for p in [p for p in toc_pages_detected if p <= total_pages]:
            text = pdf.pages[p - 1].extract_text() or ""
            for title, page_ref in re.findall(r'^(.*?)\s+(\d+)$', text, re.MULTILINE):
                title = re.sub(r'[.．。\s]+$', '', title).strip()
                if len(title) > 1:
                    raw_toc.append({"title": title, "page_ref": int(page_ref)})
                    
        offset = 0 if str(offset_input).lower() == "auto" else int(offset_input or 0)
        if str(offset_input).lower() == "auto" and raw_toc:
            offsets = []
            for e in raw_toc[:5]:
                for i in range(toc_pages_detected[-1] if toc_pages_detected else 0, total_pages):
                    if e["title"] in (pdf.pages[i].extract_text() or ""):
                        offsets.append((i + 1) - e["page_ref"])
                        break
            offset = max(set(offsets), key=offsets.count) if offsets else 0

        for e in raw_toc:
            e["page_ref"] += offset

    return raw_toc, total_pages

def clean_title(text):
    text = re.sub(r"^\d+(\.\d+)*\s*", "", text)
    return text.strip()

def toc_mapping(old_pdf, new_pdf):
    old_raw, old_total_pages = extract_toc(old_pdf)
    new_raw, new_total_pages = extract_toc(new_pdf)

    old_titles = [clean_title(e["title"]) for e in old_raw]
    new_titles = [clean_title(e["title"]) for e in new_raw]

    data = []
    matched_new = set()

    for i, item in enumerate(old_titles):
        result = process.extractOne(item, new_titles, scorer=fuzz.ratio)
        old_start_page = old_raw[i]["page_ref"]
        old_end_page = old_raw[i+1]["page_ref"] - 1 if i + 1 < len(old_raw) else old_total_pages 

        if result:
            match, score, _ = result
            if score == 100:
                status = "Matched"
                matched_new.add(match)
            elif score > 70:
                status = "Modified"
                matched_new.add(match)
            else:
                match, score, status = None, 0, "Deleted"
        else:
            match, score, status = None, 0, "Deleted"

        if match:
            new_idx = new_titles.index(match)
            new_start_page = new_raw[new_idx]["page_ref"]
            new_end_page = new_raw[new_idx+1]["page_ref"] - 1 if new_idx + 1 < len(new_raw) else new_total_pages
        else:
            new_start_page, new_end_page = None, None

        data.append({
            "Old_TOC": item, "New_TOC": match, "Similarity": score, "Status": status,
            "Old_Start_Page": old_start_page, "Old_End_Page": old_end_page,
            "New_Start_Page": new_start_page, "New_End_Page": new_end_page
        })

    for i, item in enumerate(new_titles):
        if item not in matched_new:
            new_start_page = new_raw[i]["page_ref"]
            new_end_page = new_raw[i+1]["page_ref"] - 1 if i + 1 < len(new_raw) else new_total_pages
            data.append({
                "Old_TOC": None, "New_TOC": item, "Similarity": None, "Status": "Added",
                "Old_Start_Page": None, "Old_End_Page": None,
                "New_Start_Page": new_start_page, "New_End_Page": new_end_page
            })

    df_toc = pd.DataFrame(data, columns=[
        "Old_TOC", "New_TOC", "Similarity", "Status",
        "Old_Start_Page", "Old_End_Page", "New_Start_Page", "New_End_Page"
    ])
    
    # 修正已匹配/已修改章節的 New_End_Page，避免被新增的子項目切斷
    matched_df = df_toc[df_toc['Status'].isin(["Matched", "Modified"])].copy()
    if not matched_df.empty:
        # 依新版開始頁碼排序，確保區間邊界正確
        matched_df = matched_df.sort_values(by='New_Start_Page')
        matched_indices = matched_df.index.tolist()
        for idx_curr in range(len(matched_indices)):
            curr_row_idx = matched_indices[idx_curr]
            if idx_curr + 1 < len(matched_indices):
                next_row_idx = matched_indices[idx_curr + 1]
                df_toc.at[curr_row_idx, 'New_End_Page'] = df_toc.at[next_row_idx, 'New_Start_Page'] - 1
            else:
                df_toc.at[curr_row_idx, 'New_End_Page'] = new_total_pages

    return df_toc

# ============================================================
# 頁面內容抽取
# ============================================================
def extract_text_with_tables(pdf_path, ignore_header_ratio=0.1, ignore_footer_ratio=0.1):
    doc = fitz.open(pdf_path)
    data = []
    for page_num, page in enumerate(doc):
        width, height = page.rect.width, page.rect.height
        clip_rect = fitz.Rect(0, height * ignore_header_ratio, width, height * (1 - ignore_footer_ratio))
        text = page.get_text("text", clip=clip_rect)
        full_text = re.sub(r'\s+', ' ', text).strip()

        if not full_text: 
            continue
        data.append({"page_num": page_num + 1,"content": full_text})
    doc.close()
    return pd.DataFrame(data)

# ============================================================
# 目錄範圍的頁面比對模組 (僅處理有內容的頁面)
# ============================================================
def mapping_pages_with_toc_bounds(df_old, df_new, df_toc):
    vectorizer = TfidfVectorizer().fit(df_new['content'].tolist() + df_old['content'].tolist())
    tfidf_new = vectorizer.transform(df_new['content'].tolist())
    tfidf_old = vectorizer.transform(df_old['content'].tolist())

    N = len(df_old)
    M = len(df_new)

    # 計算相似度矩陣 S (N x M)
    S = cosine_similarity(tfidf_old, tfidf_new)

    # 將目錄範圍限制以罰分的形式融入相似度矩陣
    for i in range(N):
        old_page = df_old.iloc[i]['page_num']
        matched_toc_row = df_toc[
            (df_toc['Old_Start_Page'] <= old_page) & 
            (df_toc['Old_End_Page'] >= old_page) &
            (df_toc['Status'].isin(["Matched", "Modified"]))
        ]
        if not matched_toc_row.empty:
            toc_record = matched_toc_row.iloc[0]
            new_start = int(toc_record['New_Start_Page'])
            new_end = int(toc_record['New_End_Page'])
            for j in range(M):
                new_page = df_new.iloc[j]['page_num']
                if not (new_start <= new_page <= new_end):
                    S[i][j] -= 5.0

    # DP 單調對齊演算法 (Monotonic Sequence Alignment)
    # dp[i][j] 代表將舊版前 i 頁對齊到新版手冊第 j 頁時的最大累計相似度得分
    dp = np.full((N, M), -np.inf)
    parent = np.zeros((N, M), dtype=int)

    # 初始化第一列 (舊版第 1 頁)
    for j in range(M):
        dp[0][j] = S[0][j]

    # 動態規劃轉移
    for i in range(1, N):
        running_max = -np.inf
        for j in range(M):
            # 選擇 1: 對齊到同一個新頁面 (多頁對應到同一頁，小幅罰分)
            best_val = dp[i-1][j] - 0.05
            best_k = j
            
            # 選擇 2: 依序往下一頁對齊 (最理想狀況，無罰分)
            if j - 1 >= 0:
                if dp[i-1][j-1] > best_val:
                    best_val = dp[i-1][j-1]
                    best_k = j - 1
                    
            # 選擇 3: 跨頁向後跳躍對齊 (新版有新增頁面，給予與跳躍距離成正比之罰分)
            if j - 2 >= 0:
                val_k = dp[i-1][j-2] + 0.2 * (j-2)
                if val_k > running_max:
                    running_max = val_k
                opt_jump = running_max - 0.2 * j + 0.2
                if opt_jump > best_val:
                    best_jump = -np.inf
                    best_jump_k = j - 2
                    # 回溯尋找最佳的跳躍來源 k
                    for k in range(j-2, -1, -1):
                        score = dp[i-1][k] - 0.2 * (j - k - 1)
                        if score > best_jump:
                            best_jump = score
                            best_jump_k = k
                        if dp[i-1][k] - 0.2 * (j - k - 1) < best_jump - 2.0:
                            break  # 剪枝優化
                    if best_jump > best_val:
                        best_val = best_jump
                        best_k = best_jump_k
                        
            dp[i][j] = S[i][j] + best_val
            parent[i][j] = best_k

    # 回溯尋找最優路徑
    best_end_j = np.argmax(dp[N-1])
    path = []
    curr_j = best_end_j
    for i in range(N-1, -1, -1):
        path.append(curr_j)
        curr_j = parent[i][curr_j]
    path.reverse()

    # 重構比對報告
    results = []
    for i in range(N):
        old_page = df_old.iloc[i]['page_num']
        matched_new_page = df_new.iloc[path[i]]['page_num']
        best_score = S[i][path[i]]
        
        # 決定 Search_Mode 記錄
        matched_toc_row = df_toc[
            (df_toc['Old_Start_Page'] <= old_page) & 
            (df_toc['Old_End_Page'] >= old_page) &
            (df_toc['Status'].isin(["Matched", "Modified"]))
        ]
        search_mode = "Global"
        if not matched_toc_row.empty:
            search_mode = f"Local (TOC: {matched_toc_row.iloc[0]['New_TOC']})"

        results.append({
            "Old_Page": old_page,
            "Matched_New_Page": matched_new_page,
            "Similarity_Score": round(float(best_score), 4),
            "Search_Mode": search_mode,
            "Match_Reason": "DP Monotonic Alignment",
        })

    result_df = pd.DataFrame(results)
    return result_df

# ============================================================
# 空白頁匹配：將舊版空白頁與新版空白頁做不重複配對
# ============================================================
def match_blank_pages(old_blank_pages, new_blank_pages, content_mapping_df):
    """
    根據內容頁的比對結果，將舊版空白頁與新版空白頁做匹配。
    匹配規則：以舊版空白頁的上下頁在新版中的對應位置為參考，
              找出附近最近的、尚未被匹配的新版空白頁。
    
    Returns:
        matched_blanks: list of dict  已匹配的空白頁 {old_page, new_page}
        unmatched_old_blanks: list of dict  舊版多出的空白頁 {old_page, insert_after_new_page}
    """
    # 建立 old_page -> new_page 的映射 (從內容頁比對結果)
    old_to_new = {}
    for _, row in content_mapping_df.iterrows():
        old_to_new[int(row['Old_Page'])] = int(row['Matched_New_Page'])
    
    old_blanks_sorted = sorted(old_blank_pages)
    new_blanks_available = set(new_blank_pages)  # 可用的新版空白頁（尚未被匹配的）
    
    matched_blanks = []
    unmatched_old_blanks = []
    
    for old_bp in old_blanks_sorted:
        # 找出這個舊版空白頁的「前一個有內容的頁面」和「後一個有內容的頁面」在新版中的對應
        prev_new_page = None
        next_new_page = None
        
        # 向前搜尋最近的已匹配內容頁
        for p in range(old_bp - 1, 0, -1):
            if p in old_to_new:
                prev_new_page = old_to_new[p]
                break
        
        # 向後搜尋最近的已匹配內容頁
        max_old_page = max(old_to_new.keys()) if old_to_new else old_bp
        for p in range(old_bp + 1, max_old_page + 2):
            if p in old_to_new:
                next_new_page = old_to_new[p]
                break
        
        # 在新版中搜尋附近未匹配的空白頁
        # 搜尋範圍：prev_new_page ~ next_new_page 之間
        search_start = (prev_new_page or 1)
        search_end = (next_new_page or search_start + 5)
        
        best_new_blank = None
        best_distance = float('inf')
        
        # 目標位置：大約在 prev_new_page 之後
        target_pos = (prev_new_page + 1) if prev_new_page else search_start
        
        for nb in new_blanks_available:
            if search_start <= nb <= search_end:
                dist = abs(nb - target_pos)
                if dist < best_distance:
                    best_distance = dist
                    best_new_blank = nb
        
        if best_new_blank is not None:
            # 匹配成功
            matched_blanks.append({
                "old_page": old_bp,
                "new_page": best_new_blank
            })
            new_blanks_available.discard(best_new_blank)
        else:
            # 沒有對應的新版空白頁 → 需要插入
            insert_after = prev_new_page if prev_new_page else (next_new_page - 1 if next_new_page else 1)
            unmatched_old_blanks.append({
                "old_page": old_bp,
                "insert_after_new_page": insert_after
            })
    
    return matched_blanks, unmatched_old_blanks

# ============================================================
# 在新版 PDF 中插入空白頁
# ============================================================
def insert_blank_pages_into_pdf(new_pdf_path, insertions, output_pdf_path):
    """
    insertions: list of dict, 每筆有 'insert_after_new_page' (1-based, 原始新版頁碼)
    在指定位置插入空白頁，並儲存為新的 PDF。
    
    Returns:
        page_shift_map: dict  原始新版頁碼 -> 調整後新版頁碼
        new_total_pages: int  新 PDF 的總頁數
    """
    if not insertions:
        # 不需要插入，直接複製
        doc = fitz.open(new_pdf_path)
        doc.save(output_pdf_path)
        total = len(doc)
        doc.close()
        # 頁碼不變
        return {}, total
    
    doc = fitz.open(new_pdf_path)
    original_total = len(doc)
    
    # 依照要插入的位置排序（由大到小插入，避免索引偏移）
    sorted_insertions = sorted(insertions, key=lambda x: x['insert_after_new_page'], reverse=True)
    
    # 記錄每個插入點 (1-based 原始頁碼)
    insert_positions = sorted([ins['insert_after_new_page'] for ins in sorted_insertions])
    
    # 由後往前插入空白頁
    for ins in sorted_insertions:
        insert_idx = ins['insert_after_new_page']  # 1-based
        # fitz 使用 0-based index，在 insert_idx 之後插入
        # 取得參考頁面的尺寸
        if insert_idx - 1 < len(doc):
            ref_page = doc[insert_idx - 1]
            page_width = ref_page.rect.width
            page_height = ref_page.rect.height
        else:
            page_width = 595  # A4 default
            page_height = 842
        
        doc.insert_page(insert_idx, text="", width=page_width, height=page_height)
        print(f"  插入空白頁: 在原始新版第 {insert_idx} 頁之後")
    
    doc.save(output_pdf_path)
    new_total = len(doc)
    doc.close()
    
    # 計算頁碼偏移映射：原始新版頁碼 → 調整後頁碼
    # insert_positions 是已排序的原始插入位置
    page_shift_map = {}
    for orig_page in range(1, original_total + 1):
        shift = sum(1 for pos in insert_positions if pos < orig_page)
        page_shift_map[orig_page] = orig_page + shift
    
    return page_shift_map, new_total

# ============================================================
# 整合流程：比對 + 空白頁匹配 + PDF 輸出 + Excel 報表
# ============================================================
def process_and_match_pdfs(old_pdf_path, new_pdf_path, output_excel, output_pdf):
    print("=" * 60)
    print("步驟 1: 目錄比對")
    print("=" * 60)
    
    df_toc = toc_mapping(old_pdf_path, new_pdf_path)
    print(f"  目錄比對完成，共 {len(df_toc)} 筆目錄項目")
    
    print("\n" + "=" * 60)
    print("步驟 2: 內容頁面抽取")
    print("=" * 60)
    
    df_old_text = extract_text_with_tables(old_pdf_path)
    df_new_text = extract_text_with_tables(new_pdf_path)
    
    # 取得新舊版 PDF 總頁數
    doc_old = fitz.open(old_pdf_path)
    old_total_pages = len(doc_old)
    doc_old.close()
    doc_new = fitz.open(new_pdf_path)
    new_total_pages_original = len(doc_new)
    doc_new.close()
    
    # 用內容抽取結果定義空白頁 (確保 100% 覆蓋，不會有遺漏)
    old_content_pages = set(df_old_text['page_num'].tolist())
    new_content_pages = set(df_new_text['page_num'].tolist())
    old_blanks = set(range(1, old_total_pages + 1)) - old_content_pages
    new_blanks = set(range(1, new_total_pages_original + 1)) - new_content_pages
    
    print(f"  舊版總頁數: {old_total_pages} (內容頁: {len(old_content_pages)}, 空白頁: {len(old_blanks)})")
    print(f"  新版總頁數: {new_total_pages_original} (內容頁: {len(new_content_pages)}, 空白頁: {len(new_blanks)})")
    if old_blanks:
        print(f"  舊版空白頁: {sorted(old_blanks)}")
    if new_blanks:
        print(f"  新版空白頁: {sorted(new_blanks)}")
    
    print("\n" + "=" * 60)
    print("步驟 3: 內容頁面比對 (DP 對齊)")
    print("=" * 60)
    
    content_mapping_df = mapping_pages_with_toc_bounds(df_old_text, df_new_text, df_toc)
    print(f"  內容頁比對完成，共 {len(content_mapping_df)} 筆匹配")
    
    print("\n" + "=" * 60)
    print("步驟 4: 空白頁匹配")
    print("=" * 60)
    
    matched_blanks, unmatched_old_blanks = match_blank_pages(old_blanks, new_blanks, content_mapping_df)
    print(f"  已匹配空白頁: {len(matched_blanks)} 筆")
    for mb in matched_blanks:
        print(f"    舊版第 {mb['old_page']} 頁 <-> 新版第 {mb['new_page']} 頁")
    print(f"  需插入空白頁: {len(unmatched_old_blanks)} 筆")
    for ub in unmatched_old_blanks:
        print(f"    舊版第 {ub['old_page']} 頁 -> 將插入於新版第 {ub['insert_after_new_page']} 頁之後")
    
    print("\n" + "=" * 60)
    print("步驟 5: 插入空白頁到新版 PDF")
    print("=" * 60)
    
    page_shift_map, new_total_pages = insert_blank_pages_into_pdf(
        new_pdf_path, unmatched_old_blanks, output_pdf
    )
    
    if page_shift_map:
        print(f"  已插入 {len(unmatched_old_blanks)} 頁空白頁")
        print(f"  新版 PDF 總頁數 (插入後): {new_total_pages}")
    else:
        print("  無需插入空白頁")
    
    print(f"  輸出 PDF: {output_pdf}")
    
    print("\n" + "=" * 60)
    print("步驟 6: 產生比對報表 (Excel)")
    print("=" * 60)
    
    # 計算插入空白頁的原始位置（用於計算新插入空白頁的最終頁碼）
    insert_positions_sorted = sorted([ins['insert_after_new_page'] for ins in unmatched_old_blanks])
    
    # 建立完整比對報表
    final_results = []
    
    # 將內容頁比對結果轉為 dict: old_page -> row
    content_map = {}
    for _, row in content_mapping_df.iterrows():
        content_map[int(row['Old_Page'])] = row
    
    # 將已匹配空白頁轉為 dict: old_page -> new_page
    blank_match_map = {}
    for mb in matched_blanks:
        blank_match_map[mb['old_page']] = mb['new_page']
    
    # 將需插入空白頁轉為 dict: old_page -> insert_after
    blank_insert_map = {}
    for ub in unmatched_old_blanks:
        blank_insert_map[ub['old_page']] = ub['insert_after_new_page']
    
    # 追蹤所有已被匹配到的新版原始頁碼 (用於找出新版多出來的頁面)
    matched_new_pages_original = set()
    
    # --- 遍歷所有舊版頁碼 ---
    for old_page in range(1, old_total_pages + 1):
        if old_page in content_map:
            # 有內容的頁面
            row = content_map[old_page]
            orig_new_page = int(row['Matched_New_Page'])
            matched_new_pages_original.add(orig_new_page)
            
            # 調整頁碼（如果有插入空白頁的話）
            adjusted_new_page = page_shift_map.get(orig_new_page, orig_new_page) if page_shift_map else orig_new_page
            
            similarity = row['Similarity_Score']
            mode = row['Search_Mode']
            reason = row['Match_Reason']
            
            if similarity >= 0.8:
                note = "高度相似"
            elif similarity >= 0.5:
                note = "中度相似"
            else:
                note = "低度相似，請人工確認"
            
            final_results.append({
                "舊版頁碼": old_page,
                "新版頁碼": adjusted_new_page,
                "比對相似度": similarity,
                "模式": mode,
                "備註": f"{reason} - {note}"
            })
            
        elif old_page in blank_match_map:
            # 已匹配的空白頁
            orig_new_page = blank_match_map[old_page]
            matched_new_pages_original.add(orig_new_page)
            adjusted_new_page = page_shift_map.get(orig_new_page, orig_new_page) if page_shift_map else orig_new_page
            
            final_results.append({
                "舊版頁碼": old_page,
                "新版頁碼": adjusted_new_page,
                "比對相似度": 1.0,
                "模式": "Blank Page Match",
                "備註": "空白頁匹配（新舊版皆為空白頁）"
            })
            
        elif old_page in blank_insert_map:
            # 需插入的空白頁
            insert_after = blank_insert_map[old_page]
            shift_before = sum(1 for pos in insert_positions_sorted if pos < insert_after)
            same_pos_pages = [op for op in sorted(blank_insert_map.keys()) 
                              if blank_insert_map[op] == insert_after]
            rank_in_same = same_pos_pages.index(old_page) if old_page in same_pos_pages else 0
            adjusted_new_page = insert_after + shift_before + rank_in_same + 1
            
            final_results.append({
                "舊版頁碼": old_page,
                "新版頁碼": adjusted_new_page,
                "比對相似度": 1.0,
                "模式": "Blank Page Inserted",
                "備註": f"新版原無空白頁，已插入空白頁於第 {adjusted_new_page} 頁"
            })
        else:
            # 遺漏頁面 (理論上不會出現)
            final_results.append({
                "舊版頁碼": old_page,
                "新版頁碼": None,
                "比對相似度": 0,
                "模式": "Unmatched",
                "備註": "未匹配"
            })
    
    # --- 遍歷新版多出來的頁碼 (舊版沒有對應的頁面) ---
    for new_page_orig in range(1, new_total_pages_original + 1):
        if new_page_orig not in matched_new_pages_original:
            adjusted_new_page = page_shift_map.get(new_page_orig, new_page_orig) if page_shift_map else new_page_orig
            
            if new_page_orig in new_blanks:
                final_results.append({
                    "舊版頁碼": None,
                    "新版頁碼": adjusted_new_page,
                    "比對相似度": None,
                    "模式": "New Blank Page",
                    "備註": "新版新增空白頁（舊版無對應）"
                })
            else:
                final_results.append({
                    "舊版頁碼": None,
                    "新版頁碼": adjusted_new_page,
                    "比對相似度": None,
                    "模式": "New Added Page",
                    "備註": "新版新增內容頁（舊版無對應）"
                })
    
    # 依新版頁碼排序 (舊版頁碼為 None 的排在對應新版頁碼位置)
    final_df = pd.DataFrame(final_results)
    final_df = final_df.sort_values(
        by=["新版頁碼"], 
        key=lambda x: x.fillna(0).astype(int),
        na_position='last'
    ).reset_index(drop=True)
    
    # 輸出 Excel
    final_df.to_excel(output_excel, index=False, engine="openpyxl")
    print(f"  Excel 報表已儲存: {output_excel}")
    print(f"  共 {len(final_df)} 筆比對記錄")
    
    # 印出摘要統計
    old_matched = final_df[final_df['舊版頁碼'].notna()]
    new_only = final_df[final_df['舊版頁碼'].isna()]
    
    print("\n" + "=" * 60)
    print("比對摘要")
    print("=" * 60)
    print(f"  舊版總頁數: {old_total_pages}")
    print(f"  新版總頁數 (原始): {new_total_pages_original}")
    print(f"  新版總頁數 (插入後): {new_total_pages}")
    print(f"  舊版頁面已匹配: {len(old_matched)} / {old_total_pages}")
    print(f"  新版多出頁面: {len(new_only)} 頁")
    print(f"  內容頁匹配: {len(content_map)} 頁")
    print(f"  空白頁匹配: {len(matched_blanks)} 頁")
    print(f"  空白頁插入: {len(unmatched_old_blanks)} 頁")
    mode_counts = final_df['模式'].value_counts()
    print(f"  模式分佈:")
    for mode, count in mode_counts.items():
        print(f"    {mode}: {count}")
    
    return final_df


# ============================================================
# 主程式
# ============================================================
if __name__ == "__main__":
    old_pdf = r"D:\YLH\notebook_flask\static\docVersion\doc996b418c.pdf"
    new_pdf = r"D:\YLH\notebook_flask\static\docVersion\doc52d059af.pdf"
    
    output_dir = r"D:\YLH\notebook_flask\test"
    os.makedirs(output_dir, exist_ok=True)
    
    output_excel = os.path.join(output_dir, "comparison_report.xlsx")
    output_pdf   = os.path.join(output_dir, "new_version_with_blanks.pdf")
    
    result_df = process_and_match_pdfs(old_pdf, new_pdf, output_excel, output_pdf)
    
    print("\n完成！")
    print(f"  比對報表: {output_excel}")
    print(f"  新版 PDF: {output_pdf}")