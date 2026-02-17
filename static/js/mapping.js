$('#MappingForm').on('submit', function () {
    if (this.checkValidity()) {
        $('body').loading({ message: '處理中...' });
        const btn = $(this).find('button[type="submit"]');
        btn.html('<span class="spinner-border spinner-border-sm me-2"></span>處理中');
        btn.prop('disabled', true);
    }
});

function togglePublish(recordId, checkbox) {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = "/mapping/action";

    form.innerHTML = `
        <input type="hidden" name="action" value="toggle_publish">
        <input type="hidden" name="record_id" value="${recordId}">
        <input type="hidden" name="publish" value="${checkbox.checked ? 1 : 0}">
    `;
    document.body.appendChild(form);
    form.submit();
}
