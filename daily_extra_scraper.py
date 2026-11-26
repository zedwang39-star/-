import json
import os
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

DATA_FILE = "data.json"
CUTOFF_DAYS = 180

def load_existing():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": []}

def is_valid_link(link):
    """安检员：过滤空链接、根域名、非 http(s) 链接"""
    if not link or not link.startswith(("http://", "https://")):
        return False
    try:
        parsed = urllib.parse.urlparse(link)
        host = parsed.hostname or ""
        path = parsed.path or ""
        if host in ("github.com", "www.github.com", "producthunt.com", "www.producthunt.com"):
            if path.strip("/") == "":
                return False
        if not path.strip("/") and not parsed.query:
            return False
        return True
    except Exception:
        return False

def fetch_rss(rss_url, category="ai", source_name=""):
    items = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_data = resp.read()
            root = ET.fromstring(xml_data)
            
            entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            today = datetime.date.today().isoformat()
            
            for entry in entries[:15]:
                title = (entry.findtext("title") or entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link = (entry.findtext("link") or entry.findtext("{http://www.w3.org/2005/Atom}link") or "").strip()
                
                # 如果标题里带有 GitHub 代码库典型的 '/' 符号，直接跳过
                if not title or "/" in title or not is_valid_link(link):
                    continue
                
                clean_title = title[:40].strip() if len(title) > 40 else title
                
                items.append({
                    "name": clean_title,
                    "category": category,
                    "domestic": "海外/开源动态",
                    "overseas": "全球",
                    "expected": "已发布",
                    "expected_raw": "已发布",
                    "source_ts": today,
                    "source_label": source_name or ("RSS: " + rss_url.split("//")[-1].split("/")[0]),
                    "source_url": link,
                    "basis": "P1 出海/科技情报聚合",
                    "contact": "—",
                    "pinned": False
                })
    except Exception as e:
        print(f"抓取 {rss_url} 失败: {e}")
    return items

def scrape_extra_sources():
    all_new_items = []
    # 只保留最优质的产品、新闻媒体源，彻底告别源码库
    all_new_items.extend(fetch_rss("https://www.producthunt.com/feed", "ai", "Product Hunt 新品"))
    all_new_items.extend(fetch_rss("https://techcrunch.com/category/artificial-intelligence/feed/", "ai", "TechCrunch AI"))
    all_new_items.extend(fetch_rss("https://venturebeat.com/category/ai/feed/", "ai", "VentureBeat AI"))
    all_new_items.extend(fetch_rss("https://www.theverge.com/rss/index.xml", "ai", "The Verge"))
    all_new_items.extend(fetch_rss("https://news.ycombinator.com/rss", "ai", "Hacker News 热榜"))
    all_new_items.extend(fetch_rss("https://www.nasdaq.com/feed/rssoutbound?category=FinTech", "fin", "Nasdaq FinTech"))
    return all_new_items

def merge_and_save(existing, new_items):
    name_map = {item["name"]: item for item in existing.get("items", [])}
    for item in new_items:
        name_map[item["name"]] = item
        
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=CUTOFF_DAYS)).isoformat()
    
    kept_items = []
    cleaned_count = 0
    for v in name_map.values():
        # 1. 清理超过 180 天的旧数据
        if v.get("source_ts", "9999") < cutoff_date:
            continue
        
        # 2. 🌟 核心大清洗：如果名字里有 '/' 且不是 TapTap 的游戏，直接删掉（这就是之前残留的源码库）
        if "/" in v.get("name", "") and v.get("source_label") != "TapTap 预约榜":
            cleaned_count += 1
            continue
            
        kept_items.append(v)
    
    result = {
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "items": kept_items
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        
    print(f"每日补充完成。本次抓取 {len(new_items)} 条。")
    print(f"🧹 历史大清洗：共清除了 {cleaned_count} 条无效的 GitHub 代码库记录！")

if __name__ == "__main__":
    existing_data = load_existing()
    new_data = scrape_extra_sources()
    merge_and_save(existing_data, new_data)
