import json
import os
import datetime
import requests

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

def scrape_taptap_upcoming():
    url = "https://www.taptap.cn/webapiv2/app-top/v2/hits?platform=android&type_name=reserve&dataSource=Android"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://www.taptap.cn/",
        "Accept": "application/json, text/plain, */*",
        "X-UA": "V=1&PN=WebM&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=iOS&DS=Android&UID=12f0a48b-bd25-4dce-9d50-27924e83da1d&OS=iOS&OSV=18.5"
    }
    
    items = []
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        
        game_list = data.get("data", {}).get("list", [])
        if not game_list:
            print("TapTap 返回数据为空，可能是接口结构变更或风控拦截")
            return items
            
        for game in game_list:
            title = game.get("title") or game.get("name", "未知游戏")
            app_id = game.get("app_id") or game.get("id")  # 提取 ID
            today = datetime.date.today().isoformat()
            
            # 构建 TapTap 详情页链接
            source_url = f"https://www.taptap.cn/app/{app_id}" if app_id else ""
            
            items.append({
                "name": title,
                "category": "game",
                "domestic": "待确认",
                "overseas": "待确认",
                "expected": "TBD",
                "expected_raw": "查看 TapTap 详情",
                "source_ts": today,
                "source_label": "TapTap 预约榜",
                "source_url": source_url,          # 新增：链接字段
                "basis": "P0 TapTap 预约榜自动抓取",
                "contact": "—",
                "pinned": False
            })
            
    except Exception as e:
        print(f"抓取 TapTap 预约榜失败: {e}")
    return items

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
        
    print(f"完成。本次抓取 {len(new_items)} 条，合并去重后保留 {len(kept_items)} 条。")

if __name__ == "__main__":
    existing_data = load_existing()
    new_data = scrape_taptap_upcoming()
    merge_and_save(existing_data, new_data)
