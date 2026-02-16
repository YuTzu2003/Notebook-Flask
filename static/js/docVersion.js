const flashMessages = JSON.parse('{{ get_flashed_messages(with_categories=true)|tojson|safe }}');

if (flashMessages.length > 0) {
    flashMessages.forEach(([category, message]) => {
        Swal.fire({
            icon: category === 'success' ? 'success' : 'error',
            title: message,
            showConfirmButton: false,
            timer: 2000
        });
    });
}

var editModal = document.getElementById('editModal')
editModal.addEventListener('show.bs.modal', function (event) {
    var button = event.relatedTarget
    document.getElementById('modal_id').value = button.getAttribute('data-id')
    document.getElementById('modal_version').value = button.getAttribute('data-version')
    document.getElementById('modal_author').value = button.getAttribute('data-author')
})
