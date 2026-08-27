from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer

# 连接 ES
es = Elasticsearch("http://localhost:9200")

# 加载向量模型（请确认路径正确）
model = SentenceTransformer("e:/demo/study/ES/Model/bge-small-zh-v1.5")

# 用户输入
query_text = "如何给手机充电"
filename_filter = "汽车知识手册.pdf"   # 可选，设为 None 则不过滤

# 生成查询向量
query_vector = model.encode(query_text).tolist()

# 1. 全文检索（BM25）
bm25_query = {
    "bool": {
        "must": [{"match": {"content": query_text}}],
        "filter": [{"term": {"filename": filename_filter}}] if filename_filter else []
    }
}
bm25_res = es.search(index="pdf_pages_vector", query=bm25_query, size=3)
print("=== 全文检索结果 ===")
for hit in bm25_res["hits"]["hits"]:
    src = hit["_source"]
    print(f"页码: {src['page_number']}, 得分: {hit['_score']:.4f}, 内容: {src['content'][:50]}...")

# 2. 向量检索（kNN）
knn_query = {
    "knn": {
        "field": "content_vector",
        "query_vector": query_vector,
        "k": 3,
        "filter": [{"term": {"filename": filename_filter}}] if filename_filter else []
    }
}
knn_res = es.search(index="pdf_pages_vector", query=knn_query, size=3)
print("\n=== 向量检索结果 ===")
for hit in knn_res["hits"]["hits"]:
    src = hit["_source"]
    print(f"页码: {src['page_number']}, 得分: {hit['_score']:.4f}, 内容: {src['content'][:50]}...")