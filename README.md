# Goofish Tracker

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Playwright-1.40+-green.svg" alt="Playwright">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
</p>

闲鱼（Goofish）商品追踪工具，支持 **价格监控**、**成交分析** 和 **24小时自动运行**。

## Features

- **多关键词追踪** - 同时监控多个关键词的商品
- **价格历史记录** - 追踪每个商品的价格变化
- **成交识别** - 商品下架时自动标记"疑似成交"并记录最后价格
- **定时自动运行** - 支持 24 小时无人值守
- **配置热更新** - 修改配置文件后自动生效，无需重启
- **本地存储** - 数据保存为 JSONL 格式，方便分析

## Quick Start

### 1. 安装依赖

```bash
# 克隆项目
git clone https://github.com/yourname/goofish-tracker.git
cd goofish-tracker

# 安装 Python 依赖
pip install -r requirements.txt

# 安装浏览器
playwright install chromium
```

### 2. 配置

```bash
# 复制配置文件
cp config.example.yaml config.yaml

# 编辑配置，添加你的关键词
vim config.yaml
```

```yaml
keywords:
  - "iPhone 15"
  - "MacBook Pro"
  - "显卡"

spider:
  max_pages: 3           # 每个关键词爬取页数
  interval_seconds: 1800 # 爬取间隔（30分钟）
```

### 3. 运行

```bash
# 后台运行
./run.sh start

# 查看状态
./run.sh status

# 查看日志
./run.sh logs

# 停止
./run.sh stop
```

或前台运行：

```bash
python3 tracker.py
```

## Data Structure

```
goofish-tracker/
├── data/                    # 数据目录
│   └── <keyword>/           # 按关键词分目录
│       ├── products.jsonl       # 商品主数据
│       ├── price_history.jsonl  # 价格变动记录
│       ├── sold_items.jsonl     # 疑似成交商品
│       └── snapshot_YYYYMMDD.jsonl  # 每日快照
├── logs/                    # 日志目录
├── tracker.py               # 主程序
├── config.yaml              # 配置文件
└── run.sh                   # 管理脚本
```

## Data Format

### products.jsonl

商品主数据，包含追踪信息：

```json
{
  "title": "iPhone 15 Pro Max 256G",
  "price": "¥7999",
  "area": "广东深圳",
  "seller": "数码小王",
  "link": "https://www.goofish.com/item?id=...",
  "image": "https://...",
  "publish_time": "2024-11-30 14:30",
  "link_hash": "abc123...",
  "status": "在售",
  "first_seen": "2024-11-30 15:00:00",
  "first_price": "¥8500",
  "last_updated": "2024-12-01 10:00:00",
  "price_history": [
    {"price": "¥8500", "time": "2024-11-30 15:00:00"},
    {"price": "¥7999", "time": "2024-12-01 10:00:00"}
  ]
}
```

### price_history.jsonl

价格变动记录：

```json
{
  "link_hash": "abc123...",
  "title": "iPhone 15 Pro Max",
  "old_price": "¥8500",
  "new_price": "¥7999",
  "change_time": "2024-12-01 10:00:00",
  "change_percent": "-5.9%"
}
```

### sold_items.jsonl

疑似成交商品：

```json
{
  "title": "iPhone 15 Pro Max",
  "status": "疑似成交",
  "last_price": "¥7999",
  "sold_time": "2024-12-02 15:00:00",
  "first_price": "¥8500",
  "first_seen": "2024-11-30 15:00:00"
}
```

## Configuration

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `keywords` | 搜索关键词列表 | - |
| `spider.max_pages` | 每个关键词最大爬取页数 | 3 |
| `spider.interval_seconds` | 爬取间隔（秒） | 1800 |
| `spider.concurrency` | 并发爬取关键词数 | 1 |
| `browser.headless` | 无头模式 | true |
| `storage.base_dir` | 数据存储目录 | ./data |
| `logging.level` | 日志级别 | INFO |
| `logging.file` | 日志文件路径 | ./logs/tracker.log |

## Data Analysis

```bash
# 查看价格变动记录
cat data/iPhone/price_history.jsonl | jq .

# 统计疑似成交数量
wc -l data/iPhone/sold_items.jsonl

# 查看降价幅度最大的商品
cat data/iPhone/price_history.jsonl | jq -s 'sort_by(.change_percent) | .[0:5]'

# 查看当前在售商品数量
grep '"status": "在售"' data/iPhone/products.jsonl | wc -l

# 导出为 CSV（需要 jq）
cat data/iPhone/products.jsonl | jq -r '[.title, .price, .area, .seller] | @csv'
```

## Adding Keywords

直接编辑 `config.yaml` 添加关键词，保存后下一轮爬取自动生效（无需重启）：

```yaml
keywords:
  - "iPhone 15"
  - "MacBook Pro"
  - "新增的关键词"  # 添加在这里
```

## Deployment

### 使用 systemd（推荐）

创建服务文件 `/etc/systemd/system/goofish-tracker.service`：

```ini
[Unit]
Description=Goofish Tracker
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/goofish-tracker
ExecStart=/usr/bin/python3 /path/to/goofish-tracker/tracker.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable goofish-tracker
sudo systemctl start goofish-tracker
```

### 使用 Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && playwright install chromium --with-deps

COPY . .
CMD ["python3", "tracker.py"]
```

## FAQ

**Q: 为什么有些关键词没有数据？**

A: 可能是该关键词搜索结果较少，或者遇到反爬限制。建议增加爬取间隔时间。

**Q: "疑似成交"是什么意思？**

A: 当商品从搜索结果中消失时，会被标记为"疑似成交"。实际可能是卖家下架、删除或真正成交。

**Q: 如何添加新关键词？**

A: 直接编辑 `config.yaml`，无需重启程序。下一轮爬取时会自动加载新配置。

**Q: 服务器没有图形界面怎么办？**

A: 确保 `browser.headless` 设置为 `true`，并安装 Playwright 依赖：`playwright install chromium --with-deps`

## License

MIT License - 详见 [LICENSE](LICENSE)

## Disclaimer

本项目仅供学习研究使用，请遵守相关法律法规和闲鱼平台使用协议。数据不得用于商业用途。
