"""
1、 langchain 工具调用 和 llm function call 有什么区别？
	
    llm function call 的工作流程是选择工具，然后得到工具调用方式，然后再执行；langchain 自动进行工具的选择，工具的调用，工具的执行，并且对最终的结果调用大模型做总结。

2、 langchain 工具调用 的 速度是受到什么影响？
    
    受工具本身复杂度和大模型调用速度的影响



"""