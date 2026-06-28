import fitz
import pdfplumber
import pandas as pd
import numpy as np
import re
from rapidfuzz import process, fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from modules.mapping.blank_pages import handle_blank_pages
# 目錄比對 (TOC 抽取 + 匹配)
def toc_mapping(old_pdf, new_pdf, toc_pages="auto", offset_input="auto", max_search_pages=15):

    def _extract_toc(pdf_path):
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

    def _clean(text):
        return re.sub(r"^\d+(\.\d+)*\s*", "", text).strip()

    old_raw, old_total = _extract_toc(old_pdf)
    new_raw, new_total = _extract_toc(new_pdf)

    old_titles = [_clean(e["title"]) for e in old_raw]
    new_titles = [_clean(e["title"]) for e in new_raw]

    data, matched_new = [], set()

    for i, item in enumerate(old_titles):
        result = process.extractOne(item, new_titles, scorer=fuzz.ratio)
        old_start = old_raw[i]["page_ref"]
        old_end = old_raw[i + 1]["page_ref"] - 1 if i + 1 < len(old_raw) else old_total

        if result:
            match, score, _ = result
            if score == 100:
                status = "Matched"; matched_new.add(match)
            elif score > 70:
                status = "Modified"; matched_new.add(match)
            else:
                match, score, status = None, 0, "Deleted"
        else:
            match, score, status = None, 0, "Deleted"

        ns, ne = (None, None)
        if match:
            idx = new_titles.index(match)
            ns = new_raw[idx]["page_ref"]
            ne = new_raw[idx + 1]["page_ref"] - 1 if idx + 1 < len(new_raw) else new_total

        data.append({
            "Old_TOC": item, "New_TOC": match, "Similarity": score, "Status": status,
            "Old_Start_Page": old_start, "Old_End_Page": old_end,
            "New_Start_Page": ns, "New_End_Page": ne
        })

    for i, item in enumerate(new_titles):
        if item not in matched_new:
            ns = new_raw[i]["page_ref"]
            ne = new_raw[i + 1]["page_ref"] - 1 if i + 1 < len(new_raw) else new_total
            data.append({
                "Old_TOC": None, "New_TOC": item, "Similarity": None, "Status": "Added",
                "Old_Start_Page": None, "Old_End_Page": None,
                "New_Start_Page": ns, "New_End_Page": ne
            })

    df_toc = pd.DataFrame(data, columns=[
        "Old_TOC", "New_TOC", "Similarity", "Status",
        "Old_Start_Page", "Old_End_Page", "New_Start_Page", "New_End_Page"
    ])

    # 修正已匹配章節的 New_End_Page
    matched_df = df_toc[df_toc['Status'].isin(["Matched", "Modified"])].copy()
    if not matched_df.empty:
        matched_df = matched_df.sort_values(by='New_Start_Page')
        indices = matched_df.index.tolist()
        for k in range(len(indices)):
            if k + 1 < len(indices):
                df_toc.at[indices[k], 'New_End_Page'] = df_toc.at[indices[k + 1], 'New_Start_Page'] - 1
            else:
                df_toc.at[indices[k], 'New_End_Page'] = new_total

    return df_toc, old_total, new_total


# 頁面內容抽取
def extract_text(pdf_path, header_ratio=0.1, footer_ratio=0.1):
    doc = fitz.open(pdf_path)
    data = []
    for i, page in enumerate(doc):
        w, h = page.rect.width, page.rect.height
        clip = fitz.Rect(0, h * header_ratio, w, h * (1 - footer_ratio))
        text = re.sub(r'\s+', ' ', page.get_text("text", clip=clip)).strip()
        if text:
            data.append({"page_num": i + 1, "content": text})
    doc.close()
    return pd.DataFrame(data)


# DP單調對齊 (目錄範圍約束)
def dp_align(df_old, df_new, df_toc):
    vectorizer = TfidfVectorizer().fit(df_new['content'].tolist() + df_old['content'].tolist())
    tfidf_old = vectorizer.transform(df_old['content'].tolist())
    tfidf_new = vectorizer.transform(df_new['content'].tolist())

    N, M = len(df_old), len(df_new)
    S = cosine_similarity(tfidf_old, tfidf_new)

    # 目錄範圍罰分
    for i in range(N):
        old_page = df_old.iloc[i]['page_num']
        toc_row = df_toc[(df_toc['Old_Start_Page'] <= old_page) &(df_toc['Old_End_Page'] >= old_page) &(df_toc['Status'].isin(["Matched", "Modified"]))]
        if not toc_row.empty:
            ns, ne = int(toc_row.iloc[0]['New_Start_Page']), int(toc_row.iloc[0]['New_End_Page'])
            for j in range(M):
                if not (ns <= df_new.iloc[j]['page_num'] <= ne):
                    S[i][j] -= 5.0
    # DP
    dp = np.full((N, M), -np.inf)
    parent = np.zeros((N, M), dtype=int)
    for j in range(M):
        dp[0][j] = S[0][j]

    for i in range(1, N):
        running_max = -np.inf
        for j in range(M):
            best_val, best_k = dp[i - 1][j] - 0.05, j

            if j >= 1 and dp[i - 1][j - 1] > best_val:
                best_val, best_k = dp[i - 1][j - 1], j - 1

            if j >= 2:
                val_k = dp[i - 1][j - 2] + 0.2 * (j - 2)
                if val_k > running_max:
                    running_max = val_k
                if running_max - 0.2 * j + 0.2 > best_val:
                    best_jump, best_jump_k = -np.inf, j - 2
                    for k in range(j - 2, -1, -1):
                        score = dp[i - 1][k] - 0.2 * (j - k - 1)
                        if score > best_jump:
                            best_jump, best_jump_k = score, k
                        if score < best_jump - 2.0:
                            break
                    if best_jump > best_val:
                        best_val, best_k = best_jump, best_jump_k

            dp[i][j] = S[i][j] + best_val
            parent[i][j] = best_k

    # 回溯
    path, curr = [], np.argmax(dp[N - 1])
    for i in range(N - 1, -1, -1):
        path.append(curr)
        curr = parent[i][curr]
    path.reverse()

    # 建立結果
    results = []
    for i in range(N):
        old_page = df_old.iloc[i]['page_num']
        new_page = df_new.iloc[path[i]]['page_num']
        sim = round(float(S[i][path[i]]), 4)
        toc_row = df_toc[(df_toc['Old_Start_Page'] <= old_page) &(df_toc['Old_End_Page'] >= old_page) &(df_toc['Status'].isin(["Matched", "Modified"]))]
        mode = f"Local (TOC: {toc_row.iloc[0]['New_TOC']})" if not toc_row.empty else "Global"
        results.append({"Old_Page": old_page, "New_Page": new_page, "Similarity": sim, "Mode": mode})
    return pd.DataFrame(results)


# 整合流程
def UseMapping(old_pdf_path, new_pdf_path, output_csv, output_pdf):
    df_toc, old_total, new_total_orig = toc_mapping(old_pdf_path, new_pdf_path)
    df_old = extract_text(old_pdf_path)
    df_new = extract_text(new_pdf_path)
    old_content = set(df_old['page_num'].tolist())
    new_content = set(df_new['page_num'].tolist())
    old_blanks = set(range(1, old_total + 1)) - old_content
    new_blanks = set(range(1, new_total_orig + 1)) - new_content

    content_df = dp_align(df_old, df_new, df_toc)
    matched_blanks, inserted_blanks, shift_map, new_total = handle_blank_pages(old_blanks, new_blanks, content_df, new_pdf_path, output_pdf)

    content_map = {int(r['Old_Page']): r for _, r in content_df.iterrows()}
    blank_match = {m['old_page']: m['new_page'] for m in matched_blanks}
    blank_insert = {ins['old_page']: ins['insert_after'] for ins in inserted_blanks}
    insert_positions = sorted(ins['insert_after'] for ins in inserted_blanks)

    rows = []
    for old_page in range(1, old_total + 1):
        if old_page in content_map:
            r = content_map[old_page]
            orig = int(r['New_Page'])
            adj = shift_map.get(orig, orig) if shift_map else orig
            sim = r['Similarity']
            conf = "High" if sim >= 0.8 else ("Medium" if sim >= 0.5 else "Low")
            rows.append({
                "Old_Page": old_page, "New_Page": adj,
                "Similarity": sim, "Mode": r['Mode'],
                "Confidence": conf, "Note": ""
            })

        elif old_page in blank_match:
            orig = blank_match[old_page]
            adj = shift_map.get(orig, orig) if shift_map else orig
            rows.append({
                "Old_Page": old_page, "New_Page": adj,
                "Similarity": 1.0, "Mode": "Blank Page Match",
                "Confidence": "High", "Note": "Blank Page"
            })

        elif old_page in blank_insert:
            after = blank_insert[old_page]
            shift = sum(1 for p in insert_positions if p < after)
            same = [op for op in sorted(blank_insert) if blank_insert[op] == after]
            rank = same.index(old_page) if old_page in same else 0
            adj = after + shift + rank + 1
            rows.append({
                "Old_Page": old_page, "New_Page": adj,
                "Similarity": 1.0, "Mode": "Blank Page Inserted",
                "Confidence": "High", "Note": "Blank Page Added"
            })

        else:
            rows.append({
                "Old_Page": old_page, "New_Page": None,
                "Similarity": 0, "Mode": "Unmatched",
                "Confidence": "Low", "Note": ""
            })

    result_df = pd.DataFrame(rows).sort_values("Old_Page").reset_index(drop=True)
    result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    # for mode, cnt in result_df['Mode'].value_counts().items():
    #     print(f"{mode}: {cnt}")
    return result_df