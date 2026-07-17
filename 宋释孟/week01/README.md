# 开发环境部署

我目前使用venv作为虚拟环境,安装了以下依赖参见[requirements](requirements.txt)；
配置好了Codex[image](image.png)

- ***环境搭建***
```bash
# 创建虚拟环境
python3 -m venv dl-env
# 激活（Linux/Mac）
source dl-env/bin/activate
# 激活（Windows）
dl-env\Scripts\activate
# 退出
deactivate
```

- ***包安装***
	- `numpy==1.26.4` 科学计算
	- `pandas==2.2.2`  数据分析
	- `jieba` — 中文分词
	- `matplotlib==3.9.2`  数据可视化
	- `torch torchvision torchaudio` 深度学习框架
	- `gensim` 主题建模
	- `scikit-learn==1.5.1` 机器学习
	- `peft==0.15.0` 模型微调
	- `transformers==4.56.2` HuggingFace 预训练模型
	- `fastapi[standard]` Web API 框架
	- `mypy` — 静态类型检查

```bash
pip install numpy pandas jieba matplotlib scikit-learn peft transformers fastapi[standard] mypy gensim

# PyTorch 单独装
pip install torch torchvision torchaudio
