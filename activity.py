from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import json
import time
import os
import traceback
import datetime
import re
import random

# 随机用户代理（可选，增强反检测）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/113.0.0.0 Safari/537.36",
]

def get_server_folder(server_id):
    """根据服务器ID返回对应的文件夹名称"""
    mapping = {"15": "jp", "16": "cn", "17": "intl"}
    return mapping.get(server_id, "intl")  # 默认国际服

def get_activity_types(title):
    """根据活动标题推断类型（与原脚本保持一致）"""
    types = []
    if "2倍" in title or "3倍" in title:
        types.append("资源翻倍")
    if "登入活动" in title:
        types.append("签到")
    if "制约解除决战" in title:
        types.append("制约解除决战")
    if "[活动]" in title:
        types.append("活动")
    if "总力战" in title:
        types.append("总力战")
    if "招募100次" in title:
        types.append("庆典")
    if "大决战" in title:
        types.append("大决战")
    if "综合战术考试" in title:
        types.append("考试")
    if "[迷你活动]" in title:
        types.append("长草活动")
    if "复刻" in title:
        types.append("复刻")
    if not types:
        types.append("其他")
    return types

def parse_time_delta(progress_text, status):
    """
    从进度文本解析时间增量（timedelta）
    支持格式：
      - "21天后结束"  -> 正 timedelta(days=21)
      - "5天后开始"   -> 正 timedelta(days=5)
      - "已结束3天"   -> 负 timedelta(days=3)
      - "还剩下2天5小时" -> 正 timedelta(days=2, hours=5)
    """
    try:
        days = 0
        hours = 0
        # 优先匹配“X天Y小时”
        match = re.search(r'(\d+)天(\d+)小时', progress_text)
        if match:
            days = int(match.group(1))
            hours = int(match.group(2))
        else:
            # 匹配单独的天数
            match = re.search(r'(\d+)天', progress_text)
            if match:
                days = int(match.group(1))
            # 匹配小时（可能没有天）
            match = re.search(r'(\d+)小时', progress_text)
            if match:
                hours = int(match.group(1))
        total_hours = days * 24 + hours
        if total_hours == 0:
            return None
        if "已结束" in status:
            return datetime.timedelta(hours=-total_hours)
        else:
            return datetime.timedelta(hours=total_hours)
    except Exception as e:
        print(f"时间解析错误: {progress_text} - {str(e)}")
        return None

def get_dynamic_cards(server_id):
    try:
        # 配置 Chrome 选项
        chrome_options = Options()
        # GitHub Actions 中使用无头模式
        if os.getenv("GITHUB_ACTIONS") == "true":
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
        else:
            # 本地使用有头模式（方便调试）
            chrome_options.headless = False

        # 可选随机 User-Agent
        chrome_options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        # 自动管理 ChromeDriver
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        # 移除 webdriver 特征
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })

        target_url = f"https://www.gamekee.com/ba/huodong/{server_id}"
        print(f"开始加载页面: {target_url}")
        driver.get(target_url)

        # 等待活动卡片加载（新结构类名 activity-item）
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "activity-item"))
        )

        # 模拟滚动到底部，确保所有动态内容加载
        print("模拟滚动加载内容...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        time.sleep(3)  # 等待渲染

        # 获取所有卡片
        cards = driver.find_elements(By.CLASS_NAME, "activity-item")
        print(f"找到 {len(cards)} 张活动卡片")

        # 分类存储
        ongoing = []    # 进行中
        upcoming = []   # 未开始
        ended = []      # 已结束

        for i, card in enumerate(cards, 1):
            try:
                # 提取活动类型（页面上的小标签，如“爬塔”）
                type_text = ""
                try:
                    type_elem = card.find_element(By.CSS_SELECTOR, ".activity-item_type")
                    type_text = type_elem.text.strip()
                except:
                    pass

                # 图片
                img_url = ""
                try:
                    img_elem = card.find_element(By.CSS_SELECTOR, ".activity-item_img img")
                    img_url = img_elem.get_attribute("src")
                except:
                    pass

                # 标题
                title = ""
                try:
                    title_elem = card.find_element(By.CSS_SELECTOR, ".activity-item_title")
                    title = title_elem.text.strip()
                except:
                    continue  # 无标题则跳过

                # 描述
                desc = ""
                try:
                    desc_elem = card.find_element(By.CSS_SELECTOR, ".activity-item_description")
                    desc = desc_elem.text.strip()
                except:
                    pass

                # 状态
                status = ""
                try:
                    status_elem = card.find_element(By.CSS_SELECTOR, ".activity-item_status")
                    status = status_elem.text.strip()
                except:
                    continue

                # 进度文本（如“21天后结束”）
                progress = ""
                try:
                    progress_elem = card.find_element(By.CSS_SELECTOR, ".time")
                    progress = progress_elem.text.strip()
                except:
                    pass

                # 生成标签：标题规则标签 + 页面类型
                tags = get_activity_types(title)
                if type_text and type_text not in tags:
                    tags.append(type_text)

                card_data = {
                    "title": title,
                    "description": desc,
                    "image_url": img_url,
                    "status": status,
                    "progress": progress,
                    "tags": tags
                }

                # 根据状态分类
                if "进行中" in status:
                    ongoing.append(card_data)
                elif "未开始" in status:
                    upcoming.append(card_data)
                elif "已结束" in status:
                    ended.append(card_data)

                print(f"已解析卡片 {i}/{len(cards)} - 状态: {status}")
            except Exception as e:
                print(f"卡片解析错误: {str(e)[:100]}")
                continue

        # 组合结果：全部进行中 + 全部未开始 + 最新的5个已结束
        result = ongoing + upcoming + ended[:5]
        print(f"活动统计: 进行中 {len(ongoing)} 个, 未开始 {len(upcoming)} 个, 已结束 {len(ended)} 个")
        print(f"最终保留 {len(result)} 张卡片")
        return result

    except Exception as e:
        print(f"爬取过程发生错误: {str(e)}")
        traceback.print_exc()
        return []
    finally:
        if 'driver' in locals():
            driver.quit()
            print("浏览器已关闭")

if __name__ == "__main__":
    # 读取服务器ID（从环境变量，默认17国际服）
    server_id = os.getenv("SERVER_ID", "17")
    print(f"当前爬取服务器ID: {server_id}")

    # 确定输出目录
    folder = get_server_folder(server_id)
    output_dir = os.path.join("data", folder)
    os.makedirs(output_dir, exist_ok=True)

    # 执行爬取
    results = get_dynamic_cards(server_id)

    # 获取当前东八区时间，精确到小时
    tz = datetime.timezone(datetime.timedelta(hours=8))
    crawl_dt = datetime.datetime.now(tz).replace(minute=0, second=0, microsecond=0)
    crawl_time = crawl_dt.isoformat()

    # 为每个活动计算开始/结束时间
    processed = []
    for act in results:
        start_time = None
        end_time = None
        delta = parse_time_delta(act["progress"], act["status"])
        if delta:
            if "未开始" in act["status"]:
                start_dt = crawl_dt + delta
                start_time = start_dt.isoformat()
            elif "进行中" in act["status"]:
                end_dt = crawl_dt + delta
                end_time = end_dt.isoformat()
            elif "已结束" in act["status"]:
                end_dt = crawl_dt + delta  # delta为负
                end_time = end_dt.isoformat()

        processed.append({
            "title": act["title"],
            "description": act["description"],
            "image_url": act["image_url"],
            "progress": act["progress"],
            "tags": act["tags"],
            "start_time": start_time,
            "end_time": end_time
        })

    # 构建最终输出
    output = {
        "crawl_time": crawl_time,
        "activities": processed
    }

    # 保存JSON
    out_file = os.path.join(output_dir, "activity_cards.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"结果已保存至: {os.path.abspath(out_file)}")
    print(f"爬取时间(东八区): {crawl_time}")
    print(f"提取活动数量: {len(processed)}")
    if processed:
        print(f"第一个活动: {processed[0]['title']}")
