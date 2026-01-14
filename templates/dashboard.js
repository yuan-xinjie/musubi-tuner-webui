document.addEventListener('DOMContentLoaded', () => {
    loadMissions();
    
    // 初始化控制台连接
    const consoleDiv = document.getElementById('console-window');
	if (consoleDiv) {
        consoleDiv.style.display = 'flex'; 
        connectLogStream(); 
    }
    checkTaskStatus();
    
    document.getElementById('cmd-input').addEventListener('keypress', (e) => {
        if(e.key === 'Enter') sendConsoleCmd();
    });
});

let currentStreamId = 0;

async function checkTaskStatus() {
    try {
        const res = await fetch('/task_status');
        const json = await res.json();
        const stopBtn = document.getElementById('stop-btn');
        if (stopBtn) {
            if (json.is_running) stopBtn.style.display = 'inline-block';
            else stopBtn.style.display = 'none';
        }
    } catch (e) {}
}

async function stopTask() {
    if(!confirm("FORCE STOP?")) return;
    try {
        const res = await fetch('/stop_task', { method: 'POST' });
        const json = await res.json();
        if(json.status === 'success') {
            const stopBtn = document.getElementById('stop-btn');
            if(stopBtn) stopBtn.style.display = 'none';
        } else {
            alert(json.message);
        }
    } catch (e) { alert("Error: " + e); }
}

async function connectLogStream() {
    currentStreamId++;
    const myStreamId = currentStreamId;
    
    const contentPre = document.getElementById('console-content');
    const decoder = new TextDecoder();

    while (myStreamId === currentStreamId) {
        try {
            const response = await fetch('/stream_logs');
            const reader = response.body.getReader();
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                if (myStreamId !== currentStreamId) { reader.cancel(); return; }
                
                // 直接追加文本，不处理 \r (浏览器会自动换行，进度条可能会刷屏，但绝对不会丢数据)
                contentPre.innerText += decoder.decode(value);
                contentPre.scrollTop = contentPre.scrollHeight;
            }
            await new Promise(r => setTimeout(r, 2000));
        } catch (e) {
            console.log("Stream lost, reconnecting...");
            if (myStreamId !== currentStreamId) return;
            await new Promise(r => setTimeout(r, 1000));
        }
    }
}


async function checkTaskStatus() {
    try {
        const res = await fetch('/task_status');
        const json = await res.json();
        const stopBtn = document.getElementById('stop-btn');
        if (json.is_running) stopBtn.style.display = 'inline-block';
        else stopBtn.style.display = 'none';
    } catch (e) {}
}

async function connectLogStream() {
    currentStreamId++;
    const myStreamId = currentStreamId;
    const contentPre = document.getElementById('console-content');
    const decoder = new TextDecoder();
    while (myStreamId === currentStreamId) {
        try {
            const response = await fetch('/stream_logs');
            const reader = response.body.getReader();
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                if (myStreamId !== currentStreamId) { reader.cancel(); return; }
                contentPre.innerText += decoder.decode(value);
                contentPre.scrollTop = contentPre.scrollHeight;
            }
            await new Promise(r => setTimeout(r, 2000));
        } catch (e) {
            if (myStreamId !== currentStreamId) return;
            await new Promise(r => setTimeout(r, 1000));
        }
    }
}

async function sendConsoleCmd() {
    const input = document.getElementById('cmd-input');
    const cmd = input.value;
    if(!cmd.trim()) return;
    const contentPre = document.getElementById('console-content');
    contentPre.innerText += `\n> ${cmd}\n`;
    contentPre.scrollTop = contentPre.scrollHeight;
    try {
        await fetch('/console_input', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ cmd: cmd })
        });
        input.value = '';
    } catch(e) { contentPre.innerText += `Error: ${e}\n`; }
}

async function stopTask() {
    if(!confirm("STOP TASK?")) return;
    try {
        const res = await fetch('/stop_task', { method: 'POST' });
        if((await res.json()).status === 'success') document.getElementById('stop-btn').style.display = 'none';
    } catch (e) {}
}

async function runTask(action, taskName) {
    const contentPre = document.getElementById('console-content');
    contentPre.innerText += `\n> INITIALIZING ${action.toUpperCase()} FOR [${taskName}]...\n`;
    contentPre.scrollTop = contentPre.scrollHeight;
    try {
        const res = await fetch(`/execute_task?task=${taskName}&action=${action}`);
        const json = await res.json();
        if (json.status === 'success') {
            document.getElementById('stop-btn').style.display = 'inline-block';
            connectLogStream(); 
        } else {
            contentPre.innerText += `\n❌ START FAILED: ${json.message}\n`;
        }
    } catch (e) { contentPre.innerText += `\n❌ NET ERROR: ${e}\n`; }
}

async function loadMissions() {
    const list = document.getElementById('mission-list');
    list.innerHTML = '<div class="loading-text">SCANNING PROTOCOLS...</div>';

    try {
        const res = await fetch('/get_tasks');
        const json = await res.json();
        
        list.innerHTML = '';
        
        if (json.tasks.length === 0) {
            list.innerHTML = '<div style="color:var(--text-muted);text-align:center;">NO MISSIONS FOUND.</div>';
            return;
        }

        json.tasks.forEach(task => {
            const row = document.createElement('div');
            row.className = 'mission-row';
            row.innerHTML = `
                <div class="mission-info">
                    <div class="mission-name">${task.toUpperCase()}</div>
                </div>
                <div class="mission-actions">
                    <div class="action-group-left">
                        <button class="btn-card" onclick="location.href='/editor?task=${task}'">EDIT</button>
                        <button class="btn-card" onclick="cloneTask('${task}')">CLONE</button>
                        <button class="btn-card danger" onclick="deleteTask('${task}')">DEL</button>
                    </div>
                    <div class="v-sep"></div>
                    <div class="action-group-right">
                        <button class="btn-exec" onclick="runTask('cache', '${task}')">CACHE</button>
                        <button class="btn-exec primary" onclick="runTask('train', '${task}')">TRAIN</button>
                    </div>
                </div>
            `;
            list.appendChild(row);
        });

    } catch (e) {
        list.innerHTML = `<div style="color:red">ERROR: ${e}</div>`;
    }
}

// [修改] 新增任务：直接跳转到特殊 URL
async function createNewTask() {
    window.location.href = '/editor?task=__NEW__';
}

// [修改] 克隆任务：直接执行，不弹窗
async function cloneTask(source) {
    try {
        const res = await fetch('/create_task', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ source_task_name: source })
        });
        const json = await res.json();
        
        if (json.status === 'success') {
            loadMissions(); // 刷新列表
        } else {
            alert("FAILED: " + json.message);
        }
    } catch (e) { alert("NET ERROR: " + e); }
}

async function deleteTask(name) {
    if (!confirm(`CONFIRM DELETE: [${name}]?`)) return;
    try {
        const res = await fetch('/delete_task', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ task_name: name })
        });
        if ((await res.json()).status === 'success') loadMissions();
    } catch (e) { alert(e); }
}
