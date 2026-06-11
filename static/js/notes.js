async function runMigrate() {
    let form = document.getElementById("migrateForm");
    let formData = new FormData(form);
    
    // 檢查必填
    if(!form.checkValidity()){
        form.reportValidity();
        return;
    }

    const submitBtn = document.getElementById("migrateSubmitBtn");
    submitBtn.disabled = true;

    try {
        let res = await fetch("/annotation/migrate_pdf", {
            method: "POST", 
            body: formData
        });
        let data = await res.json();

        if(data.status === "success"){
            // 重新整理以顯示新的一筆 PROCESSING 紀錄
            location.reload();
        } else {
            Swal.fire({ icon: "error", title: "轉移失敗", text: data.message });
            submitBtn.disabled = false;
        }
    } catch(e) {
        Swal.fire({ icon: "error", title: "系統錯誤", text: "請檢查伺服器連線" });
        submitBtn.disabled = false;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const processingBadges = document.querySelectorAll('.processing-badge');
    
    processingBadges.forEach(badge => {
        const transferId = badge.getAttribute('data-transfer-id');
        if (!transferId) return;

        const interval = setInterval(async () => {
            try {
                let res = await fetch(`/notes/status/${transferId}`);
                let data = await res.json();

                if (data.success && data.ResultName !== 'PROCESSING') {
                    clearInterval(interval);
                    
                    const isSuccess = data.ResultName !== 'ERROR';
                    
                    const container = document.getElementById(`status-container-${transferId}`);
                    if (container) {
                        container.innerHTML = isSuccess ? 
                            `<span class="badge bg-success bg-opacity-10 text-success border border-success border-opacity-10 fw-normal">success</span>` : 
                            `<span class="badge bg-danger bg-opacity-10 text-danger border border-danger border-opacity-10 fw-normal">error</span>`;
                    }
                    
                    const downloadBtn = document.getElementById(`download-btn-${transferId}`);
                    if (downloadBtn && isSuccess) {
                        downloadBtn.classList.remove('disabled');
                        downloadBtn.href = `/download_pdf/${data.ResultName}`;
                    }

                    const deleteBtn = document.getElementById(`delete-btn-${transferId}`);
                    if (deleteBtn) deleteBtn.classList.remove('disabled');

                    // Show Notification and Reload
                    if (isSuccess) {
                        if (typeof addNotif === 'function') {
                            addNotif('success', `一筆筆記轉移已成功完成`);
                        }
                        setTimeout(() => location.reload(), 500);
                    } else {
                        Swal.fire({
                            icon: 'error',
                            title: '轉移失敗',
                            text: '背景轉移時發生錯誤或無法解析此文件。',
                            confirmButtonColor: '#0dcaf0'
                        }).then(() => {
                            if (typeof addNotif === 'function') {
                                addNotif('error', `一筆筆記轉移失敗`);
                            }
                            location.reload();
                        });
                    }
                }
            } catch (e) {
                console.error("Status Polling Error for ID:", transferId, e);
            }
        }, 3000); // 每 3 秒輪詢一次
    });
});

async function deleteNote(transferId) {
    const result = await Swal.fire({
        title: '確定要刪除嗎？',
        text: "刪除後此 PDF 檔案將永久移除！",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '確定刪除',
        cancelButtonText: '取消'
    });

    if (result.isConfirmed) {
        try {
            const res = await fetch("/notes_tool", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "delete", transfer_id: transferId })
            });
            const data = await res.json();

            if (data.success) {
                Swal.fire({ 
                    icon: 'success', 
                    title: '已刪除', 
                    timer: 1000, 
                    showConfirmButton: false 
                }).then(() => {
                    location.reload();
                });
            } else {
                Swal.fire('錯誤', data.message, 'error');
            }
        } catch (e) {
            Swal.fire('錯誤', '系統連線異常', 'error');
        }
    }
}