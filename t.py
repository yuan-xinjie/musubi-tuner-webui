import base64
import os
import copy
import json
import sys
import subprocess
import textwrap
import threading
import time
from flask import Flask, render_template, request, jsonify, send_from_directory, Response, stream_with_context
from ruamel.yaml import YAML

app = Flask(__name__)
CONFIG_FILE = './src/config.yaml'

# --- 脚本路径配置 ---
LATENTS_SCRIPT = "src/musubi_tuner/qwen_image_cache_latents.py"
TEXT_ENC_SCRIPT = "src/musubi_tuner/qwen_image_cache_text_encoder_outputs.py"
TRAIN_SCRIPT = "src/musubi_tuner/qwen_image_train_network.py"

yaml = YAML()
yaml.preserve_quotes = True

# --- 1. 默认参数 ---
NEW_TASK_DEFAULTS = {
    'max_train_epochs': 40,
    'save_every_n_epochs': 2,
    'sample_every_n_epochs': 2,
    'gradient_checkpointing': True,
    'gradient_checkpointing_cpu_offload': False,
    'optimizer_type': 'adamw',
    'learning_rate': 0.0001,
    'timestep_sampling': 'qwen_shift',
    'loraplus_lr_ratio': 4,
    'network_dim': 32,
    'network_alpha': 16,
    'blocks_to_swap': 16,
    'model_version': 'original',
    'lora': 'Qwen-Image',
    # 路径置空
    'dit': "", 'vae': "", 'text_encoder': "",
    'dataset_config': "", 'sample_prompts': ""
}

FIELD_OPTIONS = {
    'qwen.timestep_sampling': ['flux_shift', 'qwen_shift', 'qinglong_qwen'],
    'qwen.optimizer_type': ['adamw', 'adamw8bit', 'prodigy'],
}

VISIBLE_TASK_KEYS = {
    'lora', 'model_version', 'sample_prompts', 'dataset_config',
    'output_name', 'training_comment', 'output_dir',
    'max_train_epochs', 'save_every_n_epochs', 'sample_every_n_epochs',
    'network_weights', 'dim_from_weights',
    'dit', 'vae', 'text_encoder',
    'gradient_checkpointing', 'gradient_checkpointing_cpu_offload',
    'optimizer_type', 'learning_rate', 'timestep_sampling',
    'loraplus_lr_ratio', 'network_dim', 'network_alpha', 'blocks_to_swap'
}

IGNORED_SECTIONS = {'global_config', 'golbal_config', 'cache', 'qwen'}

TASK_STATE = {"process": None, "is_running": False, "logs": [], "current_task": None, "action": None}


# --- 辅助函数 ---
def load_full_yaml():
    if not os.path.exists(CONFIG_FILE): return {}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return yaml.load(f)


def save_full_yaml(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: yaml.dump(data, f)


# --- 路由 ---
@app.route('/')
def dashboard(): return render_template('dashboard.html')


@app.route('/editor')
def editor():
    task_name = request.args.get('task')
    if not task_name: return "Error", 400
    return render_template('editor.html', task_name=task_name, options=FIELD_OPTIONS)


@app.route('/style.css')
def serve_css(): return send_from_directory('templates', 'style.css')


@app.route('/dashboard.js')
def serve_dash_js(): return send_from_directory('templates', 'dashboard.js')


@app.route('/editor.js')
def serve_edit_js(): return send_from_directory('templates', 'editor.js')


def run_powershell_dialog_robust(csharp_code, mode, title, filter_pattern="*.*"):
    # 构造调用逻辑
    invocation = ""
    if mode == 'folder':
        invocation = f"[Win32Native.ModernDialog]::ShowFolder('{title}')"
    else:
        invocation = f"[Win32Native.ModernDialog]::ShowFile('{title}', '{filter_pattern}')"

    # PowerShell 脚本
    # 1. 顶部增加了 $ProgressPreference = 'SilentlyContinue' 以屏蔽进度条乱码
    # 2. C# 代码保持兼容旧版语法的写法
    ps_script = f"""
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'

$code = @'
using System;
using System.Runtime.InteropServices;

namespace Win32Native {{

    [ComImport]
    [Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
    [ClassInterface(ClassInterfaceType.None)]
    public class FileOpenDialog {{ }}

    [ComImport]
    [Guid("42f85136-db7e-439c-85f1-e4075d135fc8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IFileDialog {{
        [PreserveSig] int Show(IntPtr parent);
        [PreserveSig] int SetFileTypes(uint cFileTypes, [In, MarshalAs(UnmanagedType.LPArray)] FilterSpec[] rgFilterSpec);
        [PreserveSig] int SetFileTypeIndex(uint iFileType);
        [PreserveSig] int GetFileTypeIndex(out uint piFileType);
        [PreserveSig] int Advise(IntPtr pfde, out uint pdwCookie);
        [PreserveSig] int Unadvise(uint dwCookie);
        [PreserveSig] int SetOptions(uint fos);
        [PreserveSig] int GetOptions(out uint fos);
        [PreserveSig] int SetDefaultFolder(IntPtr psi);
        [PreserveSig] int SetFolder(IntPtr psi);
        [PreserveSig] int GetFolder(out IntPtr ppsi);
        [PreserveSig] int GetCurrentSelection(out IntPtr ppsi);
        [PreserveSig] int SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        [PreserveSig] int GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string pszName);
        [PreserveSig] int SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
        [PreserveSig] int SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
        [PreserveSig] int SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
        [PreserveSig] int GetResult(out IShellItem ppsi);
        void AddPlace(IntPtr psi, int fdap);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string pszDefaultExtension);
        void Close(int hr);
        void SetClientGuid(ref Guid guid);
        void ClearClientData();
        void SetFilter(IntPtr pFilter);
    }}

    [ComImport]
    [Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellItem {{
        void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
        void GetParent(out IShellItem ppsi);
        void GetDisplayName(uint sigdnName, [MarshalAs(UnmanagedType.LPWStr)] out string ppszName);
        void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
        void Compare(IShellItem psi, uint hint, out int piOrder);
    }}

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
    public struct FilterSpec {{ 
        [MarshalAs(UnmanagedType.LPWStr)] public string Name; 
        [MarshalAs(UnmanagedType.LPWStr)] public string Spec; 
        public FilterSpec(string name, string spec) {{ Name = name; Spec = spec; }}
    }}

    public class ModernDialog {{
        [DllImport("user32.dll")]
        private static extern IntPtr GetForegroundWindow();

        public static string ShowFolder(string title) {{
            var dlg = new FileOpenDialog();
            var ifd = (IFileDialog)dlg;
            try {{
                ifd.SetTitle(title);
                ifd.SetOptions(0x60); // FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM

                int hr = ifd.Show(GetForegroundWindow());
                if (hr < 0) return null;

                IShellItem item;
                ifd.GetResult(out item);
                if (item != null) {{
                    string path;
                    item.GetDisplayName(0x80058000, out path);
                    return path;
                }}
                return null;
            }} finally {{
                Marshal.FinalReleaseComObject(dlg);
            }}
        }}

        public static string ShowFile(string title, string filterPattern) {{
            var dlg = new FileOpenDialog();
            var ifd = (IFileDialog)dlg;
            try {{
                ifd.SetTitle(title);
                ifd.SetOptions(0x40); // FOS_FORCEFILESYSTEM

                var specs = new FilterSpec[] {{
                    new FilterSpec("Target Files", filterPattern),
                    new FilterSpec("All Files", "*.*")
                }};
                ifd.SetFileTypes((uint)specs.Length, specs);

                int hr = ifd.Show(GetForegroundWindow());
                if (hr < 0) return null;

                IShellItem item;
                ifd.GetResult(out item);
                if (item != null) {{
                    string path;
                    item.GetDisplayName(0x80058000, out path);
                    return path;
                }}
                return null;
            }} finally {{
                Marshal.FinalReleaseComObject(dlg);
            }}
        }}
    }}
}}
'@

try {{
    Add-Type -TypeDefinition $code -Language CSharp -ErrorAction Stop
    $res = {invocation}
    if ($res) {{ Write-Output $res }}
}} catch {{
    # 错误信息写入 stderr，不会污染 stdout
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}}
    """

    try:
        encoded_cmd = base64.b64encode(ps_script.encode('utf-16le')).decode('utf-8')
        cmd = ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Sta", "-EncodedCommand", encoded_cmd]

        # 【关键修改】 stdout 和 stderr 分开读取
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            print(f"PS Error: {stderr}")
            return ""

        # 即使成功，stderr 也可能包含非致命的 CLIXML 进度信息，我们只取 stdout
        return stdout.strip()

    except Exception as e:
        print(f"General Error: {e}")
        return ""


def open_file_dialog_powershell(title, filter_pattern="*.*"):
    return run_powershell_dialog_robust(None, 'file', title, filter_pattern)


def open_folder_dialog_powershell(title):
    return run_powershell_dialog_robust(None, 'folder', title)
@app.route('/select_path', methods=['POST'])
def select_path():
    data = request.json
    select_type = data.get('type')
    extensions = data.get('extensions', [])

    path = ""
    if select_type == 'folder':
        path = open_folder_dialog_powershell("Select Directory")
    else:
        ext_pattern = "*.*"
        if extensions: ext_pattern = ";".join([f"*{ext}" for ext in extensions])
        path = open_file_dialog_powershell("Select File", ext_pattern)

    if path:
        path = path.replace('\\', '/')
        current_cwd = os.getcwd().replace('\\', '/')
        if path.startswith(current_cwd):
            try:
                rel_path = os.path.relpath(path, current_cwd)
                path = f"./{rel_path.replace(os.sep, '/')}"
            except:
                pass

    return jsonify({"path": path})


# --- 任务 API ---
@app.route('/get_tasks')
def get_tasks():
    config = load_full_yaml()
    qwen_root = config.get('qwen', {})
    tasks = [k for k in qwen_root.keys() if k not in IGNORED_SECTIONS]
    return jsonify({"status": "success", "tasks": tasks})


@app.route('/load_task')
def load_task():
    task_name = request.args.get('task')
    config = load_full_yaml()
    qwen_root = config.get('qwen', {})

    task_data = {}
    if task_name == '__NEW__':
        for k in qwen_root:
            if k not in IGNORED_SECTIONS: task_data = copy.deepcopy(qwen_root[k]); break
        if not task_data: task_data = {}
        for k, v in NEW_TASK_DEFAULTS.items(): task_data[k] = v
        task_data['output_name'] = ""
        task_data['output_dir'] = "./output/"
    else:
        if task_name not in qwen_root: return jsonify({"status": "error", "message": "Not found"}), 404
        task_data = qwen_root[task_name]

    flat_data = {}
    for k, v in task_data.items():
        if k in VISIBLE_TASK_KEYS: flat_data[f"qwen.{k}"] = v
    return jsonify({"status": "success", "config": flat_data})


@app.route('/create_task', methods=['POST'])
def create_task():
    try:
        source_name = request.json.get('source_task_name')
        config = load_full_yaml()
        qwen = config.get('qwen', {})
        if not source_name or source_name not in qwen: return jsonify(
            {"status": "error", "message": "Source missing"}), 400

        base_name = f"{source_name}_copy"
        new_name = base_name
        counter = 1
        while new_name in qwen: new_name = f"{base_name}_{counter}"; counter += 1

        source_data = copy.deepcopy(qwen[source_name])
        source_data['output_name'] = new_name
        source_data['output_dir'] = f"./output/{new_name}"

        # 复制 JSON
        src_json = f"./src/{source_name}.json"
        dst_json = f"./src/{new_name}.json"
        if os.path.exists(src_json):
            with open(src_json, 'r', encoding='utf-8') as f: content = json.load(f)
            with open(dst_json, 'w', encoding='utf-8') as f: json.dump(content, f, indent=2, ensure_ascii=False)
            source_data['dataset_config'] = dst_json
            source_data['sample_prompts'] = dst_json

        qwen[new_name] = source_data
        save_full_yaml(config)
        return jsonify({"status": "success", "task_name": new_name})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/delete_task', methods=['POST'])
def delete_task():
    try:
        task_name = request.json.get('task_name')
        config = load_full_yaml()
        qwen = config.get('qwen', {})
        if task_name in qwen and task_name not in IGNORED_SECTIONS:
            path = f"./src/{task_name}.json"
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
            del qwen[task_name]
            save_full_yaml(config)
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "Err"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 执行接口 ---
def run_background_process(commands):
    total = len(commands)
    # [回退] 使用稳健的文本缓冲模式
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    for idx, (name, cmd_list) in enumerate(commands):
        if not TASK_STATE["is_running"]: break
        msg = f"\n{'=' * 40}\n🚀 {name} ({idx + 1}/{total})\n📂 CMD: {' '.join(cmd_list)}\n{'=' * 40}\n"
        TASK_STATE["logs"].append(msg)
        try:
            process = subprocess.Popen(
                cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                text=True, bufsize=1, encoding='utf-8', errors='replace', env=env
            )
            TASK_STATE["process"] = process
            for line in iter(process.stdout.readline, ''):
                TASK_STATE["logs"].append(line)
            process.stdout.close()
            rc = process.wait()
            if rc != 0:
                if TASK_STATE["is_running"]:
                    TASK_STATE["logs"].append(f"\n❌ FAILED (CODE {rc}).\n")
                else:
                    TASK_STATE["logs"].append(f"\n🛑 STOPPED BY USER.\n")
                break
            else:
                TASK_STATE["logs"].append(f"\n✅ COMPLETED.\n")
        except Exception as e:
            TASK_STATE["logs"].append(f"\n❌ SYSTEM ERROR: {str(e)}\n")
            break
    TASK_STATE["is_running"] = False
    TASK_STATE["process"] = None
    TASK_STATE["logs"].append("\n✨ ALL TASKS FINISHED.\n")


@app.route('/execute_task')
def execute_task():
    if TASK_STATE["is_running"]: return jsonify({"status": "error", "message": "Busy"}), 400
    task_name = request.args.get('task');
    action = request.args.get('action')
    if not task_name: return "Error", 400
    config = load_full_yaml()
    if task_name not in config.get('qwen', {}): return "Error", 404
    task_data = config['qwen'][task_name]
    cache_data = config['qwen'].get('cache', {})
    global_config = config['qwen'].get('global_config', config['qwen'].get('golbal_config', {}))
    commands = []

    if action == 'cache':
        cmd1 = [sys.executable, '-u', LATENTS_SCRIPT]
        for key in ['dataset_config', 'vae', 'model_version']:
            if task_data.get(key): cmd1.extend([f'--{key}={task_data[key]}'])
        if cache_data.get('vae_tiling'): cmd1.append('--vae_tiling')
        for key in ['vae_chunk_size', 'vae_spatial_tile_sample_min_size']:
            if cache_data.get(key): cmd1.extend([f'--{key}={cache_data[key]}'])
        commands.append(("STEP 1: CACHE LATENTS", cmd1))

        cmd2 = [sys.executable, '-u', TEXT_ENC_SCRIPT]
        for key in ['dataset_config', 'text_encoder', 'model_version']:
            if task_data.get(key): cmd2.extend([f'--{key}={task_data[key]}'])
        if cache_data.get('batch_size'): cmd2.extend([f'--batch_size={cache_data["batch_size"]}'])
        if cache_data.get('fp8_vl'): cmd2.append('--fp8_vl')
        commands.append(("STEP 2: CACHE TEXT ENCODER", cmd2))

    elif action == 'train':
        cmd = ['accelerate', 'launch', '--num_cpu_threads_per_process', '8']
        if 'mixed_precision' in global_config: cmd.extend(['--mixed_precision', str(global_config['mixed_precision'])])
        cmd.append(TRAIN_SCRIPT)
        combined_args = {**global_config, **task_data}
        blacklist_keys = ['lora', 'network_args', 'mixed_precision']
        for key, value in combined_args.items():
            if value is None or value == "": continue
            if key in blacklist_keys: continue
            if key == 'loraplus_lr_ratio':
                cmd.extend(['--network_args', f"{key}={value}"])
                continue
            if isinstance(value, bool):
                if value is True: cmd.append(f'--{key}')
            else:
                cmd.extend([f'--{key}={value}'])  # [修改] 恢复使用 = 连接
        commands.append(("TRAINING SEQUENCE", cmd))

    TASK_STATE["is_running"] = True;
    TASK_STATE["logs"] = [];
    TASK_STATE["current_task"] = task_name;
    TASK_STATE["action"] = action
    thread = threading.Thread(target=run_background_process, args=(commands,));
    thread.start()
    return jsonify({"status": "success", "message": "Started"})


@app.route('/stop_task', methods=['POST'])
def stop_task():
    if TASK_STATE["process"] and TASK_STATE["is_running"]:
        TASK_STATE["is_running"] = False
        try:
            pid = TASK_STATE["process"].pid
            if os.name == 'nt':
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)])
            else:
                import signal; os.killpg(os.getpgid(pid), signal.SIGTERM)
            TASK_STATE["logs"].append("\n🛑 KILLED.\n")
            return jsonify({"status": "success"})
        except:
            return jsonify({"status": "error"}), 500
    return jsonify({"status": "error"}), 400


@app.route('/stream_logs')
def stream_logs():
    def generate():
        curr = 0
        while True:
            if curr < len(TASK_STATE["logs"]):
                yield TASK_STATE["logs"][curr]; curr += 1
            else:
                time.sleep(0.5)

    return Response(stream_with_context(generate()), mimetype='text/plain')


@app.route('/task_status')
def task_status():
    return jsonify(
        {"is_running": TASK_STATE["is_running"], "task": TASK_STATE["current_task"], "action": TASK_STATE["action"]})


@app.route('/console_input', methods=['POST'])
def console_input():
    cmd = request.json.get('cmd')
    if not cmd: return jsonify({"status": "error"}), 400
    if TASK_STATE["is_running"] and TASK_STATE["process"]:
        try:
            if TASK_STATE["process"].stdin:
                TASK_STATE["process"].stdin.write(cmd + "\n");
                TASK_STATE["process"].stdin.flush()
                TASK_STATE["logs"].append(f"> {cmd}\n")
                return jsonify({"status": "success"})
        except:
            return jsonify({"status": "error"}), 500
    else:
        TASK_STATE["logs"].append(f"\n> {cmd}\n")
        try:
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                          errors='replace')
            TASK_STATE["logs"].append(out)
        except subprocess.CalledProcessError as e:
            TASK_STATE["logs"].append(e.output)
        except Exception as e:
            TASK_STATE["logs"].append(str(e) + "\n")
    return jsonify({"status": "success"})


# --- JSON 读写 ---
@app.route('/get_json_config')
def get_json_config():
    task_name = request.args.get('task')
    if not task_name: return jsonify({"status": "error"}), 400
    json_path = f"./src/{task_name}.json"
    if not os.path.exists(json_path): return jsonify({"status": "error", "message": "Not found"}), 404
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return jsonify({"status": "success", "data": json.load(f)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/save', methods=['POST'])
def save():
    try:
        data = request.json
        current_task_id = data.get('task_name')
        full_config = load_full_yaml()

        if current_task_id == '__NEW__':
            task_config = {}
        else:
            if 'qwen' not in full_config or current_task_id not in full_config['qwen']: return jsonify(
                {"status": "error"}), 404
            task_config = full_config['qwen'][current_task_id]

        new_output_name = None

        # 1. 更新 YAML
        for flat_key, value in data.get('yaml_updates', {}).items():
            key = flat_key.split('.')[-1]
            if key not in VISIBLE_TASK_KEYS: continue
            if key == 'output_name': new_output_name = value
            orig_val = task_config.get(key)
            if value == "" and orig_val is None: continue
            if isinstance(orig_val, bool) or (current_task_id == '__NEW__' and value in [True, False]):
                task_config[key] = bool(value)
            elif (isinstance(orig_val, int) and not isinstance(orig_val, bool)) or (
                    current_task_id == '__NEW__' and isinstance(value, int)):
                try:
                    task_config[key] = int(value)
                except:
                    task_config[key] = value
            elif isinstance(orig_val, float):
                try:
                    task_config[key] = float(value)
                except:
                    task_config[key] = value
            else:
                if isinstance(value, str): value = value.replace('\\', '/')
                task_config[key] = value

        if not new_output_name: return jsonify({"status": "error"}), 400

        if current_task_id == '__NEW__': task_config['output_dir'] = f"./output/{new_output_name}"

        # 2. 保存 JSON 文件
        if not os.path.exists("./src"): os.makedirs("./src")
        json_path = f"./src/{new_output_name}.json"

        json_data = data.get('json_data', {})
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        task_config['dataset_config'] = json_path
        task_config['sample_prompts'] = json_path

        # 3. 更新 Task ID
        final_task_id = current_task_id
        if current_task_id == '__NEW__':
            if new_output_name in full_config['qwen']: return jsonify({"status": "error", "message": "Exists"}), 400
            full_config['qwen'][new_output_name] = task_config
            final_task_id = new_output_name
        elif new_output_name != current_task_id:
            if new_output_name not in full_config['qwen']:
                full_config['qwen'][new_output_name] = task_config
                del full_config['qwen'][current_task_id]
                final_task_id = new_output_name

        save_full_yaml(full_config)
        return jsonify({"status": "success", "message": "SAVED", "new_task_id": final_task_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
