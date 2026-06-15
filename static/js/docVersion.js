function confirmDelete(event, formElement) {
    event.preventDefault(); 
    Swal.fire({
        title: '確定要刪除這份文件嗎？',
        text: "刪除後此檔案將永久移除！",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: '確定刪除',
        cancelButtonText: '取消'
    }).then((result) => {
        if (result.isConfirmed) {
            formElement.submit();
        }
    });
}

document.addEventListener("DOMContentLoaded", function() {
    var editModal = document.getElementById('editModal');
    if (editModal) {
        editModal.addEventListener('show.bs.modal', function (event) {
            var button = event.relatedTarget;
            
            var filename = button.getAttribute('data-filename');

            if (filename.toLowerCase().endsWith('.pdf')) {
                filename = filename.slice(0, -4); 
            }
            
            document.getElementById('modal_id').value = button.getAttribute('data-id');
            document.getElementById('modal_filename').value = filename; // 塞入沒有副檔名的檔名
            document.getElementById('modal_version').value = button.getAttribute('data-version');
            document.getElementById('modal_author').value = button.getAttribute('data-author');
        });
    }
});

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
            title: '未選取任何檔案',
            showConfirmButton: false,
            timer: 2000
        });
        return;
    }

    if (action === 'batch_delete') {
        Swal.fire({
            title: '確定要刪除選取的檔案嗎？',
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
    form.action = '/docVersion_tool/' + action;
    
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
