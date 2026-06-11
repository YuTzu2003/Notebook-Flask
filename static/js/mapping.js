async function runMapping() {
    let form = document.getElementById("MappingForm");
    let formData = new FormData(form);
    $("body").loading({message: "版本比對中..."});

    try {
        let res = await fetch("/mapping/doc_mapping", {method: "POST", body: formData});
        let data = await res.json();
        $("body").loading("stop");

        if(data.status === "success"){
            Swal.fire({
                icon: "success",
                title: "比對完成",
                text: data.message,
                confirmButtonText: "確定"
            }).then(() => {
                location.reload();
            });
        } else {
            Swal.fire({ icon: "error", title: "比對失敗", text: data.message });
        }
    } catch(e) {
        $("body").loading("stop");
        Swal.fire({ icon: "error", title: "系統錯誤", text: "系統逾時或連線中斷" });
    }
}

async function deleteMappingRecord(recordId) {
    const result = await Swal.fire({
        title: '確定要刪除嗎？',
        text: "這將會永久刪除此比對紀錄及其結果 CSV 檔案！",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '確定刪除',
        cancelButtonText: '取消'
    });

    if (result.isConfirmed) {
        try {
            const res = await fetch("/mapping_tool", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "delete", record_id: recordId })
            });
            const data = await res.json();
            if (data.success) {
                Swal.fire({ icon: 'success', title: '已刪除', timer: 1000, showConfirmButton: false })
                    .then(() => location.reload());
            } else {
                Swal.fire('錯誤', data.message, 'error');
            }
        } catch (e) {
            console.error(e);
            Swal.fire('錯誤', '系統連線異常', 'error');
        }
    }
}

async function toggleMappingPublish(recordId, checkbox) {
    const isPublish = checkbox.checked ? 1 : 0;
    try {
        const res = await fetch("/mapping_tool", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "toggle_publish", record_id: recordId, publish: isPublish })
        });
        const data = await res.json();
        if (!data.success) {
            Swal.fire('錯誤', '更新失敗', 'error');
            checkbox.checked = !checkbox.checked;
        } else {
            const label = document.getElementById("publish-label-" + recordId);
            if (label) {
                if (isPublish) {
                    label.textContent = "發布中";
                    label.classList.remove("text-secondary");
                    label.classList.add("text-success");
                } else {
                    label.textContent = "未發布";
                    label.classList.remove("text-success");
                    label.classList.add("text-secondary");
                }
            }
        }
    } catch (e) {
        checkbox.checked = !checkbox.checked;
        Swal.fire('錯誤', '伺服器無回應', 'error');
    }
}