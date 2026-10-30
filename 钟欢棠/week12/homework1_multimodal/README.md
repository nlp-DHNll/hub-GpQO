# 作业1：楼道消防安全风险识别（前后端多模态应用）

前端网页调用手机/电脑摄像头拍照并上传图片，后端调用视觉大模型（通义千问 VL / 兼容 DeepSeek 的视觉网关）对照片做实时消防隐患分级。

## 风险分级标准

| 等级 | 判定依据 |
| --- | --- |
| 🔴 高风险 | 出现电动车、电瓶（蓄电池）、飞线充电、私拉电线等可能直接起火的元素 |
| 🟠 中风险 | 大量堆积物严重影响通行，或堆放大量纸箱、木质家具等易燃堵塞物 |
| 🟡 低风险 | 存在楼道堆物但不严重，对通行影响较小 |
| 🟢 无风险 | 楼道干净整洁，无堆放物品 |
| ⚪ 非楼道 | 图片与楼道/公共通道无关 |

## 目录结构

```
homework1_multimodal/
├── backend/
│   ├── app.py          # FastAPI 服务（API + 托管前端）
│   ├── config.py       # 配置（模型/密钥从环境变量读取）
│   ├── multimodal.py  # 视觉识别核心逻辑（LangChain + 结构化输出）
│   └── requirements.txt
└── frontend/
    └── index.html      # 摄像头拍照 + 上传 + 风险展示
```

## 运行步骤

1. 安装依赖
```bash
cd backend
pip install -r requirements.txt
```

2. 配置环境变量（以通义千问 VL 为例，默认即可）
```bash
export VISION_API_KEY="你的DashScope密钥"
# 如需切换模型/网关：
export VISION_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export VISION_MODEL="qwen-vl-max-latest"
```

3. 启动服务
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

4. 浏览器打开 `http://<本机IP>:8000/`
   - 手机端：必须与后端同局域网，且通过 `http://<电脑IP>:8000` 或 https 访问，才能调用摄像头；
   - 点击「开摄像头」授权后「拍照识别」，或用「从相册选择」直接上传图片。

## 说明

- 后端使用 LangChain 的 `ChatOpenAI`（OpenAI 兼容接口）发送包含图片的多模态消息，并通过 `with_structured_output` 让模型直接返回结构化风险报告；若端点不支持 function calling，则降级为 JSON 模式解析。
- 前端用 `getUserMedia` 获取摄像头流，拍照经 `<canvas>` 转 JPEG 上传；也支持 `capture="environment"` 直接调起手机后置摄像头。
- 提示：DeepSeek 官方接口本身无视觉能力，如使用 "ds flash" 类模型需接入支持视觉的兼容网关；推荐默认使用通义千问 VL。
