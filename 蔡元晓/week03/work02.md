### 项目整体流程说明

该项目以 `main.py` 作为服务入口，通过 **FastAPI** 接收用户请求。
利用 `data_schema.py` 完成请求参数校验以及返回数据格式定义。
调用不同的意图识别模型完成文本分类，包括：
- regex（规则匹配）
- tfidf（机器学习分类）
- bert（深度学习分类）
- gpt（大语言模型分类）

`config.py` 提供模型路径、类别信息以及大模型相关配置。
`logger.py` 负责记录系统运行日志、请求信息和异常信息。
最终将分类结果通过 FastAPI 接口返回给用户。


### FastAPI 请求处理流程及文件作用说明

```text
用户请求
    ↓
【main.py】
FastAPI 服务接收 HTTP 请求
    ↓
【data_schema.py】
使用 TextClassifyRequest 进行请求参数校验
    ↓
【main.py】
根据接口类型调用对应分类方法
    ↓
【model 模块】
调用具体意图识别模型
(regex / tfidf / bert / gpt)
    ↓
【config.py】
读取模型配置、类别配置等信息
    ↓
【main.py】
获取分类结果，封装 TextClassifyResponse
    ↓
【data_schema.py】
定义返回数据格式
    ↓
【logger.py】
记录请求信息、运行状态和异常信息
    ↓
返回 JSON 结果给用户
