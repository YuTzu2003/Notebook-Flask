/**
 * PDF Version Mapping Module
 * Handles form submission, background polling, and record management.
 */

// ==========================================
// 1. Core Mapping Operations
// ==========================================

/**
 * Submits the mapping form and starts the background comparison process.
 */
async function runMapping() {
    const form = document.getElementById("MappingForm");
    const formData = new FormData(form);
    const submitBtn = document.querySelector("#MappingForm button[type='submit']");
    const originalText = submitBtn.innerHTML;
    
    // Set UI to loading state
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>處理中...';
    submitBtn.disabled = true;

    try {
        const res = await fetch("/mapping/doc_mapping", {
            method: "POST", 
            body: formData
        });
        const data = await res.json();

        if (data.status === "success") {
            // Reload to display the new "PROCESSING" row
            location.reload();
        } else {
            Swal.fire({ icon: "error", title: "比對失敗", text: data.message });
            resetButton(submitBtn, originalText);
        }
    } catch (e) {
        console.error("Mapping Error:", e);
        Swal.fire({ icon: "error", title: "系統錯誤", text: "系統逾時或連線中斷" });
        resetButton(submitBtn, originalText);
    }
}

/**
 * Helper to reset the submit button state.
 */
function resetButton(btn, originalText) {
    btn.innerHTML = originalText;
    btn.disabled = false;
}

// ==========================================
// 2. Record Management Actions
// ==========================================

/**
 * Deletes a specific mapping record and its associated CSV file.
 * @param {string|number} recordId - The ID of the record to delete.
 */
async function deleteMappingRecord(recordId) {
    const result = await Swal.fire({
        title: '確定要刪除嗎？',
        text: "這將會永久刪除此比對紀錄及其結果 CSV 檔案！",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '確定刪除',
        cancelButtonText: '取消'
    });

    if (!result.isConfirmed) return;

    try {
        const res = await fetch("/mapping_tool", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "delete", record_id: recordId })
        });
        const data = await res.json();
        
        if (data.success) {
            Swal.fire({ icon: 'success', title: '已刪除', timer: 1000, showConfirmButton: false })
                .then(() => location.reload());
        } else {
            Swal.fire('錯誤', data.message, 'error');
        }
    } catch (e) {
        console.error("Delete Error:", e);
        Swal.fire('錯誤', '系統連線異常', 'error');
    }
}

/**
 * Toggles the publish status of a mapping record.
 * @param {string|number} recordId - The ID of the record.
 * @param {HTMLInputElement} checkbox - The checkbox DOM element triggering the change.
 */
async function toggleMappingPublish(recordId, checkbox) {
    const isPublish = checkbox.checked ? 1 : 0;
    
    try {
        const res = await fetch("/mapping_tool", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "toggle_publish", record_id: recordId, publish: isPublish })
        });
        const data = await res.json();
        
        if (!data.success) {
            Swal.fire('錯誤', '更新失敗', 'error');
            checkbox.checked = !checkbox.checked; // Revert switch state
        } else {
            // Update the UI label text and color dynamically
            const label = document.getElementById("publish-label-" + recordId);
            if (label) {
                if (isPublish) {
                    label.textContent = "發布中";
                    label.classList.remove("text-secondary");
                    label.classList.add("text-primary-emphasis"); // Match UI theme
                } else {
                    label.textContent = "未發布";
                    label.classList.remove("text-primary-emphasis");
                    label.classList.add("text-secondary");
                }
            }
        }
    } catch (e) {
        console.error("Toggle Publish Error:", e);
        checkbox.checked = !checkbox.checked; // Revert switch state
        Swal.fire('錯誤', '伺服器無回應', 'error');
    }
}

// ==========================================
// 3. Background Polling Service
// ==========================================

/**
 * Automatically polls the server for status updates on records 
 * that are currently in the 'PROCESSING' state.
 */
document.addEventListener("DOMContentLoaded", function() {
    const processingBadges = document.querySelectorAll('.processing-badge');
    
    processingBadges.forEach(badge => {
        const recordId = badge.getAttribute('data-id');
        if (!recordId) return;
        
        const intervalId = setInterval(async () => {
            try {
                const res = await fetch(`/mapping/status/${recordId}`);
                const data = await res.json();
                
                // If processing is finished (Status is determined and DiffPages is no longer PROCESSING)
                if (data.success && data.DiffPages !== 'PROCESSING') {
                    clearInterval(intervalId);
                    
                    // 1. Update the status badge HTML
                    const newHtml = data.Status ? 
                        `<span id="status-badge-${recordId}" class="badge bg-success bg-opacity-10 text-success border border-success border-opacity-10 fw-normal">success</span>` : 
                        `<span id="status-badge-${recordId}" class="badge bg-danger bg-opacity-10 text-danger border border-danger border-opacity-10 fw-normal">error</span>`;
                    badge.outerHTML = newHtml;
                    
                    // 2. Unlock the Action Buttons
                    const detailBtn = document.getElementById(`detail-btn-${recordId}`);
                    if (detailBtn) detailBtn.disabled = false;
                    
                    const deleteBtn = document.getElementById(`delete-btn-${recordId}`);
                    if (deleteBtn) deleteBtn.disabled = false;
                    
                    // 3. Unlock Publish Switch and Update UI State (Only if successful)
                    const publishSwitch = document.getElementById(`publish-switch-${recordId}`);
                    if (publishSwitch && data.Status) { 
                        publishSwitch.disabled = false;
                        publishSwitch.checked = true;
                        
                        const label = document.getElementById(`publish-label-${recordId}`);
                        if (label) {
                            label.textContent = "發布中";
                            label.classList.remove("text-secondary");
                            label.classList.add("text-primary-emphasis");
                        }
                    }
                    
                    // 4. Show Notification
                    if (data.Status) {
                        Swal.fire({
                            toast: true,
                            position: 'top-end',
                            icon: 'success',
                            title: '比對已完成',
                            showConfirmButton: false,
                            timer: 3000,
                            timerProgressBar: true
                        }).then(() => {
                            location.reload();
                        });
                    } else {
                        // Error should be a prominent alert, not just a toast, to show information
                        let errorMsg = data.DiffPages === 'ERROR' ? '背景比對時發生系統錯誤，請聯絡管理員。' : '比對過程遭遇問題或無法解析此文件。';
                        Swal.fire({
                            icon: 'error',
                            title: '比對失敗',
                            text: errorMsg,
                            confirmButtonColor: '#0dcaf0'
                        }).then(() => {
                            location.reload();
                        });
                    }
                }
            } catch (e) {
                console.error("Status Polling Error for ID:", recordId, e);
            }
        }, 3000); // Poll every 3 seconds
    });
});