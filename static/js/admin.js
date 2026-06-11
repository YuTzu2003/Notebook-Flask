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
    saveBtn.innerText = "process...";

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

// 取得登入紀錄並渲染
async function fetchLoginLogs() {
    const container = document.getElementById("loginLogsContainer");
    container.innerHTML = '<div class="p-5 text-center text-muted"><div class="spinner-border spinner-border-sm me-2"></div>正在載入紀錄...</div>';
    
    try {
        const res = await fetch("/admin/login_logs");
        const data = await res.json();
        
        if (data.success && data.logs && data.logs.length > 0) {
            let html = "";
            data.logs.forEach(log => {
                const isSuccess = log.status === "Success";
                const icon = isSuccess ? "bi-check-circle-fill text-success" : "bi-x-circle-fill text-danger";
                const bg = isSuccess ? "bg-success bg-opacity-10 text-success" : "bg-danger bg-opacity-10 text-danger";
                
                html += `
                    <div class="list-group-item p-3 border-bottom border-light">
                        <div class="d-flex align-items-center mb-1">
                            <i class="bi ${icon} me-2 fs-5"></i>
                            <strong class="text-dark">${log.emp_id}</strong>
                            <span class="ms-auto text-muted small">${log.timestamp}</span>
                        </div>
                        <div class="d-flex align-items-center ms-4 ps-1 text-muted small">
                            <span class="badge ${bg} me-2 border-0 fw-normal">${log.message}</span>
                            <span>IP: ${log.ip}</span>
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html;
        } else {
            container.innerHTML = '<div class="p-5 text-center text-muted">目前沒有任何登入紀錄</div>';
        }
    } catch (e) {
        console.error("Fetch logs error:", e);
        container.innerHTML = '<div class="p-5 text-center text-danger">載入失敗，請稍後再試</div>';
    }
}
