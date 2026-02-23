const canvas = new fabric.Canvas("c", { preserveObjectStacking: true });

fabric.Object.prototype.set({
    borderColor: '#999999',      // 外圍大框顏色
    cornerStrokeColor: '#999999',// 控制方塊邊框顏色
    cornerSize: 3,               // 方塊大小
    padding: 4,                  // 框框跟物件距離
    transparentCorners: false,
    cornerColor: '#ffffff', 
    borderDashArray: [3, 3], 
});

let pdfDoc = null, pdfDataInfo = null;
let pageNum = 1, scale = 1.0; 
let isStickyMode = false, currentNoteObj = null, tempNoteImage = null;
const noteModal = new bootstrap.Modal(document.getElementById('noteModal'));

let interactionMode = 'text'; // 'text', 'highlight', 'underline', 'draw', 'object', 'sticky'
let pendingSymbol = null;

const hoverBox = document.getElementById('hoverPreview');
const previewTxt = document.getElementById('previewText');
const previewImg = document.getElementById('previewImg');

let isPageTurning = false;
let draggingObj = null;

window.onload = async function() {
    const storedData = localStorage.getItem("currentPdfSession");
    if (!storedData) { alert("請先上傳檔案"); window.location.href = "/"; return; }
    pdfDataInfo = JSON.parse(storedData);
    document.getElementById("fileNameDisplay").innerText = pdfDataInfo.original_name;
    updateStyle('init');

    initSymbolPicker();

    const loadingTask = pdfjsLib.getDocument(`/get_pdf_content/${pdfDataInfo.doc_id}`);
    pdfDoc = await loadingTask.promise;
    pdfDataInfo.total_pages = pdfDoc.numPages;
    renderPage(pageNum);
    initScrollToTurnPage();
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

        textLayerDiv.style.setProperty('--scale-factor', scale); 

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
    const appendDraggingObj = () => {
        if (draggingObj) {
            canvas.add(draggingObj);
            canvas.setActiveObject(draggingObj);
            draggingObj = null;
            saveCurrent();
        }
        canvas.renderAll();
    };

    if (pdfDataInfo.mods && pdfDataInfo.mods[num-1]) {
        fabric.util.enlivenObjects(pdfDataInfo.mods[num-1], objs => {
            objs.forEach(o => {
                if(o.data_type === 'sticky') o.set({hasControls:true, editable:false});
                if(o.data_type === 'highlight' || o.data_type === 'underline') {
                    o.set({selectable: false, evented: false});
                }
                canvas.add(o);
            });
            appendDraggingObj(); // 在原有物件載入後，加上拖曳過來的物件
        });
    } else {
        appendDraggingObj(); // 如果這頁沒有舊筆記，直接加上拖曳過來的物件
    }

    document.getElementById("pageInfo").innerText = `${pageNum} / ${pdfDoc.numPages}`;
    document.getElementById("jumpPage").value = pageNum;
    updateActiveToc(pageNum);
    updateModeUI();
}

// ======= 畫布內物件拖曳跨頁的邏輯 =======
canvas.on('object:moving', function(e) {
    if (isPageTurning) return;
    
    const obj = e.target;
    // 取得游標相對於畫布的實體位置
    const pointer = canvas.getPointer(e.e);
    const buffer = -10; // 觸發換頁的邊緣緩衝值
    const logicalHeight = canvas.getHeight() / scale;

    if (pointer.y < buffer && pageNum > 1) {
        // 拖曳到上邊緣 -> 回到上一頁
        isPageTurning = true;
        canvas.remove(obj); // 1. 先從當前頁移除
        saveCurrent();      // 2. 儲存當前頁 (此時已不含該物件)
        
        // 3. 設定新頁面的放置位置 (底部)
        obj.top = logicalHeight - (obj.height * obj.scaleY) - 50; 
        draggingObj = obj;
        
        changePage(-1);     // 4. 觸發換頁
        setTimeout(() => isPageTurning = false, 800); // 防抖動冷卻
        
    } else if (pointer.y > logicalHeight - buffer && pageNum < pdfDoc.numPages) {
        // 拖曳到下邊緣 -> 前往下一頁
        isPageTurning = true;
        canvas.remove(obj);
        saveCurrent();
        
        // 設定新頁面的放置位置 (頂部)
        obj.top = 50; 
        draggingObj = obj;
        
        changePage(1);
        setTimeout(() => isPageTurning = false, 800);
    }
});

// ======= 新增：滾輪滑動偵測跨頁邏輯 =======
function initScrollToTurnPage() {
    const wrapElement = document.getElementById("wrap");
    let wheelTimeout;

    wrapElement.addEventListener("wheel", function(e) {
        if (isPageTurning) return;
        
        // 判斷是否滾動到最底或最頂 (給予 2px 誤差寬容值)
        const isAtBottom = wrapElement.scrollHeight - Math.ceil(wrapElement.scrollTop) <= wrapElement.clientHeight + 2;
        const isAtTop = wrapElement.scrollTop <= 2;

        if (e.deltaY > 0 && isAtBottom) { 
            // 往下滾動且到底部
            if (pageNum < pdfDoc.numPages) {
                e.preventDefault(); // 防止滾動回彈
                isPageTurning = true;
                changePage(1);
                clearTimeout(wheelTimeout);
                wheelTimeout = setTimeout(() => isPageTurning = false, 800);
            }
        } else if (e.deltaY < 0 && isAtTop) { 
            if (pageNum > 1) {
                e.preventDefault();
                isPageTurning = true;
                changePage(-1);
                clearTimeout(wheelTimeout);
                wheelTimeout = setTimeout(() => isPageTurning = false, 800);
            }
        }
    }, { passive: false });
}

// --- (螢光筆與底線) ---
document.addEventListener('mouseup', function() {
    const selection = window.getSelection();
    if (selection && selection.toString().trim() !== "") {
        setTimeout(() => {
            if (interactionMode === 'highlight') {
                highlightSelection(selection);
            } else if (interactionMode === 'underline') {
                underlineSelection(selection);
            }}, 10);
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
        
        const lineHeight = 1.5;
        const lineOffset = height * 0.18; 
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
            
            if(id === 'selectObjBtn') btn.classList.add("btn-outline-secondary");
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
        left: 100, top: 100, fontSize: 16, 
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
        const sticky = new fabric.Textbox("便籤", {
            left: p.x, top: p.y, width: 80, fontSize: 11, fontFamily: 'Noto Sans TC',
            backgroundColor: '#f7e099', padding: 6, data_type: 'sticky', 
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
    let base = str ? (str.length > 8 ? str.substring(0, 8) + "..." : str) : "便籤";
    return hasImage ? "📷" + base : "🏷️" + base;
}
canvas.on('mouse:over', function(e) {
    const obj = e.target;
    if (obj && obj.data_type === 'sticky') {
        previewTxt.innerText = obj.noteText || "無內容";
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
                if (obj.type === 'path') {
                    obj.set('strokeWidth', size);
                } 
                else if (obj.type === 'i-text' || obj.type === 'text') {
                    obj.set('fontSize', size); 
                }
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
    const pageKey = pageNum - 1;

    if (objects.length > 0) {
        pdfDataInfo.mods[pageKey] = objects.map(o => {
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
    } else {
        delete pdfDataInfo.mods[pageKey];
    }

    Object.keys(pdfDataInfo.mods).forEach(key => {
        const pageData = pdfDataInfo.mods[key];
        if (!pageData || (Array.isArray(pageData) && pageData.length === 0)) {
            delete pdfDataInfo.mods[key]; 
        }
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
            } 
            else {
                Swal.fire({
                    icon: 'success',
                    title: '儲存成功',
                    showConfirmButton: false, 
                    timer: 1500 
                });
            }
        }
    } 
    catch(e) { 
         Swal.fire({
            icon: 'error',
            title: '儲存失敗',
            showConfirmButton: false, 
            timer: 1500 
        });
    } 
    finally { 
        btn.innerHTML = isDownload ? '下載' : '儲存'; btn.disabled = false; 
    }
}

function save(btn) { download_save(btn, false); }
function download(btn) { download_save(btn, true); }

async function analyzeStructure(form) {
    const list = document.getElementById("resultList");
    const btn = form.querySelector('button');
    
    if (btn) btn.disabled = true;
    list.innerHTML = '<div class="p-4 text-center text-muted small bg-light">目錄解析中...</div>';

    const r = await fetch("/analyze_toc", { 
        method: "POST", 
        headers: { "Content-Type": "application/json" }, 
        body: JSON.stringify({ 
            pdf_name: pdfDataInfo.pdf_name, 
            toc_pages: "auto", 
            offset: "auto"
        }) 
    });
    
    const res = await r.json();
    
    if (res.data && res.data.length > 0) {
        list.innerHTML = res.data.map(item => `
            <a class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" 
               style="cursor:pointer;" 
               onclick="renderPage(${item.jump_page})">
               <span class="text-truncate">${item.title}</span>
               <span class="badge bg-secondary">P.${item.page}</span>
            </a>`).join('');
    } else {
        list.innerHTML = '<div class="p-4 text-center text-muted small bg-light">未偵測到目錄格式的文字</div>';
    }

    if (btn) btn.disabled = false;
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
    if (!confirm(`確定要在第 ${pageNum} 頁之後插入空白頁嗎？`)) return;
    saveCurrent(); isPageTurning = true; 
    try {
        const r = await fetch("/add_blank_page", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doc_id: pdfDataInfo.doc_id, insert_after: pageNum, all_modifications: pdfDataInfo.mods })
        });
        const res = await r.json();
        if (res.success) {
            pdfDataInfo.total_pages = res.new_total_pages; pdfDataInfo.mods = res.mods;
            localStorage.setItem("currentPdfSession", JSON.stringify(pdfDataInfo));
            renderPage(pageNum + 1);
            alert("頁面插入成功！");
        }
    } catch(e) { alert("失敗"); } finally { isPageTurning = false; }
}

async function deleteCurrentPage() {
    if (pdfDataInfo.total_pages <= 1) { alert("無法刪除最後一頁"); return; }
    if (!confirm(`確定要刪除第 ${pageNum} 頁嗎？`)) return;
    saveCurrent(); isPageTurning = true;
    try {
        const r = await fetch("/delete_page", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doc_id: pdfDataInfo.doc_id, page_idx: pageNum, all_modifications: pdfDataInfo.mods })
        });
        const res = await r.json();
        if (res.success) {
            pdfDataInfo.total_pages = res.new_total_pages; pdfDataInfo.mods = res.mods;
            localStorage.setItem("currentPdfSession", JSON.stringify(pdfDataInfo));
            renderPage(pageNum >= pdfDataInfo.total_pages ? pdfDataInfo.total_pages - 1 : pageNum);
            alert("頁面已刪除！");
        }
    } catch(e) { alert("失敗"); } finally { isPageTurning = false; }
}

function initSymbolPicker() {

    function getUnicodeRange(startHex, endHex) {
        let symbols = [];
        let start = parseInt(startHex, 16);
        let end = parseInt(endHex, 16);
        for (let i = start; i <= end; i++) {
            symbols.push(String.fromCodePoint(i));
        }
        return symbols;
    }

    // 符號字典
    const symbolDictionary = {
        "常用": ["±", "×", "÷", "√", "∞", "≈", "≠", "≡", "≤", "≥", "∠", "△", "°", "℃", "℉", "✓", "✗", "★", "☆"],
        "全形標點": getUnicodeRange('FF01', 'FF0F').concat(getUnicodeRange('FF1A', 'FF20'), getUnicodeRange('3000', '303F')),
        "數學運算": getUnicodeRange('2200', '22FF'),
        "箭頭符號": getUnicodeRange('2190', '21FF'),
        "幾何圖形": getUnicodeRange('25A0', '25FF'),
        "希臘字母": getUnicodeRange('0391', '03C9'),
        "特殊符號": getUnicodeRange('2600', '26FF'),
        "單位與數字": getUnicodeRange('2100', '214F').concat(getUnicodeRange('2460', '2473')),
        "製表符號": getUnicodeRange('2500', '257F')
    };

    const tabsContainer = document.getElementById('symbolTabs');
    const contentContainer = document.getElementById('symbolTabContent');

    if (!tabsContainer || !contentContainer) return;

    tabsContainer.innerHTML = '';
    contentContainer.innerHTML = '';

    let isFirst = true;
    let tabIndex = 0; // 確保ID不重複 
    for (const [category, symbols] of Object.entries(symbolDictionary)) {

        const tabId = `sym-tab-${tabIndex++}`; 
        const tabLi = document.createElement('li');
        tabLi.className = 'nav-item';
        tabLi.role = 'presentation';
        tabLi.innerHTML = `
            <button class="nav-link px-2 py-1 ${isFirst ? 'active' : ''}" 
                    data-bs-toggle="pill" data-bs-target="#${tabId}" 
                    type="button" role="tab" aria-selected="${isFirst}">
                ${category}
            </button>
        `;
        tabsContainer.appendChild(tabLi);

        const paneDiv = document.createElement('div');
        paneDiv.className = `tab-pane fade ${isFirst ? 'show active' : ''}`;
        paneDiv.id = tabId;
        paneDiv.role = 'tabpanel';

        let gridHtml = '<div class="symbol-grid-auto">';
        symbols.forEach(sym => {
            gridHtml += `<button type="button" class="symbol-btn-auto" onclick="insertSymbol(this.innerText)">${sym}</button>`;
        });
        gridHtml += '</div>';

        paneDiv.innerHTML = gridHtml;
        contentContainer.appendChild(paneDiv);

        isFirst = false;
    }
}
function insertSymbol(symbol) {
    const activeObj = canvas.getActiveObject();

    // 當有選取文字
    if (activeObj && (activeObj.type === 'i-text' || activeObj.type === 'text')) {
        if (activeObj.isEditing) {
            const start = activeObj.selectionStart;
            const end = activeObj.selectionEnd;
            const currentText = activeObj.text;
            const newText = currentText.slice(0, start) + symbol + currentText.slice(end);
            activeObj.set('text', newText);
            activeObj.selectionStart = start + symbol.length;
            activeObj.selectionEnd = start + symbol.length;
            
            if (activeObj.hiddenTextarea) {
                activeObj.hiddenTextarea.value = newText;
                activeObj.hiddenTextarea.selectionStart = activeObj.selectionStart;
                activeObj.hiddenTextarea.selectionEnd = activeObj.selectionEnd;
            }
            
            activeObj.initDimensions();
            activeObj.setCoords();
        } else {
            activeObj.set('text', activeObj.text + symbol);
        }
        canvas.requestRenderAll();
        saveCurrent();
    } 
    // 沒有選取任何東西，直接產生新文字框
    else {
        interactionMode = 'object'; 
        updateModeUI();

        const mainColor = document.getElementById("mainColor").value;
        const mainSize = parseInt(document.getElementById("mainSize").value) || 24;
        const fontFamily = document.getElementById("fontFamily").value;
        const isBold = document.getElementById("boldBtn").classList.contains("active");

        // 建立可編輯的IText
        const t = new fabric.IText(symbol, { 
            left: 100,
            top: 100, 
            fontSize: mainSize, 
            fill: mainColor,
            fontFamily: fontFamily,
            fontWeight: isBold ? 'bold' : 'normal'
        });

        canvas.add(t).setActiveObject(t);
        t.enterEditing();
        t.selectAll();        
        canvas.requestRenderAll();
        saveCurrent();
    }
}

async function openEquationEditor(existingLatex = "") {
    const { value: latex } = await Swal.fire({
        title: '編輯方程式',
        width: 650,
        html: `
            <math-field id="mf" style="
                width:100%;
                min-height:60px;
                font-size:24px;
                border:1px solid #ccc;
                border-radius:6px;
                padding:10px;
            ">${existingLatex}</math-field>

            <div style="margin-top:15px; padding:10px; border:1px solid #eee;">
                <div id="preview"></div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: '插入',
        didOpen: () => {
            const mf = document.getElementById("mf");
            const preview = document.getElementById("preview");

            // ❗ 關閉虛擬鍵盤（你之前說不要）
            mf.mathVirtualKeyboardPolicy = "off";

            const updatePreview = async () => {
                const val = mf.value.trim();
                if (!val) return;

                preview.innerHTML = `\\(${val}\\)`;
                await MathJax.typesetPromise([preview]);
            };

            mf.addEventListener("input", updatePreview);
            updatePreview();
        }
    });

    return latex;
}async function insertEquation(existingObj = null) {
    const existingLatex = existingObj?.latex || "";

    const latex = await openEquationEditor(existingLatex);
    if (!latex) return;

    try {
        // 建立隱藏容器
        const container = document.createElement("div");
        container.style.position = "absolute";
        container.style.opacity = 0;
        container.innerHTML = `\\(${latex}\\)`;
        document.body.appendChild(container);

        await MathJax.typesetPromise([container]);

        const svg = container.querySelector("svg");
        if (!svg) throw new Error("SVG 生成失敗");

        const svgData = new XMLSerializer().serializeToString(svg);
        const url = URL.createObjectURL(
            new Blob([svgData], { type: "image/svg+xml" })
        );

        // 如果是編輯 → 移除舊的
        if (existingObj) canvas.remove(existingObj);

        fabric.Image.fromURL(url, (img) => {
            img.set({
                left: existingObj ? existingObj.left : 150,
                top: existingObj ? existingObj.top : 150,
                data_type: 'equation',
                latex: latex
            });

            canvas.add(img);
            canvas.setActiveObject(img);
            canvas.renderAll();
            saveCurrent();

            URL.revokeObjectURL(url);
            document.body.removeChild(container);
        });

    } catch (err) {
        console.error(err);
        Swal.fire("錯誤", "公式解析失敗", "error");
    }
}