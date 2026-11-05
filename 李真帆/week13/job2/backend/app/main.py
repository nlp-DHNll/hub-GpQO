"""FastAPI 应用入口：路由注册 + CORS + 健康检查。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import chat
from .schemas import HealthResponse

app = FastAPI(title="SQL 数据智能体后端", version="1.0.0")

# 前端是服务端直连（Streamlit -> requests），不走浏览器 CORS；
# 仍然放开，方便用手机浏览器直接调试后端接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """存活探针：前端启动后可先探测后端是否在线。"""
    return HealthResponse(status="ok")
