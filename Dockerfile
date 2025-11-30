FROM python:3.11-slim

LABEL maintainer="your-email@example.com"
LABEL description="Goofish Tracker - 闲鱼商品追踪工具"

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps

# 复制项目文件
COPY tracker.py .
COPY config.example.yaml .

# 创建数据目录
RUN mkdir -p /app/data /app/logs

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 运行
CMD ["python3", "tracker.py"]
