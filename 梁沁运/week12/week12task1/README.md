# 🧯 楼道消防安全隐患识别

基于 **Qwen2.5-VL-3B-Instruct** 多模态大模型的楼道消防安全隐患自动识别 Web 应用。手机拍照或上传楼道照片后，AI 自动分析是否存在消防安全隐患并输出风险等级与处置建议。

## 风险分级

| 等级 | 判定依据 |
|------|----------|
| 无隐患 | 楼道通畅，无堆积物，无电动车/电池，无飞线充电，无明火/烟头，无电气隐患 |
| 低风险 | 少量普通杂物或可燃物，未明显阻塞通道，远离火源/电气设备 |
| 中等风险 | 较多可燃堆积物（纸箱、塑料、布料等），通道变窄但可通行；或有电动车停放未见充电 |
| 高风险 | 大量可燃物堵塞疏散通道；电动车入户充电/飞线充电；明火、烟头、燃气罐等直接起火风险 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python run.py
```

### 3. 打开页面

浏览器访问 `http://127.0.0.1:8000/`

## 手机访问注意

- **必须使用局域网 IP**，不能用 `localhost`（控制台启动时会打印手机访问地址）
- **Windows 防火墙**需要放行 Python 进程 / 8000 端口，否则手机无法连接
- **手机调相机**请使用页面上的「拍照 / 选择」按钮（该按钮使用 `<input capture="environment">`，兼容手机非 HTTPS 环境）
- 「开启摄像头」按钮仅在 HTTPS 或 localhost 环境下可用（手机 HTTP 访问会失败，这是浏览器的安全限制）

## 接口说明

### `POST /api/risk/analyze`

上传图片进行消防安全隐患分析。

- **Content-Type**: `multipart/form-data`
- **字段**: `file` — 图片文件（JPEG / PNG）

**成功响应示例**：

```json
{
  "success": true,
  "filename": "corridor.jpg",
  "risk_level": "中等风险",
  "risk_score": 62,
  "is_fire_hazard": true,
  "reason": "楼道内堆放了较多纸箱和塑料杂物，通行宽度变窄但仍可通行。",
  "hazards": [
    {"type": "可燃物", "description": "左侧靠墙堆放的纸箱", "bbox_2d": [120, 380, 640, 980]}
  ],
  "suggestion": "建议尽快清理可燃堆积物，保持疏散通道畅通。",
  "need_manual_review": false,
  "raw": "模型原始输出字符串"
}
```

### `GET /health`

健康检查，返回模型就绪状态。

### `GET /`

返回前端页面 `index.html`。

### `GET /docs`

Swagger UI 交互式 API 文档。

## 如何修改风险判定逻辑

风险分级标准和提示词集中在 `backend/risk_prompt.py` 中：

- 修改风险等级判定标准 → 编辑 `SYSTEM_PROMPT`
- 调整输出 JSON 格式要求 → 编辑 `build_user_prompt()`
- 修改解析/归一化逻辑 → 编辑 `parse_and_normalize()`

无需改模型代码。

## 显存不足的处理

如果显卡显存不足以加载 3B 模型（约需 6–8 GB），有以下方案：

1. **强制 CPU 推理**：设置环境变量 `CUDA_VISIBLE_DEVICES=""` 或修改 `backend/qwen_service.py` 中 `from_pretrained` 的 `device_map` 为 `"cpu"`
2. **降低最大生成长度**：修改 `backend/config.py` 中 `MAX_NEW_TOKENS` 为更小值（如 384）以节省推理时的 KV cache 显存
3. **使用半精度**：`torch_dtype="auto"` 已自适应，若模型支持会自动用 `float16`/`bfloat16` 降低显存占用

## 验收清单

- [ ] 目录结构完全按第 3 节
- [ ] `python run.py` 能直接启动，控制台打印本机/手机/文档三个地址
- [ ] `http://127.0.0.1:8000/` 打开就是拍照页，页面不引用任何外部资源
- [ ] `http://127.0.0.1:8000/docs` 能看到两个接口
- [ ] `POST /api/risk/analyze` 用 Postman/curl 传一张图能返回第 5 节的 JSON
- [ ] 手机同 WiFi 打开 `http://<LAN_IP>:8000/`，「拍照 / 选择」能调起相机
- [ ] 摄像头权限被拒时不报红屏，用「拍照 / 选择」可继续
- [ ] 模型输出不是合法 JSON 时，接口仍返回 200 且 `need_manual_review: true`
- [ ] `SYSTEM_PROMPT` 里完整包含第 2 节的 4 档标准
- [ ] 所有路径用 `pathlib.Path`，不用字符串拼 `\`
- [ ] 没有任何 `...` / `TODO` / `pass  # 省略`