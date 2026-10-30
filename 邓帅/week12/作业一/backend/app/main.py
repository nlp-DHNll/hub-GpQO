"""FastAPI 入口:实例、CORS、日志、路由挂载(技术设计 §2.5)。"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="楼道消防隐患识别")
app.include_router(router, prefix="/api")

# 覆盖前端直连后端的访问方式(dev 走 vite 代理时同源用不到,T11)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
