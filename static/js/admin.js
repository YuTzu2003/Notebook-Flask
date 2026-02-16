const userModal = new bootstrap.Modal(document.getElementById('userModal'));

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

// 儲存
function saveUser() {
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

    if (!data.user_id || !data.name) {
        alert("請填寫編號與姓名！");
        return;
    }

    const saveBtn = document.querySelector('#userModal .btn-dark');
    const originalText = saveBtn.innerText;
    saveBtn.disabled = true;
    saveBtn.innerText = "處理中...";

    fetch('/admin/manage_user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(res => res.json())
    .then(result => {
        if (result.success) {
            location.reload(); 
        } else {
            alert("操作失敗：" + (result.message || "未知錯誤"));
            saveBtn.disabled = false;
            saveBtn.innerText = originalText;
        }
    })
    .catch(err => {
        console.error(err);
        alert("發生錯誤");
        saveBtn.disabled = false;
        saveBtn.innerText = originalText;
    });
}

// 刪除
function deleteUser(guid, displayId) {
    if (!confirm(`確定要刪除此編號 ${displayId}？`)) return;

    const data = {
        action: 'delete',
        id: guid 
    };

    fetch('/admin/manage_user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(res => res.json())
    .then(result => {
        if (result.success) {
            location.reload();
        } else {
            alert("刪除失敗：" + result.message);
        }
    })
    .catch(err => console.error(err));
}
