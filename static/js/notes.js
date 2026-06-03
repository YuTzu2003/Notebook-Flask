async function runMigrate() {
    let form = document.getElementById("migrateForm");
    let formData = new FormData(form);
    
    $("body").loading({message: "筆記轉移中..."});

    try {
        let res = await fetch("/annotation/migrate_pdf", {
            method: "POST", 
            body: formData
        });
        let data = await res.json();
        $("body").loading("stop");

        if(data.status === "success"){
            Swal.fire({
                icon: "success",
                title: "轉移完成",
                text: "筆記已轉移成功！您可以立即下載檔案，或稍後在下方的紀錄區下載。",
                showCancelButton: true,
                confirmButtonText: "立即下載",
                cancelButtonText: "確定",
                confirmButtonColor: "#2563eb", // 改用新的藍色主題
                cancelButtonColor: "#64748b"   // 灰色
            }).then((result) => {
                if (result.isConfirmed) {
                    window.location.href = `/download_pdf/${data.filename}`;
                    setTimeout(() => { location.reload(); }, 1500); // 稍微加長一點時間讓下載開始
                } else {
                    location.reload();
                }
            });
        } else {
            Swal.fire({ icon: "error", title: "轉移失敗", text: data.message });
        }
    } catch(e) {
        $("body").loading("stop");
        Swal.fire({ icon: "error", title: "系統錯誤", text: "請檢查伺服器連線" });
    }
}

async function deleteNote(transferId) {
    const result = await Swal.fire({
        title: '確定要刪除嗎？',
        text: "刪除後此 PDF 檔案將永久移除！",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '確定刪除',
        cancelButtonText: '取消'
    });

    if (result.isConfirmed) {
        try {
            const res = await fetch("/notes_tool", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "delete", transfer_id: transferId })
            });
            const data = await res.json();

            if (data.success) {
                Swal.fire({ 
                    icon: 'success', 
                    title: '已刪除', 
                    timer: 1000, 
                    showConfirmButton: false 
                }).then(() => {
                    location.reload();
                });
            } else {
                Swal.fire('錯誤', data.message, 'error');
            }
        } catch (e) {
            Swal.fire('錯誤', '系統連線異常', 'error');
        }
    }
}