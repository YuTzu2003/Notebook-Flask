import fitz      
import pdfplumber
import pandas as pd
import numpy as np
import re
from rapidfuzz import process, fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from modules.mapping.pdf_diff import highlight_and_bookmark_diffs

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

# 頁面內容抽取
def extract_text_with_tables(pdf_path, ignore_header_ratio=0.1, ignore_footer_ratio=0.1):
    doc = fitz.open(pdf_path)
    data = []

    for page_num, page in enumerate(doc):
        width, height = page.rect.width, page.rect.height
        clip_rect = fitz.Rect(0, height * ignore_header_ratio, width, height * (1 - ignore_footer_ratio))

        text = page.get_text("text", clip=clip_rect)
        full_text = re.sub(r'\s+', ' ', text).strip()

        if not full_text: continue

        data.append({
            "page_num": page_num + 1,
            "content": full_text
        })

    doc.close()
    return pd.DataFrame(data)

# 目錄範圍的頁面比對模組
def mapping_pages_with_toc_bounds(df_old, df_new, df_toc, output_csv):
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
                    S[i][j] -= 5.0  # 超出目錄邊界給予極大罰分，防止跨章節錯位

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
            "Confidence": "High" if best_score > 0.8 else ("Low" if best_score < 0.5 else "Medium")
        })

    result_df = pd.DataFrame(results)
    result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"save to {output_csv}")
    return result_df

def UseMapping(old_pdf, new_pdf, output_report, diff_pdf_output):
    df_toc = toc_mapping(old_pdf, new_pdf)
    df_old_text = extract_text_with_tables(old_pdf)
    df_new_text = extract_text_with_tables(new_pdf)
    result_df = mapping_pages_with_toc_bounds(df_old_text, df_new_text, df_toc, output_csv=output_report)
    
    # 建立 0-based mapping dictionary 給 pdf_diff 使用
    mapping_dict = {
        int(row["Old_Page"]) - 1: int(row["Matched_New_Page"]) - 1
        for _, row in result_df.iterrows()
    }
    
    try:
        diff_pages, _ = highlight_and_bookmark_diffs(old_pdf, new_pdf, mapping_dict, diff_pdf_output)
    except Exception as e:
        print(f"差異標記生成失敗: {e}")
        diff_pages = []

    return result_df, diff_pages