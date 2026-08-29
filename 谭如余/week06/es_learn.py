from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer

#连接创建es 对象：
es = Elasticsearch("http://localhost:9200")

# 2.加载BGE向量模型（本地）
model = SentenceTransformer(r"F:\project\google-bert\models\bge-small-zh-v1.5")

index_name = "test_index"
# 3.创建索引：ik分词 + dense_vector向量字段
if es.indices.exists(index=index_name):
    es.indices.delete(index=index_name)

mapping = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "ik_smart_analyze": {"type": "ik_smart"},
                "ik_max_analyze": {"type": "ik_max_word"}
            }
        }
    },
    "mappings": {
        "properties": {
            "title": {"type": "text", "analyzer": "ik_max_analyze"},
            "content": {"type": "text", "analyzer": "ik_max_analyze"},
            "category": {"type": "keyword"},   # 用于条件过滤
            "publish_year": {"type": "integer"},# 用于条件过滤
            "vec": {
                "type": "dense_vector",
                "dims": 512,
                "index": True,
                "similarity": "cosine"
            }
        }
    }
}
es.indices.create(index=index_name, body=mapping)

# 准备测试数据
docs = [
    {
        "title": "大模型入门学习",
        "content": "学习大模型、LLM提示词工程，掌握RAG检索增强生成",
        "category": "AI",
        "publish_year": 2025
    },
    {
        "title": "Elasticsearch实战教程",
        "content": "ES全文检索、向量检索，构建本地知识库",
        "category": "技术",
        "publish_year": 2024
    },
    {
        "title": "Python数据分析实践",
        "content": "pandas处理表格数据，机器学习基础",
        "category": "技术",
        "publish_year": 2025
    },
    {
        "title": "人工智能行业发展报告",
        "content": "AGI通用人工智能未来发展趋势",
        "category": "AI",
        "publish_year": 2026
    }
]

# 写入文档，同时生成向量
for idx, doc in enumerate(docs):
    text_for_emb = doc["title"] + "。" + doc["content"]
    emb = model.encode(text_for_emb)
    doc["vec"] = emb
    es.index(index=index_name, id=idx, document=doc)

es.indices.refresh(index=index_name)
print("数据写入完成\n")

# ==========1.全文检索（IK分词）==========
print("=======【1.全文检索】关键词：人工智能=======")
resp1 = es.search(
    index=index_name,
    query={
        "match": {
            "content": "人工智能"
        }
    }
)
for hit in resp1["hits"]["hits"]:
    print(f"score:{hit['_score']}, title:{hit['_source']['title']}")

# ==========2.条件过滤（filter）==========
print("\n=======【2.条件过滤】category=技术，并且publish_year>=2025=======")
resp2 = es.search(
    index=index_name,
    query={
        "bool": {
            "must": [{"match_all": {}}],
            "filter": [
                {"term": {"category": "技术"}},
                {"range": {"publish_year": {"gte": 2025}}}
            ]
        }
    }
)
for hit in resp2["hits"]["hits"]:
    print(f"title:{hit['_source']['title']}, year:{hit['_source']['publish_year']}")

# ==========3.向量检索==========
print("\n=======【3.向量检索】查询文本：本地知识库搭建=======")
query_text = "本地知识库搭建"
query_vec = model.encode(query_text)
resp3 = es.search(
    index=index_name,
    knn={
        "field": "vec",
        "query_vector": query_vec,
        "k": 3,
        "num_candidates": 10
    }
)
for hit in resp3["hits"]["hits"]:
    print(f"score:{hit['_score']:.3f}, title:{hit['_source']['title']}")
