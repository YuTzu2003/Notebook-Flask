const canvas = new fabric.Canvas("c", { preserveObjectStacking: true });

let pdfDoc = null, pdfDataInfo = null;
let pageNum = 1, scale = 1.0; 
let isStickyMode = false, currentNoteObj = null, tempNoteImage = null;
const noteModal = new bootstrap.Modal(document.getElementById('noteModal'));

let interactionMode = 'text'; // 'text', 'highlight', 'underline', 'draw', 'object', 'sticky'

const hoverBox = document.getElementById('hoverPreview');
const previewTxt = document.getElementById('previewText');
const previewImg = document.getElementById('previewImg');

window.onload = async function() {
    const storedData = localStorage.getItem("currentPdfSession");
    if (!storedData) { alert("請先上傳檔案"); window.location.href = "/"; return; }
    pdfDataInfo = JSON.parse(storedData);
    document.getElementById("fileNameDisplay").innerText = pdfDataInfo.original_name;
    updateStyle('init');

    const loadingTask = pdfjsLib.getDocument(`/get_pdf_content/${pdfDataInfo.doc_id}`);
    pdfDoc = await loadingTask.promise;
    pdfDataInfo.total_pages = pdfDoc.numPages;
    renderPage(pageNum);
};

async function renderPage(num) {
    if(num < 1 || num > pdfDoc.numPages) return;
    
    if(pdfDataInfo.mods && pageNum !== num) saveCurrent();
    pageNum = num;
    
    const page = await pdfDoc.getPage(num);
    const dpr = window.devicePixelRatio || 1;

    const viewportDisplay = page.getViewport({ scale: scale });
    const viewportRender = page.getViewport({ scale: scale * dpr });
    
    const stack = document.getElementById("pageStack");
    stack.style.width = `${viewportDisplay.width}px`;
    stack.style.height = `${viewportDisplay.height}px`;

    const pdfCanvas = document.getElementById("pdfCanvas");
    const pdfCtx = pdfCanvas.getContext('2d');
    
    pdfCanvas.width = viewportRender.width;
    pdfCanvas.height = viewportRender.height;
    pdfCanvas.style.width = `${viewportDisplay.width}px`;
    pdfCanvas.style.height = `${viewportDisplay.height}px`;
    
    await page.render({ canvasContext: pdfCtx, viewport: viewportRender }).promise;

    const textLayerDiv = document.getElementById("textLayer");
    textLayerDiv.innerHTML = ""; 
    textLayerDiv.style.width = `${viewportDisplay.width}px`;
    textLayerDiv.style.height = `${viewportDisplay.height}px`;
    
    const textContent = await page.getTextContent();
    pdfjsLib.renderTextLayer({
        textContent: textContent,
        container: textLayerDiv,
        viewport: viewportDisplay,
        textDivs: []
    });

    canvas.setWidth(viewportDisplay.width);
    canvas.setHeight(viewportDisplay.height);
    canvas.setZoom(scale); 
    canvas.clear(); 

    if (pdfDataInfo.mods && pdfDataInfo.mods[num-1]) {
        fabric.util.enlivenObjects(pdfDataInfo.mods[num-1], objs => {
            objs.forEach(o => {
                if(o.data_type === 'sticky') o.set({hasControls:true, editable:false});
                if(o.data_type === 'highlight' || o.data_type === 'underline') {
                    o.set({selectable: false, evented: false});
                }
                canvas.add(o);
            });
            canvas.renderAll();
        });
    }

    document.getElementById("pageInfo").innerText = `${pageNum} / ${pdfDoc.numPages}`;
    document.getElementById("jumpPage").value = pageNum;
    updateActiveToc(pageNum);
    updateModeUI();
}

// --- (觸發螢光筆與底線) ---
document.addEventListener('mouseup', function() {
    const selection = window.getSelection();
    if (selection && selection.toString().trim() !== "") {
        setTimeout(() => {
            if (interactionMode === 'highlight') {
                highlightSelection(selection);
            } else if (interactionMode === 'underline') {
                underlineSelection(selection);
            }
        }, 10);
    }
});

// 螢光筆繪製
function highlightSelection(selection) {
    if (selection.rangeCount === 0) 
        return;
    const selectedText = selection.toString(); 
    const range = selection.getRangeAt(0);
    const rawRects = range.getClientRects(); 
    const canvasRect = canvas.getElement().getBoundingClientRect();     
    const color = document.getElementById("mainColor").value;
    const rgbaColor = hexToRgba(color, 0.5);
    const mergedRects = mergeRects(rawRects);

    for (let i = 0; i < mergedRects.length; i++) {
        const r = mergedRects[i];
        const left = (r.left - canvasRect.left) / scale;
        const top = (r.top - canvasRect.top) / scale;
        const width = r.width / scale;
        const height = r.height / scale;

        const rect = new fabric.Rect({
            left: left, top: top, width: width, height: height,
            fill: rgbaColor, rx: 0, ry: 0,
            selectable: false, evented: false,
            data_type: 'highlight',
            globalCompositeOperation: 'multiply',
            selectedText: selectedText 
        });
        canvas.add(rect);
    }
    selection.removeAllRanges(); 
    canvas.renderAll();
    saveCurrent();
}

// 底線繪製
function underlineSelection(selection) {
    if (selection.rangeCount === 0) 
        return;

    const selectedText = selection.toString();
    const range = selection.getRangeAt(0);
    const rawRects = range.getClientRects(); 
    const canvasRect = canvas.getElement().getBoundingClientRect();
    const color = document.getElementById("mainColor").value;
    const mergedRects = mergeRects(rawRects);

    for (let i = 0; i < mergedRects.length; i++) {
        const r = mergedRects[i];              
        const left = (r.left - canvasRect.left) / scale;
        const top = (r.top - canvasRect.top) / scale;
        const width = r.width / scale;
        const height = r.height / scale;
        const lineHeight = 1; // 底線粗細
        const lineOffset = 0.2; // 距離文字底部

        const line = new fabric.Rect({
            left: left,
            top: top + height - lineOffset,
            width: width,
            height: lineHeight,
            fill: color,
            selectable: false, 
            evented: false,
            data_type: 'underline',
            selectedText: selectedText 
        });
        canvas.add(line);
    }
    selection.removeAllRanges(); 
    canvas.renderAll();
    saveCurrent();
}

function mergeRects(rawRects) {
    const mergedRects = [];
    const tolerance = 2;
    for (let i = 0; i < rawRects.length; i++) {
        const r = rawRects[i];
        if (r.width === 0 || r.height === 0) continue;
        if (mergedRects.length > 0) {
            const last = mergedRects[mergedRects.length - 1];
            const sameLine = Math.abs(r.top - last.top) < tolerance && Math.abs(r.bottom - last.bottom) < tolerance;
            const overlapping = r.left < last.right + tolerance;
            if (sameLine && overlapping) {
                const newRight = Math.max(last.right, r.right);
                last.width = newRight - last.left;
                last.right = newRight; 
                last.height = Math.max(last.height, r.height);
                continue; 
            }
        }
        mergedRects.push({
            left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height
        });
    }
    return mergedRects;
}

function hexToRgba(hex, alpha) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// --- UI狀態 ---
function updateModeUI() {
    document.body.classList.remove("mode-text-select", "mode-drawing", "mode-object-edit", "mode-highlight", "mode-underline");
    
    const btnIds = ['drawBtn', 'stickyBtn', 'textBtn', 'selectObjBtn', 'highlightBtn', 'underlineBtn'];
    btnIds.forEach(id => {
        const btn = document.getElementById(id);
        if(btn) {
            btn.classList.remove("active", "btn-secondary", "btn-primary", "btn-warning", "btn-dark");
            
            if(id === 'selectObjBtn') btn.classList.add("btn-outline-info");
            else if(id === 'highlightBtn') btn.classList.add("btn-outline-primary");
            else if(id === 'underlineBtn') btn.classList.add("btn-outline-dark");
            else btn.classList.add("btn-outline-secondary");
        }
    });

    const highlights = canvas.getObjects().filter(o => o.data_type === 'highlight' || o.data_type === 'underline');

    if (interactionMode === 'text') {
        document.body.classList.add("mode-text-select");
        canvas.isDrawingMode = false;
        canvas.discardActiveObject();
        highlights.forEach(o => o.set({selectable: false, evented: false}));
    } 
    else if (interactionMode === 'highlight') {
        document.body.classList.add("mode-highlight"); 
        const btn = document.getElementById("highlightBtn");
        btn.classList.remove("btn-outline-warning");
        btn.classList.add("active", "btn-warning");
        
        canvas.isDrawingMode = false;
        canvas.discardActiveObject();
        highlights.forEach(o => o.set({selectable: false, evented: false}));
    }
    else if (interactionMode === 'underline') {
        document.body.classList.add("mode-underline"); 
        const btn = document.getElementById("underlineBtn");
        btn.classList.remove("btn-outline-dark");
        btn.classList.add("active", "btn-dark");
        
        canvas.isDrawingMode = false;
        canvas.discardActiveObject();
        highlights.forEach(o => o.set({selectable: false, evented: false}));
    }
    else if (interactionMode === 'draw') {
        document.body.classList.add("mode-drawing");
        const btn = document.getElementById("drawBtn");
        btn.classList.remove("btn-outline-secondary");
        btn.classList.add("active", "btn-secondary");
        
        canvas.isDrawingMode = true;
        canvas.freeDrawingBrush = new fabric.PencilBrush(canvas);
        updateStyle('brush');
        highlights.forEach(o => o.set({selectable: false, evented: false}));
    }
    else if (interactionMode === 'object' || interactionMode === 'sticky') {
        document.body.classList.add("mode-object-edit");
        
        if(interactionMode === 'object') {
            const btn = document.getElementById("selectObjBtn");
            btn.classList.remove("btn-outline-primary");
            btn.classList.add("active", "btn-primary");
            highlights.forEach(o => o.set({selectable: true, evented: true}));
        }
        
        if(interactionMode === 'sticky') {
                const btn = document.getElementById("stickyBtn");
                btn.classList.remove("btn-outline-secondary");
                btn.classList.add("active", "btn-secondary");
        }
        canvas.isDrawingMode = false;
    }
    
    canvas.requestRenderAll();
}

function toggleHighlightMode() {
    interactionMode = (interactionMode === 'highlight') ? 'text' : 'highlight';
    updateModeUI();
}
function toggleUnderlineMode() {
    interactionMode = (interactionMode === 'underline') ? 'text' : 'underline';
    updateModeUI();
}
function toggleSelectObjectMode() {
    interactionMode = (interactionMode === 'object') ? 'text' : 'object';
    updateModeUI();
}
function toggleDrawMode() {
    interactionMode = (interactionMode === 'draw') ? 'text' : 'draw';
    updateModeUI();
}
function toggleStickyMode() {
    isStickyMode = !isStickyMode;
    interactionMode = isStickyMode ? 'sticky' : 'text';
    canvas.defaultCursor = isStickyMode ? 'crosshair' : 'default';
    updateModeUI();
}

function addText() {
    interactionMode = 'object'; 
    updateModeUI();
    const t = new fabric.IText("文字", { 
        left: 100, top: 100, fontSize: 20, 
        fill: document.getElementById("mainColor").value,
        fontFamily: document.getElementById("fontFamily").value,
        fontWeight: document.getElementById("boldBtn").classList.contains("active") ? 'bold' : 'normal'
    });
    canvas.add(t).setActiveObject(t);
    t.enterEditing();
    t.selectAll();
}

canvas.on('mouse:down', function(opt) {
    if (interactionMode === 'sticky' && !opt.target) {
        const p = canvas.getPointer(opt.e);
        const sticky = new fabric.Textbox("新便籤", {
            left: p.x, top: p.y, width: 80, fontSize: 11, fontFamily: 'Noto Sans TC',
            backgroundColor: '#ffda6a', padding: 6, data_type: 'sticky', 
            noteText: "", noteImage: null, hasControls: true, editable: false, 
            rx: 6, ry: 6, textAlign: 'center'
        });
        sticky.set('text', getPreviewLabel("", false));
        canvas.add(sticky).setActiveObject(sticky);
        interactionMode = 'object'; 
        isStickyMode = false;
        updateModeUI();
    }
});

canvas.on('mouse:dblclick', function(opt) {
    if (opt.target && opt.target.data_type === 'sticky') {
        currentNoteObj = opt.target;
        document.getElementById('noteTextContent').value = currentNoteObj.noteText || "";
        tempNoteImage = currentNoteObj.noteImage;
        if (tempNoteImage) {
            document.getElementById('noteImagePreview').src = tempNoteImage;
            document.getElementById('noteImagePreviewContainer').style.display = 'block';
        } else {
            removeNoteImage();
        }
        noteModal.show();
    }
});

function getPreviewLabel(str, hasImage) {
    let base = str ? (str.length > 8 ? str.substring(0, 8) + "..." : str) : "新便籤";
    return hasImage ? "📷 " + base : "🏷️ " + base;
}
canvas.on('mouse:over', function(e) {
    const obj = e.target;
    if (obj && obj.data_type === 'sticky') {
        previewTxt.innerText = obj.noteText || "無詳細內容";
        if (obj.noteImage) {
            previewImg.src = obj.noteImage;
            previewImg.style.display = 'block';
        } else {
            previewImg.style.display = 'none';
        }
        hoverBox.style.display = 'block';
    }
});
canvas.on('mouse:move', function(e) {
    if (hoverBox.style.display === 'block') {
        hoverBox.style.left = (e.e.clientX + 15) + 'px';
        hoverBox.style.top = (e.e.clientY + 15) + 'px';
    }
});
canvas.on('mouse:out', function() { hoverBox.style.display = 'none'; });

function updateStyle(type) {
    const color = document.getElementById("mainColor").value;
    const size = parseInt(document.getElementById("mainSize").value);
    const font = document.getElementById("fontFamily").value;
    const activeObjs = canvas.getActiveObjects();

    if (canvas.freeDrawingBrush) {
        const r = parseInt(color.slice(1,3), 16), g = parseInt(color.slice(3,5), 16), b = parseInt(color.slice(5,7), 16);
        canvas.freeDrawingBrush.color = `rgba(${r},${g},${b},0.6)`;
        canvas.freeDrawingBrush.width = size;
    }

    if (activeObjs.length > 0) {
        activeObjs.forEach(obj => {
            if((obj.data_type === 'highlight' || obj.data_type === 'underline') && type === 'color') {
                if(obj.data_type === 'highlight') obj.set('fill', hexToRgba(color, 0.5));
                else obj.set('fill', color);
            } 
            else if (type === 'color' || type === 'init') {
                if (obj.type === 'i-text' || obj.type === 'text') obj.set('fill', color);
                else if (obj.type === 'path') obj.set('stroke', `rgba(${parseInt(color.slice(1,3), 16)},${parseInt(color.slice(3,5), 16)},${parseInt(color.slice(5,7), 16)},0.6)`);
            }
            if (type === 'size' && obj.data_type !== 'highlight' && obj.data_type !== 'underline') {
                if (obj.type === 'path') obj.set('strokeWidth', size);
            }
            if (type === 'font') {
                if (obj.type === 'i-text' || obj.type === 'text') obj.set('fontFamily', font);
            }
        });
        canvas.requestRenderAll();
        saveCurrent();
    }
}

function toggleBold() { 
    const btn = document.getElementById("boldBtn");
    btn.classList.toggle("active");
    const isBold = btn.classList.contains("active");
    const activeObjs = canvas.getActiveObjects();
    if (activeObjs.length > 0) {
        activeObjs.forEach(obj => {
            if (obj.type === 'i-text' || obj.type === 'text') {
                obj.set('fontWeight', isBold ? 'bold' : 'normal');
            }
        });
        canvas.requestRenderAll();
        saveCurrent();
    }
}

function saveCurrent() {
    const objects = canvas.getObjects().filter(o => !o.isBackground);
    if (!pdfDataInfo.mods) pdfDataInfo.mods = {};
    pdfDataInfo.mods[pageNum - 1] = objects.map(o => {
        let data = o.toObject([
            'selectable', 'data_type', 'noteText', 'noteImage', 
            'fill', 'stroke', 'strokeWidth', 'opacity', 'scaleX', 'scaleY', 
            'text', 'fontSize', 'src', 'path', 'pathOffset', 'left', 'top', 
            'width', 'height', 'backgroundColor', 'fontFamily', 'fontWeight', 
            'rx', 'ry', 'globalCompositeOperation', 'selectedText'
        ]);
        
        if (o.type === 'path') {
                const matrix = o.calcTransformMatrix();
                data.abs_points = o.path.filter(p => p[0] === 'M' || p[0] === 'L').map(p => { 
                    return [
                        fabric.util.transformPoint({ x: p[1] - o.pathOffset.x, y: p[2] - o.pathOffset.y }, matrix).x, 
                        fabric.util.transformPoint({ x: p[1] - o.pathOffset.x, y: p[2] - o.pathOffset.y }, matrix).y
                    ]; 
                });
        }
        return data;
    });
    localStorage.setItem("currentPdfSession", JSON.stringify(pdfDataInfo));
}

function changePage(d) { renderPage(pageNum + d); }
function jumpToPage() { const p = parseInt(document.getElementById("jumpPage").value); renderPage(p); }      
function adjustZoom(delta) { 
    saveCurrent();
    scale = Math.max(0.5, scale + delta); 
    document.getElementById("zoomLevel").innerText = Math.round(scale * 100) + "%"; 
    renderPage(pageNum); 
}

function fitToWidth() { 
    const wrap = document.getElementById('wrap'); 
    if(pdfDoc) {
        pdfDoc.getPage(pageNum).then(p => {
                const vp = p.getViewport({scale: 1.0});
                scale = (wrap.clientWidth - 50) / vp.width;
                renderPage(pageNum);
        });
    }
}

function selectAll() {
    interactionMode = 'object';
    updateModeUI();
    canvas.discardActiveObject();
    const sel = new fabric.ActiveSelection(canvas.getObjects(), { canvas: canvas });
    canvas.setActiveObject(sel);
    canvas.requestRenderAll();
}

function deleteObj() { 
    const activeObjects = canvas.getActiveObjects();
    if (activeObjects.length) {
        canvas.discardActiveObject();
        activeObjects.forEach(function(object) { canvas.remove(object); });
        saveCurrent();
    }
}

async function download_save(btn, isDownload) {
    saveCurrent(); btn.innerHTML = '處理中...'; btn.disabled = true;
    try {
        const r = await fetch("/save", { 
            method: "POST", headers: { "Content-Type": "application/json" }, 
            body: JSON.stringify({ doc_id: pdfDataInfo.doc_id, pdf_name: pdfDataInfo.pdf_name, original_name: pdfDataInfo.original_name, all_modifications: pdfDataInfo.mods }) 
        });
        if (r.ok) {
            if (isDownload) { 
                const blob = await r.blob(), url = window.URL.createObjectURL(blob), a = document.createElement('a'); 
                a.href = url; a.download = pdfDataInfo.original_name.replace(".pdf","") + "_note.pdf"; a.click(); 
            } else alert("儲存成功");
        }
    } catch(e) { alert("出錯了"); } finally { btn.innerHTML = isDownload ? '下載' : '儲存'; btn.disabled = false; }
}

function save(btn) { download_save(btn, false); }
function download(btn) { download_save(btn, true); }

async function analyzeStructure() {
    try {
        const r = await fetch("/analyze_toc", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pdf_name: pdfDataInfo.pdf_name, toc_pages: document.getElementById("tocRange").value, offset: document.getElementById("pageOffset").value }) });
        const res = await r.json();
        const list = document.getElementById("resultList"); list.innerHTML = "";
        res.data.forEach(item => {
            const a = document.createElement("a"); a.className = "list-group-item list-group-item-action d-flex justify-content-between align-items-center";
            a.dataset.page = item.jump_page; a.onclick = () => renderPage(parseInt(a.dataset.page));
            a.innerHTML = `<span class="text-truncate">${item.title}</span><span class="badge bg-secondary">P.${item.page}</span>`;
            list.appendChild(a);
        });
    } catch(e) { alert("目錄解析錯誤"); }
}
function updateActiveToc(pageIdx) {
    document.querySelectorAll('.list-group-item').forEach(el => el.classList.remove('active'));
    const items = Array.from(document.querySelectorAll('.list-group-item'));
    let activeItem = null;
    for (let item of items) { if (parseInt(item.dataset.page) <= pageIdx) activeItem = item; else break; }
    if (activeItem) { activeItem.classList.add('active'); activeItem.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
}

document.addEventListener('keydown', e => { 
    if(e.key === 'Delete' && canvas.getActiveObject()) {
        const active = canvas.getActiveObject();
        if (!(active.isEditing)) deleteObj();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
        e.preventDefault(); selectAll();
    }
});

function handleNoteImgChange(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = e => {
            tempNoteImage = e.target.result;
            document.getElementById('noteImagePreview').src = tempNoteImage;
            document.getElementById('noteImagePreviewContainer').style.display = 'block';
        };
        reader.readAsDataURL(input.files[0]);
    }
}
function removeNoteImage() {
    tempNoteImage = null;
    document.getElementById('noteImgInput').value = "";
    document.getElementById('noteImagePreviewContainer').style.display = 'none';
}
function saveStickyContent() {
        if (currentNoteObj) {
        const val = document.getElementById('noteTextContent').value;
        currentNoteObj.set({ 
            text: getPreviewLabel(val, !!tempNoteImage), 
            noteText: val, noteImage: tempNoteImage 
        });
        noteModal.hide(); canvas.renderAll(); saveCurrent();
    }
}

document.getElementById("imgInput").onchange = function(e) { 
    const reader = new FileReader(); 
    reader.onload = f => fabric.Image.fromURL(f.target.result, img => { 
        img.scaleToWidth(200); 
        canvas.add(img).setActiveObject(img); 
        interactionMode = 'object'; updateModeUI();
    }); 
    reader.readAsDataURL(e.target.files[0]); 
};

async function addBlankPage() {
    if (!confirm(`確定要在第 ${currentPage + 1} 頁之後插入空白頁嗎？`)) return;
    saveCurrent(); isRefreshing = true;
    try {
        const r = await fetch("/add_blank_page", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doc_id: pdfDataInfo.doc_id, insert_after: currentPage, all_modifications: pdfDataInfo.mods })
        });
        const res = await r.json();
        if (res.success) {
            pdfDataInfo.total_pages = res.new_total_pages; pdfDataInfo.mods = res.mods;
            localStorage.setItem("currentPdfSession", JSON.stringify(pdfDataInfo));
            renderPage(currentPage + 1);
            alert("頁面插入成功！");
        }
    } catch(e) { alert("失敗"); } finally { isRefreshing = false; }
}

async function deleteCurrentPage() {
    if (pdfDataInfo.total_pages <= 1) { alert("無法刪除最後一頁"); return; }
    if (!confirm(`確定要刪除第 ${currentPage + 1} 頁嗎？`)) return;
    saveCurrent(); isRefreshing = true;
    try {
        const r = await fetch("/delete_page", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doc_id: pdfDataInfo.doc_id, page_idx: currentPage, all_modifications: pdfDataInfo.mods })
        });
        const res = await r.json();
        if (res.success) {
            pdfDataInfo.total_pages = res.new_total_pages; pdfDataInfo.mods = res.mods;
            localStorage.setItem("currentPdfSession", JSON.stringify(pdfDataInfo));
            renderPage(currentPage >= pdfDataInfo.total_pages ? pdfDataInfo.total_pages - 1 : currentPage);
            alert("頁面已刪除！");
        }
    } catch(e) { alert("失敗"); } finally { isRefreshing = false; }
}
