import json
import os
import datetime
import urllib.request
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

def fetch_rss(rss_url):
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
                if not title:
                    continue
                
                clean_title = title[:40].strip() if len(title) > 40 else title
                
                items.append({
                    "name": clean_title,
                    "category": "ai",
                    "domestic": "开源/海外产品",
                    "overseas": "全球发布",
                    "expected": "已上线",
                    "expected_raw": "已上线",
                    "source_ts": today,
                    "source_label": "每日源: 抓取",
                    "source_url": link,
                    "basis": "P1 每日开源/出海情报聚合",
                    "contact": "—",
                    "pinned": False
                })
    except Exception as e:
        print(f"抓取 {rss_url} 失败: {e}")
    return items

def scrape_extra_sources():
    all_new_items = []
    # 使用最稳定的 GitHub Trending RSS
    gh_trending_url = "https://raw.githubusercontent.com/isboyjc/github-trending-api/main/data/daily/all.xml"
    all_new_items.extend(fetch_rss(gh_trending_url))
    return all_new_items

def merge_and_save(existing, new_items):
    name_map = {item["name"]: item for item in existing.get("items", [])}
    for item in new_items:
        name_map[item["name"]] = item
        
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=CUTOFF_DAYS)).isoformat()
    kept_items = [v for v in name_map.values() if v.get("source_ts", "9999") >= cutoff_date]
    
    result = {
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "items": kept_items
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        
    print(f"每日开源补充完成。本次抓取 {len(new_items)} 条。")

if __name__ == "__main__":
    existing_data = load_existing()
    new_data = scrape_extra_sources()
    merge_and_save(existing_data, new_data)
