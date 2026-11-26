import json
import os
import datetime
import re
import time
import requests
import urllib.parse
from google_play_scraper import search, app as gplay_app

DATA_FILE = "data.json"
CUTOFF_DAYS = 90  # 近3个月

# ========== 地区与品类配置 ==========
COUNTRIES = {
    "us": "美国", "sa": "沙特", "jp": "日本",
    "kr": "韩国", "cn": "中国大陆", "hk": "中国香港"
}

# App Store 品类 ID
APPSTORE_GENRES = {
    "game": "6014",
    "lifestyle": "6012",
    "utilities": "6002",
    "social": "6005",
}

# Google Play 搜索关键词映射
GPLAY_CATEGORIES = {
    "game": "new mobile game",
    "lifestyle": "new lifestyle app",
    "utilities": "new utility app",
    "social": "new social app",
}

# ========== 方案 A：大幅扩充国内出海厂商词库 ==========
CN_DEV_KEYWORDS = [
    # 中文特征
    "科技", "网络", "信息", "软件", "互动", "游戏", "数码", "无线", "移动", "娱乐", "文化", "传媒",
    "北京", "上海", "深圳", "广州", "杭州", "成都", "厦门", "福州", "苏州", "武汉", "珠海",
    # 域名/后缀特征
    ".cn", "china", "chinese", "zh_", "cn_", "hk", "macau",
    # 国内出海大厂英文名 (Top 出海厂商)
    "Tencent", "NetEase", "ByteDance", "Alibaba", "Baidu", "Xiaomi", "Huawei", "Bilibili",
    "FunPlus", "Lilith", "miHoYo", "HoYoverse", "Yostar", "Hypergryph", "Papergames", "Century",
    "Yotta", "LongE", "Perfect World", "37 Interactive", "Efun", "IGG", "Tap4Fun", "Habby",
    "Farlight", "Dragonest", "Archosaur", "Moonton", "KingsGroup", "Onemt", "Joycast"
]

def is_cn_developer(dev_name: str, dev_url: str = "") -> bool:
    text = (dev_name + " " + dev_url).lower()
    return any(kw.lower() in text for kw in CN_DEV_KEYWORDS)

# ========== +86 电话提取 ==========
PHONE_PATTERN = re.compile(
    r'(\+?86[\s\-]?)?1[3-9]\d{9}'
    r'|(\+?86[\s\-]?)?0\d{2,3}[\s\-]?\d{7,8}'
)

def extract_phone_from_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = r.apparent_encoding
        matches = PHONE_PATTERN.findall(r.text)
        for m in matches:
            raw = "".join(m).strip()
            digits = re.sub(r'\D', '', raw)
            if len(digits) == 11 and digits.startswith("1"):
                return f"+86 {digits}"
            elif digits.startswith("86") and len(digits) == 13:
                return f"+86 {digits[2:]}"
        return ""
    except Exception:
        return ""

def within_3_months(date_str: str) -> bool:
    if not date_str:
        return False
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - dt).days <= CUTOFF_DAYS
    except Exception:
        return False

# ========== 方案 B：App Store 扩充免费榜+畅销榜 ==========
def scrape_appstore(country_code: str, country_name: str):
    items = []
    # 免费榜 (topfreeapplications) 和 畅销榜 (topgrossingapplications)
    feed_types = ["topfreeapplications", "topgrossingapplications"]
    
    for cat_key, genre_id in APPSTORE_GENRES.items():
        for feed_type in feed_types:
            url = f"https://itunes.apple.com/{country_code}/rss/{feed_type}/limit=100/genre={genre_id}/json"
            try:
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                data = r.json()
                entries = data.get("feed", {}).get("entry", [])
                for entry in entries:
                    app_id = entry.get("id", {}).get("attributes", {}).get("im:id")
                    if not app_id: continue
                    
                    lookup_url = f"https://itunes.apple.com/lookup?id={app_id}&country={country_code}"
                    lr = requests.get(lookup_url, timeout=10)
                    result = lr.json().get("results", [])
                    if not result: continue
                    
                    info = result[0]
                    released = info.get("releaseDate", "")
                    if not within_3_months(released): continue

                    dev_name = info.get("artistName", "")
                    dev_url = info.get("sellerUrl", "") or info.get("artistViewUrl", "")
                    if not is_cn_developer(dev_name, dev_url): continue

                    phone = extract_phone_from_url(dev_url)

                    items.append({
                        "name": info.get("trackName", ""),
                        "category": cat_key,
                        "domestic": dev_name,
                        "overseas": f"{country_name} App Store ({'免费' if 'free' in feed_type else '畅销'})",
                        "expected": "已上线",
                        "expected_raw": released[:10],
                        "source_ts": datetime.date.today().isoformat(),
                        "source_label": f"App Store {country_name}",
                        "source_url": info.get("trackViewUrl", ""),
                        "basis": "P1 近3月新上架/榜单",
                        "contact": phone or "—",
                        "pinned": False
                    })
            except Exception as e:
                print(f"App Store {country_name}/{cat_key}/{feed_type} 失败: {e}")
    return items

# ========== Google Play 抓取 ==========
def scrape_gplay(country_code: str, country_name: str):
    items = []
    for cat_key, keyword in GPLAY_CATEGORIES.items():
        try:
            results = search(keyword, lang="en", country=country_code, n_hits=30)
            for r in results:
                app_id = r.get("appId")
                if not app_id: continue
                
                detail = gplay_app(app_id, lang="en", country=country_code)
                updated = detail.get("updated", 0)
                if updated and (datetime.datetime.now().timestamp() - updated / 1000) > CUTOFF_DAYS * 86400:
                    continue

                dev_name = detail.get("developer", "")
                dev_url = detail.get("developerWebsite", "") or detail.get("url", "")
                if not is_cn_developer(dev_name, dev_url): continue

                phone = extract_phone_from_url(dev_url)

                items.append({
                    "name": detail.get("title", ""),
                    "category": cat_key,
                    "domestic": dev_name,
                    "overseas": f"{country_name} Google Play",
                    "expected": "已上线",
                    "expected_raw": "近期更新",
                    "source_ts": datetime.date.today().isoformat(),
                    "source_label": f"Google Play {country_name}",
                    "source_url": detail.get("url", ""),
                    "basis": "P1 近3月新上架/更新",
                    "contact": phone or "—",
                    "pinned": False
                })
        except Exception as e:
            print(f"Google Play {country_name}/{cat_key} 失败: {e}")
    return items

# ========== 方案 C：TapTap 国际版预约榜 ==========
def scrape_taptap_global():
    items = []
    url = "https://www.taptap.io/webapiv2/app-top/v2/hits?platform=android&type_name=reserve&dataSource=Android"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://www.taptap.io/",
        "Accept": "application/json, text/plain, */*",
        "X-UA": "V=1&PN=WebM&LANG=en_US&VN_CODE=102&LOC=US&PLT=iOS&DS=Android&UID=12f0a48b-bd25-4dce-9d50-27924e83da1d&OS=iOS&OSV=18.5"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        game_list = data.get("data", {}).get("list", [])
        
        for game in game_list:
            title = game.get("title") or game.get("name", "Unknown Game")
            app_id = game.get("app_id") or game.get("id")
            source_url = f"https://www.taptap.io/app/{app_id}" if app_id else ""
            
            items.append({
                "name": title,
                "category": "game",
                "domestic": "国内出海厂商 (TapTap.io)",
                "overseas": "全球 (预约中)",
                "expected": "即将上线/预约中",
                "expected_raw": "TapTap.io 预约",
                "source_ts": datetime.date.today().isoformat(),
                "source_label": "TapTap.io 国际预约榜",
                "source_url": source_url,
                "basis": "P0 TapTap海外预约榜",
                "contact": "—",
                "pinned": False
            })
    except Exception as e:
        print(f"TapTap.io 抓取失败: {e}")
    return items

# ========== 主函数 ==========
def scrape_all_stores():
    all_items = []
    for code, name in COUNTRIES.items():
        print(f"正在抓取 {name} ...")
        all_items.extend(scrape_appstore(code, name))
        all_items.extend(scrape_gplay(code, name))
        time.sleep(1) # 防止请求过快
        
    print("正在抓取 TapTap.io 国际版...")
    all_items.extend(scrape_taptap_global())
    
    return all_items

def merge_and_save(existing, new_items):
    name_map = {item["name"]: item for item in existing.get("items", [])}
    for item in new_items:
        name_map[item["name"]] = item

    cutoff_date = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    kept = []
    for v in name_map.values():
        if v.get("source_ts", "9999") < cutoff_date: continue
        if "/" in v.get("name", "") and v.get("source_label") != "TapTap 预约榜": continue
        kept.append(v)

    result = {"updated_at": datetime.datetime.utcnow().isoformat() + "Z", "items": kept}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"全渠道抓取完成。本次新增 {len(new_items)} 条，库中共 {len(kept)} 条。")

if __name__ == "__main__":
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {"items": []}
    new_data = scrape_all_stores()
    merge_and_save(existing, new_data)
