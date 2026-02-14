import fitz
import pdfplumber
import pandas as pd
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def extract_text_with_tables(pdf_path, ignore_header_ratio=0.1, ignore_footer_ratio=0.1):
    doc = fitz.open(pdf_path)
    data = []

    with pdfplumber.open(pdf_path) as pdf_plumber:
        for page_num, page in enumerate(doc):
            width = page.rect.width
            height = page.rect.height
            clip_rect = fitz.Rect(
                0, height * ignore_header_ratio,
                width, height * (1 - ignore_footer_ratio)
            )

            # PyMuPDF 抽段落文字
            text = page.get_text("text", clip=clip_rect)
            text = re.sub(r'\s+', ' ', text).strip()

            # PDFPlumber 抽表格文字
            table_texts = []
            if page_num < len(pdf_plumber.pages):
                tables = pdf_plumber.pages[page_num].extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            table_texts.append(
                                " ".join(str(cell) for cell in row if cell)
                            )

            full_text = (text + " " + " ".join(table_texts)).strip()
            if not full_text:
                continue

            data.append({
                "page_num": page_num + 1,
                "raw_text_len": len(full_text),
                "content": full_text
            })

    return pd.DataFrame(data)


def mapping_version(df_old, df_new, output_report="mapping.csv"):
    df_old = df_old.dropna(subset=['content'])
    df_new = df_new.dropna(subset=['content'])

    if df_old.empty or df_new.empty:
        print("警告：舊版或新版沒有內容，無法比對")
        return pd.DataFrame()

    # TF-IDF 向量化
    vectorizer = TfidfVectorizer().fit(
        df_new['content'].tolist() + df_old['content'].tolist()
    )
    tfidf_new = vectorizer.transform(df_new['content'].tolist())
    tfidf_old = vectorizer.transform(df_old['content'].tolist())

    similarity_matrix = cosine_similarity(tfidf_old, tfidf_new)

    results = []
    for i in range(len(df_old)):
        old_page = df_old.iloc[i]['page_num']
        scores = similarity_matrix[i]
        best_idx = scores.argmax()
        best_score = scores[best_idx]
        new_page = df_new.iloc[best_idx]['page_num']

        results.append({
            "Old_Page": old_page,
            "Matched_New_Page": new_page,
            "Similarity_Score": round(best_score, 4),
            "Status": (
                "High Confidence" if best_score > 0.8
                else "Low Confidence" if best_score < 0.5
                else "Medium"
            )
        })

    result_df = pd.DataFrame(results)
    result_df.to_csv(output_report, index=False, encoding="utf-8-sig")

    print(f"Mapping file generated: {output_report}")
    print(result_df.head(10))
    return result_df

def UseMapping(old_pdf, new_pdf, output_report):
    df_old = extract_text_with_tables(old_pdf)
    df_new = extract_text_with_tables(new_pdf)
    return mapping_version(df_old, df_new, output_report)