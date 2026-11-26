import json, os, datetime, urllib.request, urllib.parse, xml.etree.ElementTree as ET, re

DATA_FILE = "data.json"
CUTOFF_DAYS = 180

def load_existing():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {"items": []}

def is_valid_link(link):
    if not link or not link.startswith(("http://", "https://")): return False
    try:
        parsed = urllib.parse.urlparse(link)
        if parsed.hostname in ("github.com", "producthunt.com") and not parsed.path.strip("/"): return False
        if not parsed.path.strip("/") and not parsed.query: return False
        return True
    except: return False

def is_new_product_launch(title):
    title_lower = title.lower()
    blacklist = ["github", "源码", "开源库", "算法", "论文", "训练", "面试", "架构", "部署"]
    if any(b in title_lower for b in blacklist): return False
    launch_keywords = ["预约", "上线", "发布", "首发", "定档", "公测", "内测", "launch", "release", "beta", "new app", "new game"]
    mobile_keywords = ["app", "手游", "移动端", "手机", "ios", "android", "mobile", "游戏", "工具"]
    return any(k in title_lower for k in launch_keywords) and any(k in title_lower for k in mobile_keywords)

def fetch_rss(rss_url, category="ai", source_name=""):
    items = []
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            root = ET.fromstring(resp.read())
            entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            today = datetime.date.today().isoformat()
            for entry in entries[:15]:
                title = (entry.findtext("title") or entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link = (entry.findtext("link") or entry.findtext("{http://www.w3.org/2005/Atom}link") or "").strip()
                title = re.sub(r'\s+', ' ', title)
                if not title or "/" in title or not is_valid_link(link) or not is_new_product_launch(title): continue
                
                items.append({
                    "name": title[:40], 
                    "platform": "other", # 标签：其他三方
                    "category": category, "domestic": "海外/全球", "overseas": "全球",
                    "expected": "已发布/预约中", "expected_raw": "资讯",
                    "source_ts": today, "source_label": source_name,
                    "source_url": link, "basis": "P1 三方资讯新品", "contact": "—", "pinned": False
                })
    except Exception as e: print(f"抓取失败: {e}")
    return items

def scrape_extra_sources():
    all_items = []
    all_items.extend(fetch_rss("https://www.producthunt.com/feed?category=artificial-intelligence", "ai", "Product Hunt AI"))
    all_items.extend(fetch_rss("http://www.gamelook.com.cn/feed", "game", "GameLook 新游"))
    all_items.extend(fetch_rss("https://rsshub.app/gameres/hot", "game", "游戏葡萄"))
    all_items.extend(fetch_rss("https://rsshub.app/jiqizhixin/article", "ai", "机器之心"))
    return all_items

def merge_and_save(existing, new_items):
    name_map = {item["name"]: item for item in existing.get("items", [])}
    for item in new_items: name_map[item["name"]] = item
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=CUTOFF_DAYS)).isoformat()
    kept = [v for v in name_map.values() if v.get("source_ts", "9999") >= cutoff_date and not ("/" in v.get("name", "") and "TapTap" not in v.get("source_label", ""))]
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.datetime.utcnow().isoformat() + "Z", "items": kept}, f, ensure_ascii=False, indent=2)
    print(f"三方媒体抓取完成。新增 {len(new_items)} 条。")

if __name__ == "__main__":
    merge_and_save(load_existing(), scrape_extra_sources())
