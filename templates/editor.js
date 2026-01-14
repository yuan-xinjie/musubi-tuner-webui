const taskId = document.getElementById('current-task-id').value;

// --- 模板定义 ---
const TEMPLATE_DATA = {
    standard: { 
        general: { resolution: [1024, 1024], enable_bucket: true, bucket_no_upscale: false, batch_size: 1, caption_extension: ".txt", num_repeats: 10 },
        datasets: [{ image_directory: "./dataset/a", cache_directory: "./dataset/a/cache" }],
        samples: [{ prompt: "A futuristic space station", width: 1024, height: 576, sample_steps: 25, guidance_scale: 3.0, seed: 42, frame_count: 1, discrete_flow_shift: 3.0 }]
    },
    edit: { 
        general: { enable_bucket: true, bucket_no_upscale: false, batch_size: 1, caption_extension: ".txt", num_repeats: 10 },
        datasets: [{ resolution: [1024, 1024], image_directory: "./dataset/target", control_directory: "./dataset/ctrl", cache_directory: "./dataset/target/cache", qwen_image_edit_no_resize_control: false, qwen_image_edit_control_resolution: [1024, 1024] }],
        samples: [{ prompt: "Replace face...", width: 1024, height: 1024, sample_steps: 25, guidance_scale: 3.0, seed: 42, discrete_flow_shift: 3.0, control_image_path: [] }]
    }
};

document.addEventListener('DOMContentLoaded', () => {
    if(!taskId) { alert("ERROR: NO MISSION"); return; }
    loadTaskConfig(taskId);
    document.getElementById('master-profile-select').addEventListener('change', (e) => switchTemplate(e.target.value));
});

// --- 路径选择 ---
async function selectPath(inputId, type, extensions=[]) {
    try {
        const res = await fetch('/select_path', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ type, extensions })
        });
        const json = await res.json();
        
        if (json.path) {
            const input = document.getElementById(inputId);
            input.value = json.path;
            if (input.name === 'qwen.output_dir') {
                const nameInput = document.querySelector('input[name="qwen.output_name"]');
                if (nameInput && nameInput.value) {
                    if (!input.value.endsWith('/')) input.value += '/';
                    input.value += nameInput.value;
                }
            }
        }
    } catch(e) { console.error(e); }
}

function getPathInputHtml(id, name, value, type, exts=[]) {
    const extJson = JSON.stringify(exts);
    return `<div class="input-group">
            <input type="text" id="${id}" name="${name}" value="${value}" placeholder="...">
            <button type="button" class="btn-folder" onclick='selectPath("${id}", "${type}", ${extJson})'>📂</button>
        </div>`;
}

// --- Editor 逻辑 ---
async function loadTaskConfig(task) {
    try {
        const res = await fetch(`/load_task?task=${task}`);
        const json = await res.json();
        if (json.status === 'success') {
            const config = json.config; 
            for (const [key, value] of Object.entries(config)) {
                if (key === 'qwen.lora') { document.getElementById('master-profile-select').value = value; continue; }
                
                const originalInput = document.querySelector(`[name="${key}"]`);
                if (originalInput) {
                    const parent = originalInput.parentElement;
                    const val = (value === null) ? '' : value;
                    const cleanKey = key.replace('qwen.', '');
                    
                    const folderKeys = ['output_dir'];
                    const fileKeys = ['dit', 'vae', 'text_encoder', 'network_weights'];
                    
                    if (folderKeys.includes(cleanKey)) {
                        parent.innerHTML = `<div class="field-label">${cleanKey.toUpperCase()}</div>${getPathInputHtml(`input-${cleanKey}`, key, val, 'folder')}`;
                    } else if (fileKeys.includes(cleanKey)) {
                        parent.innerHTML = `<div class="field-label">${cleanKey.toUpperCase()}</div>${getPathInputHtml(`input-${cleanKey}`, key, val, 'file', ['.safetensors'])}`;
                    } else {
                        if (originalInput.type === 'checkbox') originalInput.checked = value;
                        else originalInput.value = val;
                    }
                }
            }
            await loadFilesOrTemplate();
        } else alert("LOAD ERROR: " + json.message);
    } catch(e) { console.error(e); }
}

function switchTemplate(newProfile) {
    const isStandard = ['Qwen-Image', 'Qwen-Image-2512', 'Z-Image-Turbo'].includes(newProfile);
    const targetType = isStandard ? 'standard' : 'edit';
    const data = JSON.parse(JSON.stringify(TEMPLATE_DATA[targetType]));

    const currentBatch = document.querySelector('input[data-json-key="batch_size"]')?.value;
    const currentRepeat = document.querySelector('input[data-json-key="num_repeats"]')?.value;
    if (currentBatch) data.general.batch_size = parseInt(currentBatch);
    if (currentRepeat) data.general.num_repeats = parseInt(currentRepeat);

    renderJsonFields(newProfile, data);
    document.getElementById('toml-filename').innerText = `[TEMPLATE: ${targetType.toUpperCase()}]`;
    document.getElementById('txt-filename').innerText = `[TEMPLATE: ${targetType.toUpperCase()}]`;
    document.getElementById('dataset-loading').style.display='none';
    document.getElementById('dataset-fields').style.display='block';
    document.getElementById('sample-loading').style.display='none';
    document.getElementById('sample-container').style.display='block';
}

async function loadFilesOrTemplate() {
    const profile = document.getElementById('master-profile-select').value;
    if (taskId === '__NEW__') { switchTemplate(profile); return; }
    
    const dsLoading = document.getElementById('dataset-loading');
    const spLoading = document.getElementById('sample-loading');
    dsLoading.style.display='block'; spLoading.style.display='block';
    
    try {
        const r = await fetch(`/get_json_config?task=${taskId}`);
        const j = await r.json();
        if (j.status === 'success') {
            renderJsonFields(profile, j.data);
            document.getElementById('toml-filename').innerText = `${taskId}.json`;
            document.getElementById('txt-filename').innerText = `${taskId}.json`;
            document.getElementById('dataset-fields').style.display='block';
            document.getElementById('sample-container').style.display='block';
        } else { switchTemplate(profile); }
    } catch(e) { alert("Network Error"); } 
    finally { dsLoading.style.display='none'; spLoading.style.display='none'; }
}

function renderJsonFields(profile, data) {
    const container = document.querySelector('.grid-dataset');
    const sampleList = document.getElementById('sample-list');
    container.innerHTML = ''; sampleList.innerHTML = '';
    
    const isEdit = !['Qwen-Image', 'Qwen-Image-2512', 'Z-Image-Turbo'].includes(profile);
    const gen = data.general || {};
    const ds = (data.datasets && data.datasets.length) ? data.datasets[0] : {};
    const samples = data.samples || [];

    const create = (lbl, sec, k, v, small) => {
        const pathKeys = ['image_directory', 'cache_directory', 'control_directory'];
        let inputHtml = `<input type="text" data-json-section="${sec}" data-json-key="${k}" value="${v!==undefined?v:''}">`;
        if (pathKeys.includes(k)) {
            const uid = `ds-${sec}-${k}`;
            inputHtml = `<div class="input-group">
                    <input type="text" id="${uid}" data-json-section="${sec}" data-json-key="${k}" value="${v!==undefined?v:''}">
                    <button type="button" class="btn-folder" onclick='selectPath("${uid}", "folder")'>📂</button>
                </div>`;
        }
        container.innerHTML += `<div class="field-item dataset-item ${small?'small-field':''}"><div class="field-label">${lbl}</div>${inputHtml}</div>`;
    };
    
    const createRes = (lbl, sec, k, v) => {
        let w=1024,h=1024; if(Array.isArray(v)&&v.length>1){w=v[0];h=v[1];}
        container.innerHTML += `<div class="field-item dataset-item res-field">
            <div class="field-label">${lbl}</div>
            <div class="res-inputs">
                <input type="number" class="res-w" value="${w}"><span class="res-x">x</span><input type="number" class="res-h" value="${h}">
            </div>
            <input type="hidden" data-json-section="${sec}" data-json-key="${k}" data-type="resolution">
        </div>`;
    };

    if(gen.batch_size!==undefined) create('BATCH','general','batch_size',gen.batch_size,true);
    if(gen.num_repeats!==undefined) create('RPT','general','num_repeats',gen.num_repeats,true);
    if(gen.resolution!==undefined) createRes('RES','general','resolution',gen.resolution);
    if(ds.resolution!==undefined) createRes('DS_RES','datasets','resolution',ds.resolution);
    if(isEdit && ds.qwen_image_edit_control_resolution!==undefined) createRes('CTRL_RES','datasets','qwen_image_edit_control_resolution',ds.qwen_image_edit_control_resolution);
    if(ds.image_directory!==undefined) create('IMG_DIR','datasets','image_directory',ds.image_directory);
    if(isEdit && ds.control_directory!==undefined) create('CTRL_DIR','datasets','control_directory',ds.control_directory);
    if(ds.cache_directory!==undefined) create('CACHE_DIR','datasets','cache_directory',ds.cache_directory);

    samples.forEach(s => createSampleUiItem(sampleList, s, isEdit));
}

function createSampleUiItem(container, data, isEdit) {
    const div = document.createElement('div');
    div.className = 'sample-item';
    const defs = [
        {l:'W',k:'width',w:'50px',d:1024}, {l:'H',k:'height',w:'50px',d:1024},
        {l:'SEED',k:'seed',w:'50px',d:42}, {l:'CFG',k:'guidance_scale',w:'50px',d:3.0},
        {l:'STEP',k:'sample_steps',w:'50px',d:20}, {l:'SFT',k:'discrete_flow_shift',w:'50px',d:3.0}
    ];
    if(!isEdit) defs.push({l:'FRAME',k:'frame_count',w:'60px',d:1});

    let html = '';
    defs.forEach(p => {
        const v = data[p.k]!==undefined ? data[p.k] : p.d;
        html += `<div class="sample-param" style="flex:0 0 ${p.w}"><label>${p.l}</label><input type="text" data-json-key="${p.k}" value="${v}"></div>`;
    });

    if(isEdit) {
        const cis = data.control_image_path || [];
        for(let i=0; i<3; i++) {
            const uid = `ci-${Math.random().toString(36).substr(2, 9)}`;
            const val = cis[i] || '';
            const extJson = JSON.stringify(['.png','.jpg','.jpeg','.gif','.webp']);
            html += `<div class="sample-param ci-param" style="flex:1;min-width:150px">
                    <label>CTRL IMG ${i+1}</label>
                    <div class="input-group">
                        <input type="text" id="${uid}" data-json-key="control_image_path" value="${val}" placeholder="...">
                        <button type="button" class="btn-folder" onclick='selectPath("${uid}", "file", ${extJson})'>📂</button>
                    </div>
                </div>`;
        }
    }
    div.innerHTML = `<div class="sample-row-top"><textarea class="sample-prompt">${data.prompt||''}</textarea><button class="btn-delete" onclick="this.closest('.sample-item').remove()">DEL</button></div><div class="sample-row-bottom">${html}</div>`;
    container.appendChild(div);
}

function addSampleItem() {
    const list = document.getElementById('sample-list');
    const profile = document.getElementById('master-profile-select').value;
    const isEdit = !['Qwen-Image', 'Qwen-Image-2512', 'Z-Image-Turbo'].includes(profile);
    createSampleUiItem(list, {}, isEdit);
    list.lastElementChild.scrollIntoView({ behavior: 'smooth' });
}

async function submitConfig() {
    const btn = document.getElementById('save-btn');
    const taskId = document.getElementById('current-task-id').value;
    const originalText = btn.innerText;
    btn.innerText="SAVING...";
    
    // YAML
    const yamlUpdates = {};
    document.querySelectorAll('#config-form input:not([data-json-key]):not([data-key]):not(.res-w):not(.res-h):not([data-type="resolution"]):not(.sample-prompt), #config-form select:not(#master-profile-select)').forEach(i => {
        if(!i.name) return;
        if(i.dataset.type==='bool') yamlUpdates[i.name] = i.checked;
        else if(i.dataset.type==='select') {
             let v = i.value; if(!isNaN(v)&&v.trim()!=='') v=Number(v);
             yamlUpdates[i.name] = v;
        } else yamlUpdates[i.name] = i.value;
    });

    const profile = document.getElementById('master-profile-select').value;
    yamlUpdates['qwen.lora'] = profile;
    let ver = 'original';
    if(profile.includes('Edit')) ver = profile.endsWith('Edit')?'edit':(profile.endsWith('2509')?'edit-2509':'edit-2511');
    yamlUpdates['qwen.model_version'] = ver;

    // JSON
    const isStandard = ['Qwen-Image', 'Qwen-Image-2512', 'Z-Image-Turbo'].includes(profile);
    const targetType = isStandard ? 'standard' : 'edit';
    const jsonData = JSON.parse(JSON.stringify(TEMPLATE_DATA[targetType]));
    
    document.querySelectorAll('.dataset-item input[type="text"][data-json-key]').forEach(input => {
        const sec = input.dataset.jsonSection;
        const k = input.dataset.jsonKey;
        let v = input.value;
        if(['batch_size','num_repeats'].includes(k)) v = parseInt(v) || 1;
        if (sec === 'general') jsonData.general[k] = v;
        else if (sec === 'datasets') jsonData.datasets[0][k] = v;
    });
    
    document.querySelectorAll('.dataset-item input[type="hidden"][data-type="resolution"]').forEach(hidden => {
        const parent = hidden.parentElement;
        const w = parseInt(parent.querySelector('.res-w').value) || 1024;
        const h = parseInt(parent.querySelector('.res-h').value) || 1024;
        const sec = hidden.dataset.jsonSection;
        const k = hidden.dataset.jsonKey;
        if (sec === 'general') jsonData.general[k] = [w, h];
        else if (sec === 'datasets') jsonData.datasets[0][k] = [w, h];
    });

    jsonData.samples = [];
    document.querySelectorAll('.sample-item').forEach(item => {
        const p = item.querySelector('.sample-prompt').value;
        if (!p.trim()) return;
        const sampleObj = { prompt: p };
        item.querySelectorAll('.sample-param input:not(.ci-param input)').forEach(inp => {
            const k = inp.dataset.jsonKey;
            let val = parseFloat(inp.value);
            if (['width','height','seed','sample_steps','frame_count'].includes(k)) val = parseInt(inp.value);
            sampleObj[k] = val;
        });
        if (!isStandard) {
            const cis = [];
            item.querySelectorAll('.ci-param input').forEach(inp => {
                if (inp.value.trim()) cis.push(inp.value.trim());
            });
            if (cis.length > 0) sampleObj.control_image_path = cis;
        }
        jsonData.samples.push(sampleObj);
    });

    const payload = { task_name: taskId, yaml_updates: yamlUpdates, json_data: jsonData };

    try {
        const res = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const json = await res.json();
        if(json.status==='success') {
            btn.innerText = "SAVED";
            if (json.new_task_id && json.new_task_id !== taskId) window.location.href = `/editor?task=${json.new_task_id}`;
            else setTimeout(()=>btn.innerText = originalText, 1500);
        } else { alert("Error: " + json.message); btn.innerText = "ERROR"; }
    } catch (e) { alert("Net Error: " + e); btn.innerText = "FAIL"; }
}
