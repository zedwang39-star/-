import json
import os
import datetime
import re
import time
import requests
import urllib.parse
from google_play_scraper import search, app as gplay_app

DATA_FILE = "data.json"

# ========== 地区与品类配置 ==========
COUNTRIES = {
    "us": "美国", "sa": "沙特", "jp": "日本",
    "kr": "韩国", "cn": "中国大陆", "hk": "中国香港"
}

APPSTORE_GENRES = {
    "game": "6014", "lifestyle": "6012", "utilities": "6002", "social": "6005"
}

GPLAY_CATEGORIES = {
    "game": "new mobile game", "lifestyle": "new lifestyle app",
    "utilities": "new utility app", "social": "new social app",
}

# ========== 国内开发者识别 ==========
CN_DEV_KEYWORDS = [
    "科技", "网络", "信息", "软件", "互动", "游戏", "数码", "无线", "移动", "娱乐", "文化", "传媒",
    "北京", "上海", "深圳", "广州", "杭州", "成都", "厦门", "福州", "苏州", "武汉", "珠海",
    ".cn", "china", "chinese", "zh_", "cn_", "hk", "macau",
    "Tencent", "NetEase", "ByteDance", "Alibaba", "Baidu", "Xiaomi", "Huawei", "Bilibili",
    "FunPlus", "Lilith", "miHoYo", "HoYoverse", "Yostar", "Hypergryph", "Papergames", "Century",
    "Yotta", "LongE", "Perfect World", "37 Interactive", "Efun", "IGG", "Tap4Fun", "Habby",
    "Farlight", "Dragonest", "Archosaur", "Moonton", "KingsGroup", "Onemt", "Joycast"
]

def is_cn_developer(dev_name: str, dev_url: str = "") -> bool:
    text = (dev_name + " " + dev_url).lower()
    return any(kw.lower() in text for kw in CN_DEV_KEYWORDS)

# ========== +86 手机号提取 (仅限中国大陆手机格式) ==========
# 匹配 +86 138xxxx 或者不带+86的 138xxxx
PHONE_PATTERN = re.compile(r'(?:\+?86[\s\-]?)?(1[3-9]\d{9})')

def extract_phone_from_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = r.apparent_encoding
        matches = PHONE_PATTERN.findall(r.text)
        if matches:
            return f"+86 {matches[0]}"
        return ""
    except Exception:
        return ""

def is_appstore_target_date(release_str: str) -> bool:
    """App Store：往推2个月(60天) OR 未来预约"""
    if not release_str: return False
    try:
        release_dt = datetime.datetime.fromisoformat(release_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        # 1. 日期在未来 (预约产品) 2. 过去60天内
        return release_dt > now or (now - release_dt).days <= 60
    except Exception:
        return False

# ========== App Store 抓取 ==========
def scrape_appstore(country_code: str, country_name: str):
    items = []
    feed_types = ["topfreeapplications", "topgrossingapplications"]
    
    for cat_key, genre_id in APPSTORE_GENRES.items():
        for feed_type in feed_types:
            url = f"https://itunes.apple.com/{country_code}/rss/{feed_type}/limit=100/genre={genre_id}/json"
            try:
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                entries = r.json().get("feed", {}).get("entry", [])
                for entry in entries:
                    app_id = entry.get("id", {}).get("attributes", {}).get("im:id")
                    if not app_id: continue
                    
                    lr = requests.get(f"https://itunes.apple.com/lookup?id={app_id}&country={country_code}", timeout=10)
                    result = lr.json().get("results", [])
                    if not result: continue
                    
                    info = result[0]
                    released = info.get("releaseDate", "")
                    
                    # 拦截：时间必须符合近2个月或未来
                    if not is_appstore_target_date(released): continue

                    dev_name = info.get("artistName", "")
                    dev_url = info.get("sellerUrl", "") or info.get("artistViewUrl", "")
                    
                    # App Store 暂时保留国内开发者识别
                    if not is_cn_developer(dev_name, dev_url): continue

                    items.append({
                        "name": info.get("trackName", ""),
                        "platform": "app_store", # 打标签
                        "category": cat_key,
                        "domestic": dev_name,
                        "overseas": f"{country_name} App Store",
                        "expected": "预约中" if is_appstore_target_date(released) and datetime.datetime.fromisoformat(released.replace("Z", "+00:00")) > datetime.datetime.now(datetime.timezone.utc) else "已上线",
                        "expected_raw": released[:10],
                        "source_ts": datetime.date.today().isoformat(),
                        "source_label": f"App Store {country_name}",
                        "source_url": info.get("trackViewUrl", ""),
                        "basis": "P1 App Store 近2月新上架/预约",
                        "contact": extract_phone_from_url(dev_url) or "—",
                        "pinned": False
                    })
            except Exception as e:
                print(f"App Store {country_name}/{cat_key} 失败: {e}")
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
                dev_name = detail.get("developer", "")
                dev_url = detail.get("developerWebsite", "") or detail.get("url", "")
                
                # Google Play 核心逻辑：必须抓到 +86 手机号，或者是国内开发者
                phone = extract_phone_from_url(dev_url)
                is_cn = is_cn_developer(dev_name, dev_url)
                
                if not phone and not is_cn:
                    continue # 两者都不满足，直接抛弃

                items.append({
                    "name": detail.get("title", ""),
                    "platform": "google", # 打标签
                    "category": cat_key,
                    "domestic": dev_name,
                    "overseas": f"{country_name} Google Play",
                    "expected": "已上线",
                    "expected_raw": "近期上架",
                    "source_ts": datetime.date.today().isoformat(),
                    "source_label": f"Google Play {country_name}",
                    "source_url": detail.get("url", ""),
                    "basis": "P1 Google 筛选 (+86/国内企业)",
                    "contact": phone or "国内企业(未留+86)",
                    "pinned": False
                })
        except Exception as e:
            print(f"Google Play {country_name}/{cat_key} 失败: {e}")
    return items

# ========== TapTap 国际版 (归入 Other) ==========
def scrape_taptap_global():
    items = []
    url = "https://www.taptap.io/webapiv2/app-top/v2/hits?platform=android&type_name=reserve&dataSource=Android"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15",
        "Referer": "https://www.taptap.io/",
        "X-UA": "V=1&PN=WebM&LANG=en_US&VN_CODE=102&LOC=US&PLT=iOS&DS=Android&OS=iOS&OSV=18.5"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        data = resp.json()
        for game in data.get("data", {}).get("list", []):
            title = game.get("title") or game.get("name", "Unknown")
            app_id = game.get("app_id") or game.get("id")
            items.append({
                "name": title,
                "platform": "other", # 打标签
                "category": "game",
                "domestic": "国内出海厂商",
                "overseas": "全球",
                "expected": "即将上线/预约中",
                "expected_raw": "TapTap.io 预约",
                "source_ts": datetime.date.today().isoformat(),
                "source_label": "TapTap.io 国际预约",
                "source_url": f"https://www.taptap.io/app/{app_id}" if app_id else "",
                "basis": "P0 TapTap海外预约榜",
                "contact": "—",
                "pinned": False
            })
    except Exception as e:
        print(f"TapTap.io 失败: {e}")
    return items

def scrape_all_stores():
    all_items = []
    for code, name in COUNTRIES.items():
        print(f"正在抓取 {name} ...")
        all_items.extend(scrape_appstore(code, name))
        all_items.extend(scrape_gplay(code, name))
        time.sleep(1)
    all_items.extend(scrape_taptap_global())
    return all_items

def merge_and_save(existing, new_items):
    name_map = {item["name"]: item for item in existing.get("items", [])}
    for item in new_items: name_map[item["name"]] = item

    cutoff_date = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    kept = []
    for v in name_map.values():
        if v.get("source_ts", "9999") < cutoff_date: continue
        if "/" in v.get("name", "") and "TapTap" not in v.get("source_label", ""): continue
        kept.append(v)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.datetime.utcnow().isoformat() + "Z", "items": kept}, f, ensure_ascii=False, indent=2)
    print(f"应用商店抓取完成。新增 {len(new_items)} 条，库中共 {len(kept)} 条。")

if __name__ == "__main__":
    existing = json.load(open(DATA_FILE, "r", encoding="utf-8")) if os.path.exists(DATA_FILE) else {"items": []}
    merge_and_save(existing, scrape_all_stores())
