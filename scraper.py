import json, os, datetime, urllib.request, re

DATA_FILE = "data.json"

def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"items": []}

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")

def scrape_new_items():
    """
    在这里填入你的真实抓取逻辑。
    下面是一个最小示例：抓取一个页面，用正则提取标题和日期。
    把 URL 和正则换成你目标页面的即可。
    """
    items = []
    url = "https://example.com/news"   # ← 替换成真实信息源 URL
    try:
        html = fetch(url)
        # 示例正则：匹配 <h2>标题</h2> 和 2026-11-20 这样的日期
        # 真实使用时请根据目标页面结构调整
        for m in re.finditer(r"<h2>(.*?)</h2>.*?(\d{4}-\d{2}-\d{2})", html, re.S):
            title = re.sub(r"<.*?>", "", m.group(1)).strip()
            date_str = m.group(2)
            items.append({
                "name": title,
                "category": "game",
                "domestic": "待补充",
                "overseas": "待补充",
                "expected": "2027-01-01",
                "expected_raw": "",
                "source_ts": date_str,
                "source_label": "自动抓取",
                "basis": "自动抓取",
                "contact": "—",
                "pinned": False
            })
    except Exception as e:
        print("抓取失败:", e)
    return items

def merge_and_save(existing, new_items):
    name_map = {item["name"]: item for item in existing.get("items", [])}
    for item in new_items:
        name_map[item["name"]] = item
    cutoff = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    kept = [v for v in name_map.values() if v.get("source_ts", "9999") >= cutoff]
    result = {
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "items": kept
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"完成。本次抓取 {len(new_items)} 条，保留 {len(kept)} 条。")

if __name__ == "__main__":
    merge_and_save(load_existing(), scrape_new_items())
