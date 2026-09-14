let userModal;

document.addEventListener('DOMContentLoaded', function() {
    const modalElem = document.getElementById('userModal');
    if (modalElem) {
        userModal = new bootstrap.Modal(modalElem);
    }
});

function editUser(btnElement) {
    const userData = JSON.parse(btnElement.getAttribute('data-user'));
    openModal('edit', userData);
}

// 開啟 Modal
function openModal(mode, userData = null) {
    const title = document.getElementById('modalTitle');
    const actionType = document.getElementById('actionType');
    const guidInput = document.getElementById('hiddenGuid');
    const idInput = document.getElementById('userId');
    const nameInput = document.getElementById('userName');
    const pwdInput = document.getElementById('userPassword');
    const posInput = document.getElementById('userPosition');
    const locInput = document.getElementById('userLocation');
    const passwordHelp = document.getElementById('passwordHelp');

    pwdInput.value = '';

    if (mode === 'edit' && userData) {
        title.innerText = "編輯帳號";
        actionType.value = "edit";

        guidInput.value = userData.ID;      // GUID
        idInput.value = userData.UserID;    // UserID
        idInput.readOnly = false; 
        
        passwordHelp.style.display = 'block';

        nameInput.value = userData.Name;
        posInput.value = userData.Position || 'Staff';
        locInput.value = userData.Location || '';
    } else {
        title.innerText = "新增帳號";
        actionType.value = "add";

        guidInput.value = '';
        idInput.value = '';
        idInput.readOnly = false;                
        passwordHelp.style.display = 'none';

        nameInput.value = '';
        posInput.value = 'Staff';
        locInput.value = '';
    }
    userModal.show();
}

function showAdminMessage(icon, title, text = '') {
    Swal.fire({
        icon,
        title,
        text,
        confirmButtonText: '確定',
        confirmButtonColor: '#212529'
    });
}

// 儲存
async function saveUser() {
    const action = document.getElementById('actionType').value;
    
    const data = {
        action: action,
        id: document.getElementById('hiddenGuid').value,
        user_id: document.getElementById('userId').value,
        name: document.getElementById('userName').value,
        password: document.getElementById('userPassword').value,
        position: document.getElementById('userPosition').value,
        location: document.getElementById('userLocation').value
    };

    if (!data.user_id || !data.name || (action === 'add' && !data.password)) {
        showAdminMessage('warning', '請完整填寫必要欄位', action === 'add' ? '新增使用者時，編號、姓名與密碼皆為必填。' : '請填寫編號與姓名。');
        return;
    }

    const saveBtn = document.querySelector('#userModal .btn-dark');
    const originalText = saveBtn.innerText;
    saveBtn.disabled = true;
    saveBtn.innerText = "儲存中…";

    try {
        const response = await fetch('/admin/manage_user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.success) {
            location.reload(); 
        } else {
            showAdminMessage('error', '操作失敗', result.message || '請稍後再試。');
        }
    } catch (err) {
        console.error(err);
        showAdminMessage('error', '系統連線失敗', '請確認網路後再試一次。');
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerText = originalText;
    }
}

// 刪除
async function deleteUser(guid, displayId) {
    const confirmation = await Swal.fire({
        icon: 'warning',
        title: '確定刪除使用者？',
        text: `帳號：${displayId}，刪除後將無法復原。`,
        showCancelButton: true,
        confirmButtonText: '刪除',
        cancelButtonText: '取消',
        confirmButtonColor: '#b02a37'
    });
    if (!confirmation.isConfirmed) return;

    const data = {
        action: 'delete',
        id: guid 
    };

    try {
        const response = await fetch('/admin/manage_user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.success) {
            location.reload();
        } else {
            showAdminMessage('error', '刪除失敗', result.message || '請稍後再試。');
        }
    } catch (err) {
        console.error(err);
        showAdminMessage('error', '系統連線失敗', '請確認網路後再試一次。');
    }
}

