"""
代码流程：
	运行程序后，首先加载四种分类方法的模型（import 阶段触发）。当客户端发送POST请求后，FastAPI通过data_schema.py文件当中的TextClassifyRequest 自动校验数据类型，校验通过后进入对应的路由函数，路由函数的执行步骤为：
 1. 记录开始时间
 2. 构造初始化的TextClassifyResponse对象
 3. 打印日志
 4. 调用分类函数进行实际分类
 5. 异常记录
 6. 计算耗时
 7. 返回JSON响应

项目源文件作用说明
 根目录文件
 	main.py    -》web服务入口，定义FastAPI应用和4个文本分类POST接口
	data_schema.py	-》数据契约，用 Pydantic 定义请求体 TextClassifyRequest 和响应体 TextClassifyResponse
	config.py		-》统一配置：正则规则字典、12 个类别名、模型权重路径、大模型 API Key / URL / 模型名
	logger.py		-》日志模块
	fastapi_demp.py	-》FastAPI示例demo
	README.md	-》项目说明

model 目录 ： 四种分类算法实现

training_code：离线训练脚本

assets/dataset :训练数据

logs ：训练日志

test ：压测用的data.json请求样本

doc ：项目背景、实施、运维、面试点文档

"""
