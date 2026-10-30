# week12 作业一：楼道消防隐患识别（多模态前后端应用）

参考课程案例「多模态内容理解」构建（课件 notebook 不随仓库分发）：网页拍照/上传楼道照片 → 云端多模态模型（`qwen3.8-max`，OpenAI 兼容接口）→ 实时判定消防隐患等级（五级）。

> 作业要求原文（判定标准）：
>
> - 高风险：楼道中出现电动车、电瓶、飞线充电等可能起火的元素。
> - 中风险：楼道中存在大量堆积物严重影响通行或堆放大量纸箱、木质家具等能造成火势蔓延的堵塞物。
> - 低风险：存在楼道堆物现象但不严重。
> - 无风险：楼道干净，无堆放物品。
> - 非楼道：一些与楼道无关的图片。

设计文档：`PRD.md`（行为）→ `楼道消防隐患识别 功能设计文档.md`（交互）→ `楼道消防隐患识别 技术设计文档.md`（实现），三文档为单一事实源。

## 1. 环境准备

| 项 | 要求 |
|---|---|
| 后端 | conda 环境 py312：`/opt/miniconda3/envs/py312/bin/python` |
| 前端 | node v20（默认 v16 跑不了 pnpm，先切 PATH，见下）＋ pnpm |
| 凭据 | 项目根 `/Users/drdidi/Desktop/badou2026/.env`（`API_KEY`/`BASE_URL`/`BASE_MODEL`，后端沿目录链自动查找，无需额外配置） |

## 2. 启动命令

```bash
# —— 后端（backend/ 目录下）——
/opt/miniconda3/envs/py312/bin/python -m pip install -r requirements.txt
/opt/miniconda3/envs/py312/bin/python -m uvicorn app.main:app --port 8000 --reload
# 8000 被占 → --port 8001，同时前端启动时设 BACKEND_URL=http://localhost:8001（不用改代码）

# —— 前端（frontend/ 目录下）——
export PATH="$HOME/.nvs/default/bin:$PATH"   # 切 node v20
pnpm install
BACKEND_URL=http://localhost:8000 pnpm dev --host   # 8001 时同步替换；--host 供手机局域网访问
```

浏览器打开 <http://localhost:5173>（桌面全功能：拍照＋相册）。

## 3. 局域网访问（手机演示）

1. 手机与电脑连同一 WiFi；
2. 电脑上前端以 `pnpm dev --host` 启动（上节命令已含）；
3. 手机浏览器打开 `http://<电脑局域网IP>:5173`（本机当前 IP：`192.168.163.178`，用 `ipconfig getifaddr en0` 查询）；
4. 局域网 HTTP 为非安全上下文，手机浏览器将隐藏「拍照」入口、保留相册上传（自动降级）。

## 4. 验收自查步骤（对应 PRD §9 七项）

| # | 验收项 | 自查方式 | 结果 |
|---|---|---|---|
| 1 | 五类分类正确性 | `test_images/` 九张图 curl 冒烟（清单见 `test_images/README.md`），五类全对 | ✅ 全对（2026-10-28 实测） |
| 2 | 桌面全链路（拍照） | Playwright fake 摄像头流自动化：拍照→预览→确认→出结果（`frontend/smoke_camera.mjs` 场景 A） | ✅ PASS |
| 3 | 手机降级链路 | 真机局域网访问：拍照入口隐藏＋D2 文案＋相册全链路 | ✅（2026-10-29 真机验证通过） |
| 4 | 相册上传（桌面） | `frontend/smoke_album.mjs`：选图→预览→确认→真识别出结果 | ✅ ALL PASS |
| 5 | 两步交互 | 同上：预览阶段无上传、重选替换、取消回空态、确认才上传 | ✅ ALL PASS |
| 6 | 异常路径 | 后端 pytest 8 用例（400/502/504/重试）＋前端 E1–E4 文案与重试（`smoke_camera.mjs` 场景 D）＋断网恢复重试 | ✅ ALL PASS |
| 7 | 非楼道引导 | 上传风景图 → 灰色「非楼道」＋引导文案＋「重新拍摄」回跳（`m6_2` 验证） | ✅ PASS |

复跑冒烟（前后端均启动后，`frontend/` 下）。注：技术设计 T2 定稿「前端不写自动化、走手工验收」；`smoke_*.mjs` 为 M6 验收记录的辅助冒烟工具（Playwright 驱动真实浏览器走用户路径并截图留证），非前端测试套件，属验收方式增强：

```bash
export PATH="$HOME/.nvs/default/bin:$PATH"
node smoke_album.mjs    # 相册链路 + 两步交互(验收项 4、5)
node smoke_camera.mjs   # 拍照/降级/异常路径(验收项 2、3 前置、6)
```

后端单测（`backend/` 下）：`/opt/miniconda3/envs/py312/bin/python -m pytest -q`

## 5. 工程结构

```
作业一/
├── PRD.md / 功能设计文档 / 技术设计文档   # 行为依据
├── backend/          # FastAPI:POST /api/recognize(校验→vision→归一化→重试)
├── frontend/         # Vue3+TS+Vite+Element Plus:五态状态机、拍照/相册、压缩
└── test_images/      # 五类冒烟测试图＋来源与实测记录
```
