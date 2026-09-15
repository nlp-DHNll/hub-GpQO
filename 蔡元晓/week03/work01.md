### 安装langchain 和 openai-agent

<img width="960" height="510" alt="P1_install" src="https://github.com/user-attachments/assets/95268a2e-5846-4b3f-b735-6e21f998a7a5" />

### 问题1：LangChain 工具调用和 LLM Function Call 有什么区别？

- LLM Function Call 是大模型自身提供的一种能力，主要解决的是模型如何识别用户意图，并按照指定格式返回需要调用的函数名称和参数。
- LangChain Tool Calling 是基于 Function Call 的框架封装，它不仅包含模型调用工具的能力，还提供了工具注册、工具管理、参数解析、执行流程编排以及 Agent 多轮调用等能力。
- Function Call 负责“模型决定调用什么工具”，而 LangChain Tool Calling 负责“管理整个工具调用流程”。

### 问题2：LangChain 工具调用速度受到哪些因素影响？
LangChain Tool Calling 的耗时主要不是来自 LangChain 框架本身，而是受到以下几个因素影响：
- 第一，大模型推理速度，包括模型规模、上下文长度、Token数量等，这是主要影响因素。
- 第二，工具执行耗时，例如数据库查询、API请求、搜索服务等外部调用速度。
- 第三，Agent调用次数，如果任务需要多轮 ReAct 推理，多次调用工具，会增加整体响应时间。
- 第四，Prompt和上下文大小，包括工具描述、历史消息、RAG召回内容等，都会影响模型处理时间。

优化方向主要是选择合适模型、减少无效工具调用、优化工具接口和控制上下文长度。
