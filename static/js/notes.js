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
            const res = await fetch("/notes/action", {
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

let allSelected = false;
document.addEventListener('DOMContentLoaded', () => {
    const selectAllBtn = document.getElementById('selectAllBtn');
    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', function() {
            allSelected = !allSelected;
            const checkboxes = document.querySelectorAll('.doc-checkbox');
            checkboxes.forEach(cb => cb.checked = allSelected);
            this.textContent = allSelected ? '取消全選' : '全選';
        });
    }
});

function submitBatch(action) {
    const checkboxes = document.querySelectorAll('.doc-checkbox:checked');
    if (checkboxes.length === 0) {
        Swal.fire({
            icon: 'warning',
            title: '未選取任何紀錄',
            showConfirmButton: false,
            timer: 2000
        });
        return;
    }

    if (action === 'batch_delete') {
        Swal.fire({
            title: '確定要刪除選取的紀錄嗎？',
            text: '刪除後將無法復原。',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#6c757d',
            confirmButtonText: '確定刪除',
            cancelButtonText: '取消'
        }).then((result) => {
            if (result.isConfirmed) {
                executeBatchRequest(action, checkboxes);
            }
        });
    } else {
        executeBatchRequest(action, checkboxes);
    }
}

function executeBatchRequest(action, checkboxes) {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/notes/action';
    
    const actionInput = document.createElement('input');
    actionInput.type = 'hidden';
    actionInput.name = 'action';
    actionInput.value = action;
    form.appendChild(actionInput);

    checkboxes.forEach(cb => {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'doc_ids';
        input.value = cb.value;
        form.appendChild(input);
    });

    document.body.appendChild(form);
    form.submit();
}