const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('pdfInput');
const overlay = document.getElementById('loadingOverlay');
const loadingText = document.getElementById('loadingText');

// 拖曳上傳
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) {
        handleUpload(e.dataTransfer.files[0]);
    }
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleUpload(e.target.files[0]);
    }
});

// 處理檔案上傳
async function handleUpload(file) {
    if (file.type !== 'application/pdf') {
        alert('上傳錯誤：請上傳 PDF 檔案！');
        return;
    }

    loadingText.textContent = "正在上傳PDF中...";
    overlay.style.display = 'flex';

    const fd = new FormData();
    fd.append("pdf", file);

    try {
        const response = await fetch("/upload_pdf", { 
            method: "POST", 
            body: fd 
        });

        if (!response.ok) throw new Error("伺服器回應錯誤");

        const data = await response.json();
        const sessionData = {
            doc_id: data.doc_id,           // UUID
            pdf_name: data.pdf_name,       // UUID.pdf
            original_name: data.original_name,
            total_pages: data.total_pages,
            mods: data.mods || {},         // 新檔案通常為空
            width: data.width,
            height: data.height,
            has_toc: data.has_embedded_toc
        };

        localStorage.setItem("currentPdfSession", JSON.stringify(sessionData));
        window.location.href = "/edit"; 

    } catch (err) {
        console.error(err);
        alert("上傳失敗，請檢查網路或檔案大小。");
        overlay.style.display = 'none';
        fileInput.value = ''; 
    }
}

// --- 舊檔案載入 ---
async function loadExistingDoc(docId) {
    loadingText.textContent = "正在讀取標註紀錄...";
    overlay.style.display = 'flex';

    const response = await fetch(`/get_doc_info/${docId}`);
    const data = await response.json();
    const sessionData = {
        doc_id: data.doc_id,
        pdf_name: data.pdf_name,
        original_name: data.original_name,
        total_pages: data.total_pages,
        mods: data.mods, // 標註JSON
        width: data.width,
        height: data.height,
        has_toc: data.has_embedded_toc
    };

    localStorage.setItem("currentPdfSession", JSON.stringify(sessionData));
    window.location.href = "/edit";

}
// 工具庫
async function doc_tool(actionType, docId, event) {
    if (event) {
        event.stopPropagation();
    }

    if (actionType === 'delete') {
        if (!confirm("確定要刪除這份文件嗎？")) {
            return;
        }
        loadingText.textContent = "正在刪除文件...";
    } else {
        loadingText.textContent = "正在讀取文件與標註紀錄...";
    }

    overlay.style.display = 'flex';

    try {
        const response = await fetch("/doc_tool", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                action: actionType, // edit or delete
                doc_id: docId
            })
        });

        const result = await response.json();

        if (actionType === 'delete') {
            alert("刪除成功！");
            window.location.reload();
            
        } else if (actionType === 'edit') {
            const data = result.data;
            const sessionData = {
                doc_id: data.doc_id,
                pdf_name: data.pdf_name,
                original_name: data.original_name,
                total_pages: data.total_pages,
                mods: data.mods, 
                width: data.width,
                height: data.height,
                has_toc: data.has_toc
            };

            localStorage.setItem("currentPdfSession", JSON.stringify(sessionData));
            window.location.href = "/edit"; 
        }

    } catch (err) {
        console.error(err);
        alert("錯誤：" + err.message);
        overlay.style.display = 'none'; 
    }
}

// --- 搜尋 ---
document.getElementById('searchInput').addEventListener('keyup', function(e) {
    const term = e.target.value.toLowerCase();
    const items = document.querySelectorAll('.doc-item');
    items.forEach(item => {
        const title = item.querySelector('.card-title').textContent.toLowerCase();
        if (title.includes(term)) {
            item.style.display = 'block';
        } else {
            item.style.display = 'none';
        }
    });
});

