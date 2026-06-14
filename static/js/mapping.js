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
    btn.disabled = false;
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
