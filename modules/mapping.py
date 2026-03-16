import fitz      
import pdfplumber
import pandas as pd
import re
from rapidfuzz import process, fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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

    df_toc = pd.DataFrame(data)
    return df_toc

# 頁面內容抽取
def extract_text_with_tables(pdf_path, ignore_header_ratio=0.1, ignore_footer_ratio=0.1):
    doc = fitz.open(pdf_path)
    data = []

    with pdfplumber.open(pdf_path) as pdf_plumber:
        for page_num, page in enumerate(doc):
            width, height = page.rect.width, page.rect.height
            clip_rect = fitz.Rect(0, height * ignore_header_ratio, width, height * (1 - ignore_footer_ratio))

            text = page.get_text("text", clip=clip_rect)
            text = re.sub(r'\s+', ' ', text).strip()

            table_texts = []
            if page_num < len(pdf_plumber.pages):
                tables = pdf_plumber.pages[page_num].extract_tables()
                if tables:  
                    for table in tables:
                        for row in table:
                            table_texts.append(" ".join([str(cell) for cell in row if cell]))

            full_text = (text + " " + " ".join(table_texts)).strip()
            if not full_text: continue

            data.append({
                "page_num": page_num + 1,
                "content": full_text
            })

    return pd.DataFrame(data)

# 目錄範圍的頁面比對模組
def mapping_pages_with_toc_bounds(df_old, df_new, df_toc, output_csv):
    vectorizer = TfidfVectorizer().fit(df_new['content'].tolist() + df_old['content'].tolist())
    tfidf_new = vectorizer.transform(df_new['content'].tolist())
    tfidf_old = vectorizer.transform(df_old['content'].tolist())

    results = []
    
    for i in range(len(df_old)):
        old_page = df_old.iloc[i]['page_num']
        
        matched_toc_row = df_toc[
            (df_toc['Old_Start_Page'] <= old_page) & 
            (df_toc['Old_End_Page'] >= old_page) &
            (df_toc['Status'].isin(["Matched", "Modified"]))
        ]

        search_indices = []
        search_mode = "Global" 

        if not matched_toc_row.empty:
            toc_record = matched_toc_row.iloc[0]
            new_start = toc_record['New_Start_Page']
            new_end = toc_record['New_End_Page']
            search_indices = df_new.index[(df_new['page_num'] >= new_start) & (df_new['page_num'] <= new_end)].tolist()
            
            if search_indices:
                search_mode = f"Local (TOC: {toc_record['New_TOC']})"

        if not search_indices:
            search_indices = df_new.index.tolist()
            search_mode = "Global (Fallback)"

        similarities = cosine_similarity(tfidf_old[i], tfidf_new[search_indices])
        scores = similarities[0]
        
        top_k = min(3, len(scores))
        top_local_indices = scores.argsort()[-top_k:][::-1]     
        candidates = []
        for loc_idx in top_local_indices:
            glob_idx = search_indices[loc_idx]
            candidates.append({
                'page_num': df_new.iloc[glob_idx]['page_num'],
                'score': scores[loc_idx]
            })
   
        valid_candidates = [c for c in candidates if abs(c['page_num'] - old_page) <= 20]
        
        if valid_candidates:
            best_match = valid_candidates[0]
            match_reason = "Top3 & Distance<=20"
        else:
            best_match = candidates[0]
            match_reason = "Highest Score (Distance>20)"
            
        matched_new_page = best_match['page_num']
        best_score = best_match['score']

        results.append({
            "Old_Page": old_page,
            "Matched_New_Page": matched_new_page,
            "Similarity_Score": round(best_score, 4),
            "Search_Mode": search_mode,
            "Match_Reason": match_reason,
            "Confidence": "High" if best_score > 0.8 else ("Low" if best_score < 0.5 else "Medium")
        })

    result_df = pd.DataFrame(results)
    result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"save to {output_csv}")
    return result_df

def UseMapping(old_pdf, new_pdf, output_report):
    df_toc = toc_mapping(old_pdf, new_pdf)
    df_old_text = extract_text_with_tables(old_pdf)
    df_new_text = extract_text_with_tables(new_pdf)
    result_df = mapping_pages_with_toc_bounds(df_old_text, df_new_text, df_toc, output_csv=output_report)
    return result_df