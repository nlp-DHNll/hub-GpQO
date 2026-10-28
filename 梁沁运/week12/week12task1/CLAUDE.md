# PROJECT SPEC —— 楼道消防安全隐患识别 Web 应用

## 0. 你的任务
你要生成一个**完整可运行**的项目，包含前端 + 后端，用于：手机拍照 / 上传楼道照片，后端调用本地 **Qwen2.5-VL-3B-Instruct** 模型判断是否存在消防安全隐患，并输出风险等级。**不做模型微调**。

请一次性输出**全部文件**，每个文件用 ` ```文件路径 ``` ` 代码块标出。不要省略、不要写"此处省略"、不要用伪代码。

---

## 1. 硬性约束（必须遵守，不可更改）

- **模型目录**（用户本地已下载）：
  ```
  C:\Users\Hester\Desktop\AI\第12周：多模态大模型和RAG应用\Week12_2026Q2\02-多模态大模型\model\Qwen--Qwen2.5-VL-3B-Instruct
  ```
  - 代码里要做兼容（若路径以 `tokenizer_config.json` 结尾则取父目录）。
  - **只能用 3B**，不要用 7B。
- **运行环境**：Windows 10/11，Python 3.12，可能有 CUDA 也可能没有；`device_map="auto"` 自适应。
- **不做微调**，直接 `from_pretrained` 推理。
- **模型调用方式必须对齐**下面 Notebook 的写法（这是课程参考代码）：
  ```python
  from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
  from qwen_vl_utils import process_vision_info

  model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
      MODEL_DIR, torch_dtype="auto", device_map="auto"
  )
  processor = AutoProcessor.from_pretrained(MODEL_DIR)

  messages = [
      {"role": "system", "content": SYSTEM_PROMPT},
      {"role": "user", "content": [
          {"type": "image", "image": PIL.Image},
          {"type": "text",  "text": USER_PROMPT},
      ]},
  ]
  text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
  image_inputs, video_inputs = process_vision_info(messages)
  inputs = processor(text=[text], images=image_inputs, videos=video_inputs,
                     padding=True, return_tensors="pt").to(device)
  out = model.generate(**inputs, max_new_tokens=N, do_sample=False)
  trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, out)]
  raw = processor.batch_decode(trimmed, skip_special_tokens=True,
                               clean_up_tokenization_spaces=False)[0]
  ```
- **前端同源托管**：后端用 FastAPI 直接服务 `frontend/index.html`，手机访问 `http://<局域网IP>:8000/` 一个地址就能用。前端 fetch 用相对路径 `/api/risk/analyze`，不填绝对地址。
- **手机调相机必须用** `<input type="file" accept="image/*" capture="environment">`。**不要**把 `getUserMedia` 当主路径（手机非 HTTPS 会失败）；`getUserMedia` 只能作为桌面/localhost 的增强入口。

---

## 2. 风险分级标准（这是核心评分点，务必体现在 SYSTEM_PROMPT 里）

风险等级只能取这 4 个字符串之一：`无隐患`、`低风险`、`中等风险`、`高风险`。

| 等级 | 判定依据（以楼道场景为准） |
|---|---|
| 无隐患 | 楼道通畅；无堆积物，或仅有少量不影响通行的非可燃物；无电动车/电池入户；无飞线充电；无明火/烟头；无电气隐患 |
| 低风险 | 有少量普通杂物或可燃物，但未明显阻塞通道，远离火源/电气设备 |
| 中等风险 | 有较多可燃堆积物（纸箱、纸皮、塑料、布料、木质杂物等），通道变窄但**仍可通行**；或存在电动车/电池停放但未见充电；或存在一般电气隐患 |
| 高风险 | 大量可燃物密集堆积、**明显堵塞**疏散通道；或电动车入户/楼道充电/飞线充电；或明火、烟头、燃气罐、私拉乱接电线等直接起火风险 |

规则：
- 模型无法确定时，倾向保守等级，并在 `reason` 中说明建议人工复核。
- 严禁编造图片中不存在的物体。

---

## 3. 目录结构（按此生成，5 + 4 个文件，可以按需调整）

```
project/
├── backend/
│   ├── __init__.py
│   ├── config.py
│   ├── risk_prompt.py
│   ├── qwen_service.py
│   └── app.py
├── frontend/
│   └── index.html
├── run.py
├── requirements.txt
└── README.md
```


---

## 4. 每个文件的规格

### 4.1 `backend/config.py`
集中所有可调项，其余模块只能从这里 import，禁止散落常量。
必须包含：
- `MODEL_DIR`：Path，默认值为上面第 1 节的路径，支持环境变量 `QWEN_MODEL_DIR` 覆盖；若结尾是 `tokenizer_config.json` 则取父目录。
- `BASE_DIR`：项目根（`Path(__file__).resolve().parent.parent`）
- `FRONTEND_DIR = BASE_DIR / "frontend"`
- `MAX_NEW_TOKENS = 768`、`DO_SAMPLE = False`
- `MAX_UPLOAD_MB = 20`
- `HOST = "0.0.0.0"`、`PORT = 8000`

### 4.2 `backend/risk_prompt.py`
只做「提示词 + 输出解析 + 结果归一化」，不碰模型、不碰 FastAPI。
必须导出：
- `RISK_LEVELS: tuple = ("无隐患", "低风险", "中等风险", "高风险")`
- `SYSTEM_PROMPT: str` —— 把第 2 节的风险分级标准完整写进去。
- `build_user_prompt(width: int, height: int) -> str` —— 拼用户提示词，包含：
  - 图像尺寸（告诉模型便于 bbox 定位）
  - "严格只输出一个 JSON 对象，不要 markdown 代码块"
  - 明确的 JSON schema（见第 5 节）
- `parse_and_normalize(raw: str) -> dict` —— 内部做三件事并返回最终 dict：
  1. 从 raw 中解析 JSON（容错：去 ```json 围栏、截取首个 `{` 到末个 `}`、json.loads → ast.literal_eval 兜底）
  2. 归一化：`risk_level` 别名映射（如"中风险"→"中等风险"），非法等级用 `risk_score` 分档兜底并置 `need_manual_review=True`；`risk_score` 裁到 0–100；`is_fire_hazard` 缺省时按等级推；`reason`/`suggestion` 为空时填默认；`hazards` 里的 `bbox_2d` 非 4 个数字则置 None。
  3. 返回字段固定为（**顺序照此**）：
     ```json
     {
       "risk_level": "...",
       "risk_score": 0,
       "is_fire_hazard": false,
       "reason": "...",
       "hazards": [ {"type": "...", "description": "...", "bbox_2d": [x1,y1,x2,y2] | null} ],
       "suggestion": "...",
       "need_manual_review": false,
       "raw": "模型原始输出"
     }
     ```

### 4.3 `backend/qwen_service.py`
只做模型加载和生成。
- 全局单例 + `threading.Lock()` 做懒加载（`load_model()` 幂等）。
- 另一个 `threading.Lock()` 包住 `model.generate`（VL 模型非线程安全）。
- `@torch.inference_mode()` 装饰 `generate`。
- 函数签名：
  ```python
  def load_model() -> None
  def is_ready() -> bool
  def generate(image: PIL.Image.Image, system_prompt: str,
               user_prompt: str, max_new_tokens: int = MAX_NEW_TOKENS) -> str
  ```
- `generate` 内部严格照第 1 节的调用顺序：`apply_chat_template` → `process_vision_info` → `processor(...)` → `model.generate` → trim → `batch_decode`，返回 `output_text[0]`。
- 模型路径不存在时抛清晰异常（`assert` + 中文信息）。

### 4.4 `backend/app.py`
FastAPI 应用。
- `CORSMiddleware`：`allow_origins=["*"]`（作业场景，允许跨域调试；README 里注明生产环境要收窄）。
- `@app.on_event("startup")`：用 `run_in_threadpool(load_model)` 启动时加载模型，失败仅打印日志不崩溃。
- 路由：
  - `GET /health` → `{"status": "ok", "model_ready": bool}`
  - `POST /api/risk/analyze` → `UploadFile` 字段名**必须**是 `file`。
    - 校验 `content_type` 以 `image/` 开头、非空、不超过 `MAX_UPLOAD_MB`
    - `PIL.Image.open(BytesIO(data)).convert("RGB")`
    - 用 `run_in_threadpool` 调推理（阻塞函数不能直接 await）
    - 成功返回：`{"success": True, "filename": ..., **parse_and_normalize(raw)}`
    - 失败：`HTTPException`，中文 detail
  - `GET /` → `FileResponse(FRONTEND_DIR / "index.html")`，404 时给中文 detail。**这个路由必须写在所有 `/api/...` 之后**。
- 不要用 `StaticFiles` mount（只服务单个 index.html 即可）。

### 4.5 `frontend/index.html`
**单文件**，HTML + CSS + JS 内联，无外部 CDN、无构建步骤。

UI 要求（移动优先，max-width 720px 居中）：
1. **顶部**：标题「楼道消防安全隐患识别」+ 副标题一行说明。
2. **图片预览区**（4:3 深色容器，`object-fit: contain`）：
   - 三态切换：空占位 / `<video>` 实时画面 / `<img>` 预览图
   - 隐藏 `<canvas id="captureCanvas">` 供拍照使用
3. **操作按钮行**（`flex-wrap` 换行，按钮 min-width 92px）：
   - 「开启摄像头」（`getUserMedia`，仅在 `window.isSecureContext` 时启用，否则禁用并加 title 提示）
   - 「拍照」（取 `<video>` 帧 → canvas → jpeg blob）
   - 「拍照 / 选择」`<label class="btn-file" for="fileCam">` 包装 `<input id="fileCam" type="file" accept="image/*" capture="environment">` —— 这是**手机主路径**
   - 「从相册」`<input id="fileGallery" type="file" accept="image/*">`
   - 「重来」（清空状态）
4. **「开始识别」** 按钮（主色块，占满宽度），未选图时 disabled；点击后按钮文案变「识别中…」+ 一个小圆点 pulse 动画。
5. **状态行** `#status`：正常 / 红色错误两态。
6. **结果卡片**（初始 `hidden`）：
   - 风险徽章：4 个等级各配一套颜色（绿/蓝/橙/红），未识别时灰色
   - 分数条：0–100，`width` 动画过渡到目标值，颜色跟随等级
   - 「判断原因」/「处置建议」两个 `dt/dd`
   - 「识别到的隐患」`<ul>`，每条 `类型：描述`，橙色背景
   - 「需人工复核」黄色提示条（`need_manual_review === true` 时显示）
   - `<details>` 折叠「查看模型原始输出」

图片处理要求：
- 上传前**必须压缩**：`createImageBitmap(file, {imageOrientation:'from-image'})` 修正 EXIF 方向 → canvas 缩放到长边 ≤ 1600px → `toBlob('image/jpeg', 0.85)`。手机原图 5–10MB，压缩后 ~200–400KB。
- 老浏览器不支持 `createImageBitmap` 时用 `new Image()` 兜底。

请求要求：
- `FormData`，字段名 `file`，相对路径 `/api/risk/analyze`。
- `AbortController` 120 秒超时。
- 后端返回非 2xx 时尝试读 `detail` 字段显示。
- 显示后端返回的 `risk_level / risk_score / reason / suggestion / hazards / need_manual_review / raw`。

其他交互：
- `document.addEventListener('visibilitychange', ...)`，页面切后台自动关闭摄像头流。
- 每次上传新图前 `URL.revokeObjectURL` 旧预览。
- 不要引第三方库（不用 vue/react/jquery/tailwind）。
- 中文 UI，不要英文占位符。

### 4.6 `run.py`
启动脚本。
- Windows 控制台 UTF-8：`sys.stdout.reconfigure(encoding="utf-8")` 放在 try/except 里。
- 打印局域网 IP（UDP socket connect 8.8.8.8 拿本机出口 IP），输出三行：
  ```
  本机访问 : http://127.0.0.1:8000/
  手机访问 : http://<LAN_IP>:8000/   （同一 WiFi）
  接口文档 : http://127.0.0.1:8000/docs
  ```
- `uvicorn.run("backend.app:app", host=HOST, port=PORT, reload=False)`

### 4.7 `requirements.txt`
```
torch
torchvision
transformers>=4.49.0
accelerate
qwen-vl-utils
fastapi
uvicorn[standard]
python-multipart
pillow
```

### 4.8 `README.md`
中文，包含：
1. 项目简介 + 风险分级表（4 行即可）
2. 快速开始（3 步：`pip install -r requirements.txt` → `python run.py` → 打开 `http://127.0.0.1:8000/`）
3. **手机访问注意**：
   - 必须用局域网 IP，不能用 `localhost`
   - Windows 防火墙放行 Python / 8000 端口
   - 手机调相机用页面上的「拍照 / 选择」按钮
4. 接口说明：`POST /api/risk/analyze`、字段 `file`、返回 JSON 示例
5. 如何改提示词（指向 `backend/risk_prompt.py` 的 `SYSTEM_PROMPT`）
6. 显存不足的处理（`device_map="cpu"` 或降低 `MAX_NEW_TOKENS`）

---

## 5. 数据契约（前端 ⇄ 后端）

### 请求
```
POST /api/risk/analyze
Content-Type: multipart/form-data
字段：
  file: <image/jpeg 或 image/png 二进制>
```

### 成功响应（HTTP 200）
```json
{
  "success": true,
  "filename": "capture.jpg",
  "risk_level": "中等风险",
  "risk_score": 62,
  "is_fire_hazard": true,
  "reason": "楼道内堆放了较多纸箱和塑料杂物，通行宽度变窄但仍可通行。",
  "hazards": [
    {"type": "可燃物", "description": "左侧靠墙堆放的纸箱", "bbox_2d": [120, 380, 640, 980]},
    {"type": "堵塞通道", "description": "通道右侧的塑料杂物", "bbox_2d": null}
  ],
  "suggestion": "建议尽快清理可燃堆积物，保持疏散通道畅通，并人工复核。",
  "need_manual_review": false,
  "raw": "模型返回的原始字符串"
}
```

### 错误响应
```json
{"detail": "请上传图片文件"}
```
状态码：400 图片/参数问题，413 超大，500 推理异常。

---

## 6. 模型实际输出的 Prompt 目标（写进 `USER_PROMPT_TEMPLATE`）

模型必须只输出这样的 JSON（前端解析靠这个）：
```json
{
  "risk_level": "无隐患|低风险|中等风险|高风险",
  "risk_score": 0,
  "is_fire_hazard": false,
  "reason": "一两句话",
  "hazards": [
    {"type": "堆积物|可燃物|堵塞通道|电动车/电池|充电/飞线|明火/烟头|电气隐患|其他",
     "description": "描述",
     "bbox_2d": [x1, y1, x2, y2]}
  ],
  "suggestion": "处置建议"
}
```
用户提示词里必须：
- 明确给出图像宽高（`{width} x {height}`），说明 bbox 用原图像素坐标、左上角 (0,0)
- 明确"不要 markdown 代码块、不要解释文字"
- 明确 `hazards` 为空时填 `[]`

---

## 7. 代码风格要求

- 每个文件顶部有简短的中文 docstring，说明职责。
- 全部中文注释、中文错误提示、中文 UI，不要中英混杂。
- 不写无意义的 try/except；`except Exception as e:` 里的 `e` 要么用要么 `_`。
- 不要 print 调试，需要日志用 `print` 只在加载模型和启动时。
- 依赖项：**只用 `requirements.txt` 里的库**。不要引入 `httpx`、`pydantic` 之外的额外包（pydantic 是 fastapi 依赖，可以间接用；不要额外写 schemas 文件）。
- 不要写测试文件、不要写 `.env`、不要写 dockerfile、不要写 CI 配置。

---

## 8. 验收清单（生成代码后自检，并在 README 末尾附上）

- [ ] 目录结构完全按第 3 节
- [ ] `python run.py` 能直接启动，控制台打印本机/手机/文档三个地址
- [ ] `http://127.0.0.1:8000/` 打开就是拍照页，页面不引用任何外部资源
- [ ] `http://127.0.0.1:8000/docs` 能看到两个接口
- [ ] `POST /api/risk/analyze` 用 Postman/curl 传一张图能返回第 5 节的 JSON
- [ ] 手机同 WiFi 打开 `http://<LAN_IP>:8000/`，「拍照 / 选择」能调起相机
- [ ] 摄像头权限被拒时不报红屏，用「拍照 / 选择」可继续
- [ ] 模型输出不是合法 JSON 时，接口仍返回 200 且 `need_manual_review: true`
- [ ] `SYSTEM_PROMPT` 里完整包含第 2 节的 4 档标准
- [ ] 所有路径用 `pathlib.Path`，不用字符串拼 `\\`
- [ ] 没有任何 `...` / `TODO` / `pass  # 省略`

---

## 9. 明确不要做的事

- ❌ 不要给模型做微调 / LoRA / QLoRA
- ❌ 不要用 7B 模型
- ❌ 不要把 `getUserMedia` 当手机主路径
- ❌ 不要引入前端框架、不要写 `vite` / `webpack` 配置
- ❌ 不要写多页前端 / 路由 / 数据库 / 用户系统
- ❌ 不要用 `StaticFiles` 挂载整个 `frontend/`
- ❌ 不要把推理函数写成 `async def`（PIL + transformers 都是阻塞的，用 `run_in_threadpool`）
- ❌ 不要引入 `langchain` / `llamaindex` / `ollama` / `vllm`
- ❌ 不要在 `model.generate` 外面不锁就并发调用

---

请现在开始，有问题可以问我澄清。