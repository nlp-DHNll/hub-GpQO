# 楼道消防隐患识别网页应用实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 按任务执行；每项工作完成后核对交付内容。

**目标：** 构建手机可拍照/上传楼道照片并由 DeepSeek Flash 识别消防风险的独立中文网页应用。

**架构：** FastAPI 托管静态网页和图片识别接口。后端校验并规范图片后，通过 OpenAI 兼容 SDK 将图片以 base64 data URL 发送到 DeepSeek Chat Completions API，校验模型结构化结果再返回网页。

**技术栈：** Python、FastAPI、Uvicorn、OpenAI Python SDK、Pillow、原生 HTML/CSS/JavaScript。

**设计文档：** `docs/superpowers/specs/2026-10-28-corridor-fire-risk-design.md`

## 全局约束

- 所有说明文档和代码注释使用中文。
- API 密钥只从服务端环境变量读取，不写入网页或源码。
- 不持久保存上传图片，不增加数据库或用户系统。
- 按五类规则返回：非楼道、无风险、低风险、中风险、高风险。
- API 错误、上传校验错误向用户展示清楚的中文提示。
- multipart 解析前限制请求体大小；按 IP 每分钟最多识别 10 次，同时最多进行 2 次模型调用。

## 文件结构

- `app.py`：FastAPI 应用、请求体/上传校验、按 IP 频率与并发限制、DeepSeek 调用、结果解析和 API 路由。
- `static/index.html`：中文移动优先页面、拍照/相册选择、预览和结果呈现。
- `requirements.txt`：运行依赖。
- `.env.example`：服务端配置示例，不含真实密钥。
- `.gitignore`：忽略虚拟环境、缓存与本地 `.env`。
- `README.md`：中文安装、配置、启动和手机访问说明。

## 重点检查项

- 浏览器无法直接打开摄像头时仍可从相册选图；由移动端文件输入属性提供相机入口。
- 非图片、损坏图片及超出大小上限的上传返回可读错误。
- API Key 缺失、DeepSeek 超时/错误、模型输出格式不合规都显示中文错误。
- 模型把模糊照片判断为安全时，应要求人工复核，不暗示确定安全。
- 手机布局、按钮忙碌状态、重复提交与错误恢复都可用。

## 实施任务

### 任务 1：后端识别接口

**文件：** 新建 `app.py`、`requirements.txt`、`.env.example`、`.gitignore`。

- 创建 FastAPI 服务并挂载 `static/` 页面目录。
- 实现 `POST /api/analyze`，接收 multipart 图片；限制文件大小，使用 Pillow 验证并将图片统一转为 JPEG，避免传递损坏内容或 EXIF 元数据。
- 从环境变量读取 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`；默认模型为 `deepseek-flash`。
- 使用官方支持的 OpenAI 兼容图片输入格式，提示词严格约束风险类别、理由、建议、不确定性字段；从模型内容提取 JSON 并校验类别与字段。
- 返回 `{category, level, reason, suggestion, needs_manual_review}`；所有异常映射到中文 HTTP 错误。
- 注释只用中文，密钥配置不写进任何前端响应。

### 任务 2：移动网页交互

**文件：** 新建 `static/index.html`。

- 构建适配窄屏的中文页面，说明拍摄取景建议与风险判定口径。
- 提供带 `accept="image/jpeg,image/png,image/webp"` 和 `capture="environment"` 的拍照/选图入口、图片预览、重新选择、识别按钮。
- 使用 `fetch` 上传 multipart 图片；显示加载状态，防重复提交，并渲染等级、判断依据、建议与人工复核提示。
- 处理无文件、接口错误、非 JSON 响应等状态，支持用户重新识别。
- 页面代码注释使用中文，键盘可操作并提供可读的状态提示。

### 任务 3：中文使用文档

**文件：** 新建 `README.md`。

- 说明 Python 版本、安装命令、复制 `.env.example` 并设置密钥、启动命令。
- 说明电脑本机访问和手机同一 Wi-Fi 下通过电脑局域网 IP 访问的方法。
- 解释五类风险规则、图片隐私处理方式、模型辅助判断的局限及常见错误。

### 任务 4：交付核对

- 对照设计文档核对前端拍照/上传、五类结果、配置说明、隐私边界及中文注释。
- 不增加或运行自动化测试；以代码审阅确认接口字段、依赖与启动说明一致。
