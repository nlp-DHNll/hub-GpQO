from sentence_transformers import SentenceTransformer,util

model = SentenceTransformer(r"F:\project\google-bert\models\bge-small-zh-v1.5")

sentences = [
    "我喜欢机器学习",
    "我喜欢深度学习",
    "我今天心情很不错"
]

testSentences = "我今天很开心"

sourceEmbeddings = model.encode(sentences)
testEmbeddings = model.encode(testSentences)
print(f"sourceEmbeddings shape : {sourceEmbeddings}")
print(f"testEmbeddings shape : {sourceEmbeddings}")

#直接匹配相似度：
similarities = model.similarity(sourceEmbeddings,testEmbeddings)
print(similarities)

# 计算余弦相似度
cos_scores = util.cos_sim(testEmbeddings,sourceEmbeddings)[0]
results = []
for index,score in enumerate(cos_scores):
    results.append({
        "text": sentences[index],
        "score" : score
    })

# 数据对象按相似度排序：
results = sorted(results,key=lambda x:x["score"],reverse=True)
print(f"查询的语句是：{testSentences}")
for result in results:
    print(f"比较文本：{result["text"]}, 相似度为：{result["score"]}")


