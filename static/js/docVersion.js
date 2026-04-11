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
