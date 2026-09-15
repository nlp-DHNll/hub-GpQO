# 深度研究助手

输入研究主题与约束，系统执行“规划 → 多轮搜索 → 正文提取 → 总结 → 充分性判断 → 报告生成”，产出带引用、过程记录和置信度说明的中文报告。项目是可完整演示的个人研究工作台。

## 已实现

- Next.js + TypeScript + Tailwind 专业桌面工作台：登录、新建、排队/运行进度、历史、报告详情、版本切换、管理页。
- FastAPI API；SSE 实时推送，前端断线时自动轮询降级。
- 快速/标准/深度档分别执行 1/2/3 轮，并限制时间、搜索和模型调用。
- PostgreSQL + Alembic；Redis + Celery，Worker 并发固定为 2；本地开发可用 SQLite + asyncio 回退。
- 取消保留过程、失败重试、补充研究生成 V2/V3、Markdown/HTML/PDF 导出。
- 公开网页正文提取；拒绝本机/内网 URL 和危险重定向；失败时明确降级为搜索摘要。
- PBKDF2 密码哈希、24 小时 HttpOnly Cookie、接口限流、安全响应头、密钥仅从环境变量注入。

## 本地开发

1. 复制 `.env.example` 为 `.env`，填入**新申请**的 DeepSeek 兼容接口密钥与 Bocha 搜索密钥。
2. 生成共享密码哈希：

   ```powershell
   $env:PASSWORD="你的密码"
   python -m backend.auth
   ```

3. 安装并启动后端：

   ```powershell
   python -m pip install -r requirements.txt
   uvicorn backend.app:app --reload --port 8000
   ```

4. 启动前端：

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

浏览器打开 `http://localhost:3000`。本地模式使用 SQLite 和进程内并发队列，无需先装 PostgreSQL/Redis。

## Docker Compose

配置 `.env` 后运行：

```bash
docker compose up --build
```

打开 `http://localhost`。Compose 会启动 Caddy、前端、API、并发为 2 的 Celery Worker、PostgreSQL 和 Redis。配置真实域名时，将 `SITE_ADDRESS` 设为域名并开放 80/443，Caddy 会自动申请 HTTPS 证书。

## 测试

```bash
pytest -q
cd frontend && npm run lint && npm run build
# 安装 Playwright 浏览器后可运行：npm run test:e2e
```

## API 摘要

- `POST /api/auth/login` / `POST /api/auth/logout`
- `POST /api/research`，`GET /api/research`，`GET /api/research/{id}`
- `GET /api/research/{id}/events`（SSE）
- `POST /api/research/{id}/cancel` / `retry`
- `GET /api/research/{id}/versions`
- `GET /api/research/{id}/export/{markdown|html|pdf}`
- `GET /api/admin/stats` / `failures`

## 安全说明

早期 README 中曾出现过明文搜索凭据，现已删除。该凭据应视为泄露并立即在服务商后台撤销；正式部署只能使用重新签发的密钥。不要提交 `.env`、数据库、日志和导出文件。
