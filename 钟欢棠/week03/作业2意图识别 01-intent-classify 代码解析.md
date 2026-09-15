## 一、项目概述

`01-intent-classify` 是一个**文本意图分类服务**，基于 FastAPI 构建，提供 4 种不同策略的意图分类 API。12 类意图包括：`Travel-Query`（旅游查询）、`Music-Play`（音乐播放）、`FilmTele-Play`（影视播放）、`Video-Play`（视频播放）、`Radio-Listen`（广播收听）、`HomeAppliance-Control`（家电控制）、`Weather-Query`（天气查询）、`Alarm-Update`（闹钟更新）、`Calendar-Query`（日历查询）、`TVProgram-Play`（电视节目播放）、`Audio-Play`（音频播放）、`Other`（其他）。

---

## 二、源文件清单及作用

### 顶层文件

| 文件                                   | 作用                                                                                                                                                                           |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[main.py](main.py)`                 | **服务入口**。FastAPI 应用定义，注册 4 个 POST 路由，分别对应 regex/tfidf/bert/gpt 四种分类策略。统一请求-响应处理模板：接收 `TextClassifyRequest` → 调用模型 → 填充 `TextClassifyResponse` → 返回                           |
| `[config.py](config.py)`             | **全局配置**。定义正则规则字典 `REGEX_RULE`、12 类意图名列表 `CATEGORY_NAME`、模型文件路径、大模型 API 的 URL/Key/ModelName                                                                                  |
| `[data_schema.py](data_schema.py)`   | **数据模型**（Pydantic）。`TextClassifyRequest`（请求体：request_id + request_text）和 `TextClassifyResponse`（响应体：request_id + request_text + classify_result + classify_time + error_msg） |
| `[logger.py](logger.py)`             | **日志模块**。配置 logging，同时输出到 `[app.log](app.log)` 文件和控制台                                                                                                                        |
| `[fastapi_demp.py](fastapi_demp.py)` | **FastAPI 教学 demo**（与主项目无关）。演示 `@app.get("/")` 和 `@app.get("/items/{item_id}")` 基础路由                                                                                         |
| `[README.md](README.md)`             | **项目说明**。记录启动命令、压测命令、curl 调用示例                                                                                                                                               |

### `model/` — 四种分类策略

|文件|策略|核心逻辑|
|---|---|---|
|`[regex_rule.py](regex_rule.py)`|**正则规则**|启动时预编译正则。匹配 `REGEX_RULE` 中的关键词（如"播放""电视剧"→FilmTele-Play），命中则返回对应类别，否则返回 `Other`|
|`[tfidf_ml.py](tfidf_ml.py)`|**TF-IDF + 机器学习**|启动时加载 `joblib` 模型（TF-IDF 向量器 + LinearSVC 分类器）。推理时用 jieba 分词+去停用词 → TF-IDF 向量化 → SVM 预测|
|`[bert.py](bert.py)`|**BERT 深度学习**|启动时加载 `bert-base-chinese` 预训练模型 + 微调权重。推理时 tokenize → DataLoader 批处理 → 前向传播 → argmax 取 logits 最大值索引 → 映射到类别名|
|`[prompt.py](prompt.py)`|**大模型（LLM）**|启动时加载训练集 + TF-IDF 向量器。推理时用 TF-IDF 相似度检索训练集中 Top-10 最相似样本作为 Few-shot 示例 → 拼入 Prompt 模板 → 调用阿里百炼 DashScope 的 `qwen-plus` 模型（OpenAI 兼容接口）|

### `training_code/` — 模型训练脚本

|文件|作用|
|---|---|
|`[train_tfidf.py](train_tfidf.py)`|训练 TF-IDF + LinearSVC 模型，保存为 `[assets/weights/tfidf_ml.pkl](assets/weights/tfidf_ml.pkl)`|
|`[train_bert.py](train_bert.py)`|微调 `bert-base-chinese`（12 分类），保存最佳模型权重为 `[assets/weights/bert.pt](assets/weights/bert.pt)`|

### `assets/` — 数据和模型资产

|路径|内容|
|---|---|
|`[dataset/dataset.csv](dataset/dataset.csv)`|训练数据（文本 \t 标签）|
|`[dataset/baidu_stopwords.txt](dataset/baidu_stopwords.txt)`|百度中文停用词表|
|`[weights/tfidf_ml.pkl](weights/tfidf_ml.pkl)`|训练好的 TF-IDF+SVM 模型|
|`[weights/bert.pt](weights/bert.pt)`|微调后的 BERT 权重|
|`models/bert-base-chinese/`|预训练的 BERT 中文模型|

### `doc/` — 文档

|文件|内容|
|---|---|
|`01_项目背景文档.md`|项目背景|
|`02_项目实施文档.md`|实施细节|
|`03_项目运维文档.md`|运维说明|
|`04_项目面试点.md`|面试要点|

---

## 三、请求 → 响应完整流程图（自然语言）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FASTAPI 服务启动阶段                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. Python 解释器执行 main.py                                           │
│     │                                                                    │
│     ├─ 导入 config.py → 读取 REGEX_RULE、CATEGORY_NAME、各路径/密钥       │
│     ├─ 导入 logger.py → 初始化 logging（文件 + 控制台双输出）              │
│     ├─ 导入 data_schema.py → 注册 Pydantic 请求/响应模型                  │
│     │                                                                    │
│     ├─ 导入 model/regex_rule.py                                         │
│     │   └─ 模块级代码执行：遍历 REGEX_RULE，预编译正则表达式对象            │
│     │                                                                   │
│     ├─ 导入 model/tfidf_ml.py                                           │
│     │   └─ 模块级代码执行：joblib.load() 加载 TF-IDF+SVM 模型到内存        │
│     │      从远程读取百度停用词表                                          │
│     │                                                                   │
│     ├─ 导入 model/bert.py                                               │
│     │   └─ 模块级代码执行：                                               │
│     │       - 检测 CUDA/CPU 设备                                         │
│     │       - 加载 bert-base-chinese tokenizer                          │
│     │       - 加载预训练 BERT 模型                                       │
│     │       - load_state_dict 加载微调权重                                │
│     │       - model.to(device) 移到 GPU/CPU                              │
│     │                                                                   │
│     ├─ 导入 model/prompt.py                                             │
│     │   └─ 模块级代码执行：                                               │
│     │       - 读取训练集 CSV → train_data                                │
│     │       - 加载 TF-IDF 向量器                                         │
│     │       - 对全部训练文本做 TF-IDF 变换 → train_tfidf（用于相似度检索）   │
│     │       - 初始化 OpenAI client（指向阿里百炼 DashScope）               │
│     │                                                                   │
│     └─ app = FastAPI() → 注册 4 条路由                                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                       HTTP 请求到达 → 响应返回                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  客户端                                                                  │
│  │                                                                      │
│  │  POST /v1/text-cls/{regex|tfidf|bert|gpt}                           │
│  │  Body: {"request_id": "abc", "request_text": "帮我播放周杰伦的歌曲"}    │
│  │                                                                      │
│  ▼                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  FastAPI 框架层                                               │       │
│  │                                                              │       │
│  │  1. HTTP 请求解析                                             │      │
│  │     ├─ 解析 URL 路径，匹配路由                                  │      │
│  │     │   /v1/text-cls/regex  → regex_classify()               │      │
│  │     │   /v1/text-cls/tfidf → tfidf_classify()                │      │
│  │     │   /v1/text-cls/bert  → bert_classify()                 │      │
│  │     │   /v1/text-cls/gpt   → gpt_classify()                  │      │
│  │     │                                                        │      │
│  │     └─ 2. Pydantic 请求体验证                                  │      │
│  │         ├─ JSON → TextClassifyRequest 对象                    │      │
│  │         ├─ request_id: 必须是 str                             │      │
│  │         └─ request_text: 必须是 str 或 List[str]              │      │
│  │                                                              │      │
│  └──────────────────────────────────────────────────────────────┘       │
│  │                                                                      │
│  │  传入 TextClassifyRequest 对象                                        │
│  ▼                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  路由处理函数（以 regex 为例，四种策略结构一致）                   │       │
│  │                                                              │       │
│  │  3. 记录开始时间 start_time = time.time()                      │       │
│  │                                                              │       │
│  │  4. 初始化响应对象 TextClassifyResponse(                       │       │
│  │       request_id   = req.request_id,                          │       │
│  │       request_text = req.request_text,                        │       │
│  │       classify_result = "",     ← 占位                        │       │
│  │       classify_time   = 0,      ← 占位                        │       │
│  │       error_msg       = ""      ← 占位                        │       │
│  │     )                                                        │       │
│  │                                                              │       │
│  │  5. logger.info() 记录请求日志                                  │       │
│  │                                                              │       │
│  │  6. try:                                                     │       │
│  │       ┌─────────────────────────────────────────────────┐     │       │
│  │       │  调用对应模型函数（四种策略发散）                     │     │       │
│  │       │                                                  │     │       │
│  │       │  【策略A - regex】                                │     │       │
│  │       │  model_for_regex(request_text)                   │     │       │
│  │       │   ├─ 若 request_text 是 str:                     │     │       │
│  │       │   │   遍历预编译的正则 → findall()                │     │       │
│  │       │   │   命中 → 加入结果列表                        │     │       │
│  │       │   │   无命中 → 返回 ["Other"]                    │     │       │
│  │       │   └─ 若 request_text 是 list:                    │     │       │
│  │       │       逐条文本匹配 → 返回类别列表                 │     │       │
│  │       │                                                  │     │       │
│  │       │  【策略B - TF-IDF】                               │     │       │
│  │       │  model_for_tfidf(request_text)                   │     │       │
│  │       │   ├─ jieba.lcut() 分词                          │     │       │
│  │       │   ├─ 过滤停用词                                  │     │       │
│  │       │   ├─ tfidf.transform() 向量化                    │     │       │
│  │       │   └─ model.predict() → 返回类别名列表             │     │       │
│  │       │                                                  │     │       │
│  │       │  【策略C - BERT】                                 │     │       │
│  │       │  model_for_bert(request_text)                    │     │       │
│  │       │   ├─ tokenizer() 编码（truncation + padding）    │     │       │
│  │       │   ├─ 构建 NewsDataset → DataLoader(batch=16)     │     │       │
│  │       │   ├─ model.eval() + torch.no_grad() 推理         │     │       │
│  │       │   ├─ argmax(logits) 取预测索引                    │     │       │
│  │       │   └─ CATEGORY_NAME[idx] → 类别名列表              │     │       │
│  │       │                                                  │     │       │
│  │       │  【策略D - LLM/GPT】                              │     │       │
│  │       │  model_for_gpt(request_text)                     │     │       │
│  │       │   ├─ tfidf.transform() 向量化请求文本              │     │       │
│  │       │   ├─ 计算与训练集的余弦相似度（内积）                 │     │       │
│  │       │   ├─ 取 Top-10 最相似训练样本                      │     │       │
│  │       │   ├─ 拼入 PROMPT_TEMPLATE（Few-shot）              │     │       │
│  │       │   ├─ client.chat.completions.create()             │     │       │
│  │       │   │   → 阿里百炼 DashScope / qwen-plus            │     │       │
│  │       │   └─ 提取 response.choices[0].message.content     │     │       │
│  │       └─────────────────────────────────────────────────┘     │       │
│  │                                                              │       │
│  │     7. response.classify_result = 模型返回的类别                │       │
│  │        response.error_msg = "ok"                               │       │
│  │                                                              │       │
│  │     except Exception:                                        │       │
│  │     8. response.classify_result = ""                          │       │
│  │        response.error_msg = traceback.format_exc()  ← 异常堆栈  │       │
│  │                                                              │       │
│  │  9. response.classify_time = round(time.time() - start, 3)   │       │
│  │                                                              │       │
│  │  10. return response                                         │       │
│  └──────────────────────────────────────────────────────────────┘       │
│  │                                                                      │
│  │  返回 TextClassifyResponse 对象                                       │
│  ▼                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  FastAPI 框架层                                               │       │
│  │                                                              │       │
│  │  11. Pydantic 序列化：TextClassifyResponse → JSON              │      │
│  │  12. HTTP Response 返回给客户端                                │      │
│  └──────────────────────────────────────────────────────────────┘       │
│  │                                                                      │
│  ▼                                                                      │
│  客户端收到 JSON 响应：                                                   │
│  {                                                                      │
│    "request_id": "abc",                                                 │
│    "request_text": "帮我播放周杰伦的歌曲",                                 │
│    "classify_result": "Music-Play",                                     │
│    "classify_time": 0.234,                                              │
│    "error_msg": "ok"                                                    │
│  }                                                                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 四、关键设计要点

1. **模块级加载（启动时一次性加载）**：每个 `model/*.py` 在 `import` 时就完成模型加载（正则编译、TF-IDF 模型反序列化、BERT 权重加载、训练集 TF-IDF 矩阵计算），避免每次请求重复加载。这是 AI 推理服务的常见模式。
    
2. **统一的请求/响应契约**：4 种策略共用 `TextClassifyRequest` / `TextClassifyResponse`，路由处理函数的代码结构完全一致（计时 → 初始化响应 → try 调用模型 → 填充结果/异常 → 返回），差异仅在于调用哪个模型函数。
    
3. **四种策略形成难度梯度**：正则（无机器学习）→ TF-IDF+SVM（传统 ML）→ BERT（深度学习微调）→ LLM Few-shot（大模型提示工程），展示了同一任务的不同技术方案。
    
4. **LLM 策略的 Few-shot 设计**：不是简单的 zero-shot 调大模型，而是用 TF-IDF 向量相似度从训练集中检索 Top-10 最相似样本作为参考例子，拼入 Prompt，属于 **检索增强生成（RAG）** 的轻量应用。
    
5. **异常处理**：`traceback.format_exc()` 把完整堆栈写进 `error_msg` 返回给客户端，方便调试但生产环境需注意信息泄露。