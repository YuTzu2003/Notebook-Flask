document.addEventListener("DOMContentLoaded", function() {
    var editModal = document.getElementById('editModal');
    if (editModal) {
        editModal.addEventListener('show.bs.modal', function (event) {
            var button = event.relatedTarget;
            
            var filename = button.getAttribute('data-filename');
            // 如果檔名以 .pdf 結尾 (不分大小寫)，就把最後 4 個字元切掉
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
