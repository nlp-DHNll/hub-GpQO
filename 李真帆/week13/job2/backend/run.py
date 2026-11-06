"""后端启动入口：python run.py（监听 127.0.0.1:8000）。

与前端（streamlit run frontend/app.py，:8501）分进程运行；
严禁把 FastAPI 实例放进 Streamlit 脚本里——Streamlit 会自动接管导致前端不渲染。
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
