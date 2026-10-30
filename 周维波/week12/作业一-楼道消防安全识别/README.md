# 楼道消防安全风险识别（前后端多模态应用）

参考课程《案例-多模态内容理解.ipynb》，构建的带前后端的多模态应用：**网页打开调用手机摄像头拍照 / 上传图片**，后端调用视觉大模型 **ds flash 4.1（DeepSeek V4.1 Flash，模型名 `deepseek-flash`）** 或 **qwen（`qwen-vl-max`，阿里云百炼）**，对楼道照片实时识别消防安全隐患并分级。

## 风险分级定义

| 等级 | 定义 |
| ---- | ---- |
| 高风险 | 楼道中出现电动车、电瓶、飞线充电等可能起火的元素 |
| 中风险 | 楼道中存在大量堆积物严重影响通行，或堆放大量纸箱、木质家具等能造成火势蔓延的堵塞物 |
| 低风险 | 存在楼道堆物现象但不严重 |
| 无风险 | 楼道干净，无堆放物品 |
| 非楼道 | 与楼道无关的图片 |

## 项目结构

```
楼道消防安全识别/
├── server.py              # 后端服务（纯标准库 HTTP，无需额外框架）
├── llm.py                 # 模型调用层：图片归一化 + deepseek / qwen / 演示模式
├── prompt.py              # 消防专家提示词 + 模型输出解析（严格 JSON）
├── config.json            # 服务与模型配置（端口、base_url、模型名）
├── .env                   # API 密钥（自行创建，参考 .env.example）
├── .env.example           # 密钥模板
├── requirements.txt       # 仅 requests + Pillow
├── start_server.bat       # 一键启动脚本
├── tools/self_test.py     # 离线自测脚本（解析/归一化单元测试）
└── frontend/
    ├── index.html         # 前端页面（拍照 + 上传 + 结果展示）
    ├── style.css
    └── app.js
```

## 快速开始

### 1. 安装依赖

```
pip install -r requirements.txt
```

### 2. 配置 API 密钥

把 `.env.example` 复制为 `.env`，填入密钥：

```
DEEPSEEK_API_KEY=sk-...      # https://platform.deepseek.com
DASHSCOPE_API_KEY=sk-...     # https://bailian.console.aliyun.com
```

> 只填一个也能用：前端选择对应模型即可；不想填密钥时前端可选「演示模式」跑通全流程。

### 3. 启动

- 双击 `start_server.bat`，或运行 `python server.py`
- 本机访问：**http://127.0.0.1:8000**
- 手机访问（同一 Wi-Fi）：先 `ipconfig` 查看电脑局域网 IP（如 192.168.x.x），手机浏览器打开 **http://192.168.x.x:8000**

## 功能说明

- **拍照**：手机浏览器通过 `getUserMedia` 调起摄像头实时取景拍照；若页面运行在局域网 `http://IP`（非安全上下文）导致摄像头不可用，会自动改用系统相机（`capture="environment"`）拍摄。
- **上传图片**：从相册或电脑选择图片。
- **模型切换**：ds flash 4.1 / qwen-vl-max / 演示模式，三种可随时切换。
- **结果展示**：五档风险卡片（颜色区分）+ 判断依据 + 模型与耗时，并保留本次会话识别记录。
- **图片处理**：前端 canvas 压缩 + 后端 Pillow 归一化（最长边 1568px、JPEG），控制请求体与 token 费用。

## 后端接口

| 接口 | 方法 | 说明 |
| ---- | ---- | ---- |
| `/api/analyze` | POST | 请求体 `{"provider":"deepseek|qwen|mock","image":"<base64 data URL>"}`；返回 `{ok, category, level, reason, model, latency_ms}` |
| `/api/health` | GET | 服务状态与各模型密钥是否已配置 |

## 常见问题

- **提示「未配置 API Key」**：检查 `.env` 是否创建、变量名是否正确，改完重启服务。
- **手机打不开页面**：确认手机与电脑在同一局域网；Windows 防火墙如拦截 8000 端口，放行 Python 或端口 8000。
- **手机拍照按钮没反应/黑屏**：`http://IP` 下浏览器禁止非加密摄像头，应用已自动切换系统相机；如需网页内取景，可用 `ngrok`/`cloudflared` 或自签 HTTPS 访问。
- **模型输出解析失败**：模型偶发返回非 JSON 文本，后端有容错解析；可重试一次。

## 验证

`python tools/self_test.py` 可离线自测：图片归一化、五档类别归一化、JSON 解析。真实识别需配置密钥后在前端实际拍照验证。
