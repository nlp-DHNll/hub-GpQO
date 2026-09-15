from sentence_transformers import SentenceTransformer
import torch
model = SentenceTransformer("../BAAI/bge-small-zh-v1.5/")

query = "我今天很开心"

database = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]

query_embeddings = model.encode(query)

database_embeddings = model.encode(database)

similarities = model.similarity(query_embeddings, database_embeddings)
best_idx = torch.argmax(similarities[0]).item()
best_score = similarities[0][best_idx]
best_text = database[best_idx]
print(f"相似度矩阵: {similarities}, 最相似文本: {best_text}, 相似度分数: {best_score:.4f}")
