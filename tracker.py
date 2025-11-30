#!/usr/bin/env python3
"""
Goofish Tracker - 闲鱼商品追踪器
支持24小时定时运行，记录价格变化，追踪商品状态

GitHub: https://github.com/yourname/goofish-tracker
"""

__version__ = "1.0.0"
__author__ = "Your Name"

import hashlib
import asyncio
import json
import logging
import signal
import sys
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import yaml
except ImportError:
    print("错误: 请先安装依赖 - pip install pyyaml")
    sys.exit(1)

try:
    from playwright.async_api import async_playwright, Response
except ImportError:
    print("错误: 请先安装依赖 - pip install playwright && playwright install chromium")
    sys.exit(1)


class Config:
    """配置管理类，支持热更新"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.data = self._load()

    def _load(self) -> dict:
        """加载配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def reload(self):
        """重新加载配置（支持运行时热更新）"""
        self.data = self._load()

    @property
    def keywords(self) -> List[str]:
        return self.data.get("keywords", [])

    @property
    def max_pages(self) -> int:
        return self.data.get("spider", {}).get("max_pages", 3)

    @property
    def interval_seconds(self) -> int:
        return self.data.get("spider", {}).get("interval_seconds", 1800)

    @property
    def page_wait_seconds(self) -> int:
        return self.data.get("spider", {}).get("page_wait_seconds", 2)

    @property
    def timeout_seconds(self) -> int:
        return self.data.get("spider", {}).get("timeout_seconds", 30)

    @property
    def concurrency(self) -> int:
        return self.data.get("spider", {}).get("concurrency", 1)

    @property
    def headless(self) -> bool:
        return self.data.get("browser", {}).get("headless", True)

    @property
    def user_agent(self) -> str:
        return self.data.get("browser", {}).get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    @property
    def base_dir(self) -> Path:
        return Path(self.data.get("storage", {}).get("base_dir", "./data"))

    @property
    def keyword_subdirs(self) -> bool:
        return self.data.get("storage", {}).get("keyword_subdirs", True)

    @property
    def log_level(self) -> str:
        return self.data.get("logging", {}).get("level", "INFO")

    @property
    def log_file(self) -> Optional[str]:
        return self.data.get("logging", {}).get("file")

    @property
    def track_days(self) -> int:
        return self.data.get("tracking", {}).get("track_days", 7)


class ProductTracker:
    """商品追踪器 - 管理商品状态和价格历史"""

    STATUS_ACTIVE = "在售"
    STATUS_SOLD = "疑似成交"
    STATUS_REMOVED = "已下架"

    def __init__(self, config: Config):
        self.config = config
        self.base_dir = config.base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("Tracker")

    @staticmethod
    def get_md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def get_link_unique_key(link: str) -> str:
        parts = link.split('&', 1)
        return parts[0] if len(parts) >= 1 else link

    @staticmethod
    def safe_filename(s: str) -> str:
        return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_.-]", "_", s)[:50]

    @staticmethod
    def parse_price(price_str: str) -> Optional[float]:
        if not price_str or price_str == "价格异常":
            return None
        try:
            price = price_str.replace("¥", "").replace(",", "").strip()
            return float(price)
        except ValueError:
            return None

    def get_keyword_dir(self, keyword: str) -> Path:
        if self.config.keyword_subdirs:
            kw_dir = self.base_dir / self.safe_filename(keyword)
        else:
            kw_dir = self.base_dir
        kw_dir.mkdir(parents=True, exist_ok=True)
        return kw_dir

    def get_tracker_file(self, keyword: str) -> Path:
        return self.get_keyword_dir(keyword) / "products.jsonl"

    def get_daily_file(self, keyword: str) -> Path:
        date_str = datetime.now().strftime("%Y%m%d")
        return self.get_keyword_dir(keyword) / f"snapshot_{date_str}.jsonl"

    def get_history_file(self, keyword: str) -> Path:
        return self.get_keyword_dir(keyword) / "price_history.jsonl"

    def get_sold_file(self, keyword: str) -> Path:
        return self.get_keyword_dir(keyword) / "sold_items.jsonl"

    def load_tracked_products(self, keyword: str) -> Dict[str, Dict]:
        tracker_file = self.get_tracker_file(keyword)
        products = {}

        if tracker_file.exists():
            try:
                with open(tracker_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            item = json.loads(line.strip())
                            link_hash = item.get("link_hash")
                            if link_hash:
                                products[link_hash] = item
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                self.logger.warning(f"读取追踪数据失败: {e}")

        return products

    def save_tracked_products(self, keyword: str, products: Dict[str, Dict]):
        tracker_file = self.get_tracker_file(keyword)
        with open(tracker_file, "w", encoding="utf-8") as f:
            for item in products.values():
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def record_price_change(self, keyword: str, link_hash: str,
                            old_price: str, new_price: str, title: str):
        history_file = self.get_history_file(keyword)
        record = {
            "link_hash": link_hash,
            "title": title,
            "old_price": old_price,
            "new_price": new_price,
            "change_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "change_percent": self._calc_price_change(old_price, new_price)
        }
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _calc_price_change(self, old_price: str, new_price: str) -> str:
        old_val = self.parse_price(old_price)
        new_val = self.parse_price(new_price)
        if old_val and new_val and old_val > 0:
            change = ((new_val - old_val) / old_val) * 100
            return f"{change:+.1f}%"
        return "N/A"

    def record_sold_item(self, keyword: str, item: Dict):
        sold_file = self.get_sold_file(keyword)
        sold_item = item.copy()
        sold_item["status"] = self.STATUS_SOLD
        sold_item["sold_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sold_item["last_price"] = item.get("price", "未知")
        with open(sold_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(sold_item, ensure_ascii=False) + "\n")

    def save_daily_snapshot(self, keyword: str, items: List[Dict]):
        daily_file = self.get_daily_file(keyword)
        with open(daily_file, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def process_items(self, keyword: str, new_items: List[Dict]) -> Dict[str, int]:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats = {"new": 0, "price_changed": 0, "sold": 0, "active": 0, "total": len(new_items)}

        tracked = self.load_tracked_products(keyword)
        current_hashes = set()

        for item in new_items:
            link = item.get("link", "")
            unique_part = self.get_link_unique_key(link)
            link_hash = self.get_md5(unique_part)
            item["link_hash"] = link_hash
            current_hashes.add(link_hash)

            if link_hash in tracked:
                old_item = tracked[link_hash]
                old_price = old_item.get("price", "")
                new_price = item.get("price", "")

                if old_price != new_price:
                    stats["price_changed"] += 1
                    self.record_price_change(keyword, link_hash, old_price, new_price, item.get("title", ""))
                    price_history = old_item.get("price_history", [])
                    price_history.append({"price": new_price, "time": now})
                    item["price_history"] = price_history
                    item["first_seen"] = old_item.get("first_seen", now)
                    item["first_price"] = old_item.get("first_price", old_price)
                else:
                    item["price_history"] = old_item.get("price_history", [])
                    item["first_seen"] = old_item.get("first_seen", now)
                    item["first_price"] = old_item.get("first_price", old_price)

                item["last_updated"] = now
                item["status"] = self.STATUS_ACTIVE
                stats["active"] += 1
            else:
                stats["new"] += 1
                item["first_seen"] = now
                item["first_price"] = item.get("price", "")
                item["last_updated"] = now
                item["status"] = self.STATUS_ACTIVE
                item["price_history"] = [{"price": item.get("price", ""), "time": now}]

            tracked[link_hash] = item

        for link_hash, old_item in list(tracked.items()):
            if link_hash not in current_hashes:
                if old_item.get("status") == self.STATUS_ACTIVE:
                    stats["sold"] += 1
                    old_item["status"] = self.STATUS_SOLD
                    old_item["sold_time"] = now
                    self.record_sold_item(keyword, old_item)
                    tracked[link_hash] = old_item

        self.save_tracked_products(keyword, tracked)
        self.save_daily_snapshot(keyword, new_items)

        return stats


class GoofishScraper:
    """闲鱼爬虫核心类"""

    API_PATTERN = "h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search"

    def __init__(self, config: Config, tracker: ProductTracker):
        self.config = config
        self.tracker = tracker
        self.logger = logging.getLogger("Scraper")

    @staticmethod
    def safe_get(data: Any, *keys, default="") -> Any:
        for key in keys:
            try:
                data = data[key]
            except (KeyError, TypeError, IndexError):
                return default
        return data

    def parse_item(self, item: dict) -> Optional[Dict]:
        try:
            main_data = self.safe_get(item, "data", "item", "main", "exContent", default={})
            click_params = self.safe_get(item, "data", "item", "main", "clickParam", "args", default={})

            title = self.safe_get(main_data, "title", default="未知标题")

            price_parts = self.safe_get(main_data, "price", default=[])
            price = "价格异常"
            if isinstance(price_parts, list):
                price = "".join([str(p.get("text", "")) for p in price_parts if isinstance(p, dict)])
                price = price.replace("当前价", "").strip()
                if "万" in price:
                    try:
                        num = float(price.replace("¥", "").replace("万", ""))
                        price = f"¥{num * 10000:.0f}"
                    except ValueError:
                        pass

            area = self.safe_get(main_data, "area", default="地区未知")
            seller = self.safe_get(main_data, "userNickName", default="匿名卖家")
            raw_link = self.safe_get(item, "data", "item", "main", "targetUrl", default="")
            image_url = self.safe_get(main_data, "picUrl", default="")

            publish_time_str = click_params.get("publishTime", "")
            if str(publish_time_str).isdigit():
                publish_time = datetime.fromtimestamp(int(publish_time_str) / 1000).strftime("%Y-%m-%d %H:%M")
            else:
                publish_time = "未知时间"

            return {
                "title": title,
                "price": price,
                "area": area,
                "seller": seller,
                "link": raw_link.replace("fleamarket://", "https://www.goofish.com/"),
                "image": f"https:{image_url}" if image_url and not image_url.startswith("http") else image_url,
                "publish_time": publish_time,
            }
        except Exception as e:
            self.logger.warning(f"解析商品数据失败: {e}")
            return None

    async def scrape_keyword(self, keyword: str) -> List[Dict]:
        data_list = []

        async def on_response(response: Response):
            if self.API_PATTERN in response.url:
                try:
                    result_json = await response.json()
                    items = result_json.get("data", {}).get("resultList", [])
                    for item in items:
                        parsed = self.parse_item(item)
                        if parsed:
                            data_list.append(parsed)
                except Exception as e:
                    self.logger.warning(f"响应处理异常: {e}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.config.headless)
            context = await browser.new_context(user_agent=self.config.user_agent)
            page = await context.new_page()

            try:
                self.logger.info(f"开始爬取: {keyword}")
                await page.goto("https://www.goofish.com", timeout=self.config.timeout_seconds * 1000)

                await page.fill('input[class*="search-input"]', keyword)
                await page.click('button[type="submit"]')

                try:
                    await page.wait_for_selector("div[class*='closeIconBg']", timeout=3000)
                    await page.click("div[class*='closeIconBg']")
                except:
                    pass

                try:
                    await page.click('text=新发布', timeout=5000)
                    await page.click('text=最新', timeout=5000)
                except:
                    self.logger.debug("排序设置失败，使用默认排序")

                page.on("response", on_response)

                current_page = 1
                while current_page <= self.config.max_pages:
                    self.logger.debug(f"[{keyword}] 第 {current_page}/{self.config.max_pages} 页")
                    await asyncio.sleep(self.config.page_wait_seconds)

                    if current_page < self.config.max_pages:
                        try:
                            next_btn = await page.query_selector(
                                "[class*='search-pagination-arrow-right']:not([disabled])"
                            )
                            if not next_btn:
                                break
                            await next_btn.click()
                        except Exception as e:
                            self.logger.warning(f"翻页失败: {e}")
                            break

                    current_page += 1

            except Exception as e:
                self.logger.error(f"爬取异常: {e}")
            finally:
                await browser.close()

        return data_list

    async def run_once(self):
        self.logger.info("=" * 50)
        self.logger.info(f"开始新一轮爬取 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            self.config.reload()
            self.logger.info(f"关键词: {self.config.keywords}")
        except Exception as e:
            self.logger.warning(f"配置重载失败: {e}")

        keywords = self.config.keywords
        if not keywords:
            self.logger.warning("没有配置关键词")
            return

        sem = asyncio.Semaphore(self.config.concurrency)

        async def process_keyword(kw: str):
            async with sem:
                try:
                    items = await self.scrape_keyword(kw)
                    if items:
                        stats = self.tracker.process_items(kw, items)
                        self.logger.info(
                            f"[{kw}] 完成: 总计{stats['total']}, "
                            f"新增{stats['new']}, 价格变动{stats['price_changed']}, "
                            f"疑似成交{stats['sold']}"
                        )
                    else:
                        self.logger.warning(f"[{kw}] 未获取到数据")
                except Exception as e:
                    self.logger.error(f"[{kw}] 爬取失败: {e}")

        tasks = [asyncio.create_task(process_keyword(kw)) for kw in keywords]
        await asyncio.gather(*tasks)

        self.logger.info(f"本轮完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    async def run_forever(self):
        self.logger.info(f"Goofish Tracker v{__version__} 启动")
        self.logger.info(f"爬取间隔: {self.config.interval_seconds}秒")

        while True:
            try:
                await self.run_once()
            except Exception as e:
                self.logger.error(f"任务异常: {e}")

            next_time = datetime.now().timestamp() + self.config.interval_seconds
            next_time_str = datetime.fromtimestamp(next_time).strftime("%Y-%m-%d %H:%M:%S")
            self.logger.info(f"下次爬取: {next_time_str}")

            await asyncio.sleep(self.config.interval_seconds)


def setup_logging(config: Config):
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(console_handler)

    if config.log_file:
        log_file = Path(config.log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(file_handler)


def main():
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.yaml"

    if not config_path.exists():
        example_path = script_dir / "config.example.yaml"
        if example_path.exists():
            print(f"提示: 请复制 config.example.yaml 为 config.yaml 并修改配置")
        else:
            print(f"错误: 配置文件不存在 - {config_path}")
        sys.exit(1)

    try:
        config = Config(str(config_path))
    except Exception as e:
        print(f"配置文件加载失败: {e}")
        sys.exit(1)

    setup_logging(config)
    logger = logging.getLogger("main")

    tracker = ProductTracker(config)
    scraper = GoofishScraper(config, tracker)

    def signal_handler(sig, frame):
        logger.info("收到退出信号，正在关闭...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    pid_file = script_dir / "tracker.pid"
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    try:
        asyncio.run(scraper.run_forever())
    except KeyboardInterrupt:
        logger.info("用户中断")


if __name__ == "__main__":
    main()
