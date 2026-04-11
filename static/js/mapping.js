/**
 * 執行版本比對 (AJAX 模式)
 */
async function runMapping() {
    let form = document.getElementById("MappingForm");
    let formData = new FormData(form);
    
    // 1. 顯示轉圈圈
    $("body").loading({message: "版本比對中..."});

    try {
        // 2. 發送請求到後端
        let res = await fetch("/mapping/doc_mapping", {
            method: "POST", 
            body: formData
        });
        let data = await res.json();
        
        // 3. 關閉轉圈圈
        $("body").loading("stop");

        if(data.status === "success"){
            // 4. 顯示成功彈窗
            Swal.fire({
                icon: "success",
                title: "比對完成",
                text: data.message,
                confirmButtonText: "確定"
            }).then(() => {
                // 5. 點擊確定後才重新整理，讓新紀錄出現在下方表格
                location.reload();
            });
        } else {
            Swal.fire({ icon: "error", title: "比對失敗", text: data.message });
        }
    } catch(e) {
        $("body").loading("stop");
        Swal.fire({ icon: "error", title: "系統錯誤", text: "伺服器運算逾時或連線中斷" });
    }
}

/**
 * 1. 刪除比對紀錄
 */
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

/**
 * 2. 切換發布狀態
 */
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
        }
    } catch (e) {
        checkbox.checked = !checkbox.checked;
        Swal.fire('錯誤', '伺服器無回應', 'error');
    }
}