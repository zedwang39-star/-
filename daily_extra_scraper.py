import json
import os
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re

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

def is_new_product_launch(title):
    """核心过滤器：只保留包含新项目、上线、预约等关键词的移动端产品"""
    title_lower = title.lower()
    
    # 排除明显的纯技术/源码/算法文章
    blacklist = ["github", "源码", "开源库", "算法详解", "论文", "模型训练", "面试", "架构", "部署", "报错"]
    if any(b in title_lower for b in blacklist):
        return False
        
    # 必须包含以下至少一个“发布/上线/预约”强信号
    launch_keywords = [
        "预约", "上线", "发布", "首发", "定档", "公测", "内测", "开测", "封测", 
        "新游", "launch", "release", "pre-register", "pre-registration", 
        "new game", "new app", "unveil", "out now", "beta"
    ]
    
    # 必须是移动端相关（App/手游/手机/移动端）或明确的品类
    mobile_keywords = ["app", "手游", "移动端", "手机", "ios", "android", "mobile", "游戏", "工具", "短剧"]
    
    has_launch = any(k in title_lower for k in launch_keywords)
    has_mobile = any(k in title_lower for k in mobile_keywords)
    
    # 对于Product Hunt等海外源，有些标题很简短不带App字样，但只要是新品发布也算
    return has_launch and has_mobile

def fetch_rss(rss_url, category="ai", source_name=""):
    items = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_data = resp.read()
            root = ET.fromstring(xml_data)
            
            entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            today = datetime.date.today().isoformat()
            
            for entry in entries[:20]:
                title = (entry.findtext("title") or entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link = (entry.findtext("link") or entry.findtext("{http://www.w3.org/2005/Atom}link") or "").strip()
                
                # 清洗标题
                title = re.sub(r'\s+', ' ', title)
                
                # 1. 链接安检
                if not title or not is_valid_link(link):
                    continue
                
                # 2. 内容安检：过滤掉非移动端新项目发布的信息
                if not is_new_product_launch(title):
                    continue
                
                clean_title = title[:40].strip() if len(title) > 40 else title
                
                items.append({
                    "name": clean_title,
                    "category": category,
                    "domestic": "海外/全球",
                    "overseas": "全球发布",
                    "expected": "已发布/预约中",
                    "expected_raw": "已发布/预约中",
                    "source_ts": today,
                    "source_label": source_name,
                    "source_url": link,
                    "basis": "P1 移动端新品发布",
                    "contact": "—",
                    "pinned": False
                })
    except Exception as e:
        print(f"抓取 {rss_url} 失败: {e}")
    return items

def scrape_extra_sources():
    all_new_items = []
    
    # ========== 1. 全球应用商店与聚合平台 (新上架/预约) ==========
    # AppAgg: 多平台新应用与新游戏聚合（支持RSS）
    all_new_items.extend(fetch_rss("https://appagg.com/rss/new/?hl=en", "game", "AppAgg 新游"))
    all_new_items.extend(fetch_rss("https://appagg.com/rss/new-apps/?hl=en", "ai", "AppAgg 新App"))
    
    # App Store 新游推荐 (美国区免费游戏榜)
    all_new_items.extend(fetch_rss("https://itunes.apple.com/us/rss/topfreeapplications/limit=20/genre=6014/json", "game", "App Store 新游"))
    # App Store 新App推荐 (美国区免费应用榜)
    all_new_items.extend(fetch_rss("https://itunes.apple.com/us/rss/topfreeapplications/limit=20/genre=6000/json", "ai", "App Store 新App"))

    # ========== 2. 海外AI与工具新品 (Product Hunt 精准分类) ==========
    # Product Hunt 官方分类 Feed
    all_new_items.extend(fetch_rss("https://www.producthunt.com/feed?category=artificial-intelligence", "ai", "PH AI工具"))
    all_new_items.extend(fetch_rss("https://www.producthunt.com/feed?category=games", "game", "PH 游戏"))
    all_new_items.extend(fetch_rss("https://www.producthunt.com/feed?category=mobile", "ai", "PH 移动端"))
    
    # ========== 3. 国内游戏出海与预约榜 ==========
    # GameLook 官方RSS (海外新游速递等)
    all_new_items.extend(fetch_rss("http://www.gamelook.com.cn/feed", "game", "GameLook 新游"))
    
    # 游戏葡萄 (通过RSSHub，通常聚焦手游与出海)
    all_new_items.extend(fetch_rss("https://rsshub.app/gameres/hot", "game", "游戏葡萄热文"))
    
    # 游戏陀螺 (聚焦出海与日韩市场)
    all_new_items.extend(fetch_rss("https://rsshub.app/sy/youxituoluo", "game", "游戏陀螺"))
    
    # ========== 4. 国内AI工具新品动态 ==========
    # 机器之心 (国内AI权威媒体，筛选后只会留下产品发布相关)
    all_new_items.extend(fetch_rss("https://rsshub.app/jiqizhixin/article", "ai", "机器之心"))
    # 新智元
    all_new_items.extend(fetch_rss("https://rsshub.app/ai-era/daily", "ai", "新智元 AI日报"))
    
    return all_new_items

def merge_and_save(existing, new_items):
    name_map = {item["name"]: item for item in existing.get("items", [])}
    for item in new_items:
        name_map[item["name"]] = item
        
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=CUTOFF_DAYS)).isoformat()
    
    kept_items = []
    cleaned_count = 0
    for v in name_map.values():
        if v.get("source_ts", "9999") < cutoff_date:
            continue
        # 保留之前的历史大清洗逻辑：剔除带“/”的源码库等无效记录
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
    print(f"🧹 历史大清洗：共清除了 {cleaned_count} 条无效记录！")

if __name__ == "__main__":
    existing_data = load_existing()
    new_data = scrape_extra_sources()
    merge_and_save(existing_data, new_data)
