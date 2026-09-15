###    1、langchain 工具调用 和 llm function call 有什么区别？
- 1 架构不同 llm function call 是大模型内置判断是否使用工具 langchain是通过框架集成使用 bind_tools() 方法将其绑定到模型上
- 2 llm function call需要自定义Schema 工具的名称、描述和参数结构，开发过程相对繁琐。langchain则高度模块化，自动提取函数生成可调用的工具
###  2、 langchain 工具调用 的 速度是受到什么影响？
- 1 框架底层的抽象开销 2 隐式重试机制及错误机制 3 解析方式及多轮推理累积 4 大模型本身的性能配置影响