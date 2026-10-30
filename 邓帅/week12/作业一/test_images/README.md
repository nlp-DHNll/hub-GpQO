# 冒烟测试图集（PRD 验收项 1）

> 2026-10-28 实测，后端 `uvicorn --port 8001`，模型 `qwen3.8-max`（`BASE_MODEL`）。
> `from_nb/` 为课程 notebook（`案例-多模态内容理解.ipynb`）内嵌图片的提取原始件，仅留档。

| level | 文件 | 来源 | 实测返回 |
|---|---|---|---|
| high | `high_corridor_ebike.jpg` | 网易新闻《电动自行车安全隐患："飞线"充电屡禁不止》配图（楼道内电动车飞线充电） | `high` ✓ |
| high | `high_flywire_multi.jpg` | 同上（飞线充电多图拼版） | `high` ✓ |
| medium | `nb_boxes.jpg` | 课程 notebook 问题背景拼图切分（楼道角落纸箱堆积） | `medium` ✓ |
| medium | `nb_people.jpg` | 同上切分（楼道杂物搬运场景） | `medium` ✓ |
| medium | `parking_lot_boxes.jpg` | notebook cell16 输出图（停车场角落纸箱堆积） | `medium` ✓ |
| low | `medium_notebook.jpg` | notebook cell17 输出图（楼道自行车＋少量堆物；notebook 中 Qwen2.5-VL 判中风险，qwen3.8-max 判低风险） | `low` ✓ |
| none | `nb_clean.jpg` | 课程 notebook 问题背景拼图切分（干净楼道） | `none` ✓ |
| not_corridor | `landscape1.jpg` | picsum（海景） | `not_corridor` ✓ |
| not_corridor | `landscape2.jpg` | picsum（随机风景） | `not_corridor` ✓ |

复现命令（`backend/` 启动后）：

```bash
cd test_images
for f in high_corridor_ebike.jpg high_flywire_multi.jpg nb_boxes.jpg nb_people.jpg \
         parking_lot_boxes.jpg medium_notebook.jpg nb_clean.jpg landscape1.jpg landscape2.jpg; do
  echo "$f -> $(curl -s -F "image=@$f;type=image/jpeg" http://localhost:8001/api/recognize)"
done
```

说明：图源网络受限（Wikimedia/GitHub raw/Unsplash 主站均不可达），可用图源为国内新闻 CDN 与 picsum；
low/none 类每类 1 张（PRD 最低要求每类 ≥1 张全对；「建议每类 2 张」受图源限制未凑齐）。
