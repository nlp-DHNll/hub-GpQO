# 车载意图识别系统（Vibe Coding 重写版）

面向汽车行业的**意图识别**（文本分类）系统，可应用于智能座舱语音助手、智能客服等场景。
本项目为作业 2 的 vibe coding 产物，从零实现了四条技术路线，通过分层架构提供统一的 RESTful API。

**典型场景：**
- "帮我播放周杰伦的歌曲" → `Music-Play`
- "把空调调到26度" → `HomeAppliance-Control`
- "导航到最近的加油站" → `Travel-Query`

---

## 技术路线

| 路线 | 精度 | 速度 | 训练 | GPU | 定位 |
|------|------|------|------|-----|------|
| 正则表达式 (Regex) | ~70% | ~0.1ms | 无需 | 无需 | 快速关键词匹配 |
| TF-IDF + LinearSVM | ~80% | ~2ms | 需要 | 无需 | 轻量级主力 |
| BERT 微调 | ~95% | ~40ms | 需要 | 推荐 | 高精度主力 |
| LLM + Few-shot | ~95% | ~400ms | 少量即可 | 无需 | API 兜底 / 无 GPU 方案 |

---

## 项目结构

```
02-intent-classify/
├── main.py                    # API 服务入口（FastAPI，4 个接口）
├── data_schema.py             # 请求/响应数据模型（Pydantic）
├── config.py                  # 全局配置（规则、类别、路径、LLM 参数）
├── logger.py                  # 日志配置
├── requirements.txt           # 依赖清单
├── model/                     # 模型推理引擎（4 条技术路线）
│   ├── regex_rule.py          # 正则规则引擎
│   ├── tfidf_ml.py            # TF-IDF + SVM 引擎
│   ├── bert.py                # BERT 引擎（惰性加载）
│   └── prompt.py              # 大模型 few-shot 引擎
├── training_code/             # 模型训练脚本
│   ├── train_tfidf.py         # 训练 TF-IDF + SVM
│   └── train_bert.py          # 微调 BERT
├── assets/
│   ├── dataset/               # 数据集 & 停用词表
│   └── weights/               # 训练产出的模型权重
└── test/                      # 测试数据
    └── data.json
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 训练模型

```bash
# TF-IDF + SVM（无需 GPU，几秒钟完成）
python training_code/train_tfidf.py

# BERT 微调（需先下载 bert-base-chinese 到 assets/models/，推荐 GPU）
python training_code/train_bert.py
```

### 3. 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 4. 调用接口

```bash
# 正则（单条）
curl -X POST 'http://127.0.0.1:8000/v1/text-cls/regex' \
  -H 'Content-Type: application/json' \
  -d '{"request_id": "001", "request_text": "帮我播放周杰伦的歌曲"}'

# TF-IDF（批量）
curl -X POST 'http://127.0.0.1:8000/v1/text-cls/tfidf' \
  -H 'Content-Type: application/json' \
  -d '{"request_id": "002", "request_text": ["打开空调", "导航到公司"]}'
```

---

## API 接口

| 端点 | 模型 | 说明 |
|------|------|------|
| `POST /v1/text-cls/regex` | 正则规则 | 关键词快速匹配 |
| `POST /v1/text-cls/tfidf` | TF-IDF + SVM | 轻量级统计分类 |
| `POST /v1/text-cls/bert` | BERT | 深度语义分类 |
| `POST /v1/text-cls/gpt` | 大模型 | LLM few-shot 分类 |

### 请求格式

```json
{
  "request_id": "可选，方便调试",
  "request_text": "字符串 或 字符串列表"
}
```

### 响应格式

```json
{
  "request_id": "原请求ID",
  "request_text": "原请求文本",
  "classify_result": "分类结果",
  "classify_time": 0.023,
  "error_msg": "ok"
}
```

### 支持分类类别

`Travel-Query`、`Music-Play`、`FilmTele-Play`、`Video-Play`、`Radio-Listen`、
`HomeAppliance-Control`、`Weather-Query`、`Alarm-Update`、`Calendar-Query`、
`TVProgram-Play`、`Audio-Play`、`Other`，共 12 类。
