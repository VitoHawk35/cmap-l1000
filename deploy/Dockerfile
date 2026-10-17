# CMAP L1000 API 生产镜像
FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# 复制应用代码
COPY app/ ./app/
COPY run.py .

# 数据目录（挂载卷）
VOLUME ["/app/cmap_data"]

# 暴露端口
EXPOSE 8000

# 启动命令（单 worker + 8 线程，绑定0.0.0.0允许容器内访问）
CMD ["gunicorn", "-w", "1", "--threads", "8", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "300", "--keep-alive", "60", "app.main:app"]