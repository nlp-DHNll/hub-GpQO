from sentence_transformers import SentenceTransformer

model = SentenceTransformer("../../models/BAAI/bge-small-zh-v1.5/")

query = "我今天很开心"
data = ["我喜欢机器学习","我喜欢深度学习","我今天心情很不错"]

data_embeddings = model.encode(data, normalize_embeddings=True)
query_embedding = model.encode(query, normalize_embeddings=True)

similarity_scores = query_embedding @ data_embeddings.T
scores = similarity_scores.tolist()


print(f"查询文本: 【{query}】\n")
print("各候选文本与查询的相似度：")
for item, score in zip(data, scores):
    print(f"  {item}  -->  相似度: {score:.4f}")
