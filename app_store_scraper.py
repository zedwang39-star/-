import json
import os
import datetime
import re
import time
import requests
import urllib.parse
from bs4 import BeautifulSoup
from google_play_scraper import search, app as gplay_app

DATA_FILE = "data.json"

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

# ========== 极度严格的国内主体特征（剔除 hk、china 等模糊词） ==========
CN_DEV_KEYWORDS = [
    "科技", "网络", "信息", "软件", "互动", "游戏", "数码", "无线", "移动", "娱乐", "文化", "传媒",
    "北京", "上海", "深圳", "广州", "杭州", "成都", "厦门", "福州", "苏州", "武汉", "珠海",
    ".cn", "zh_", "cn_",
    "Tencent", "NetEase", "ByteDance", "Alibaba", "Baidu", "Xiaomi", "Huawei", "Bilibili",
    "FunPlus", "Lilith", "miHoYo", "HoYoverse", "Yostar", "Hypergryph", "Papergames",
    "Yotta", "LongE", "Perfect World", "37 Interactive", "Efun", "IGG", "Tap4Fun", "Habby",
    "Farlight", "Dragonest", "Archosaur", "Moonton", "KingsGroup", "Onemt", "Joycast",
    "Manus", "Genspark", "Meshy", "Tripo", "PixVerse", "DeepSeek", "Moonshot", "StepFun",
    "01.AI", "XVERSE", "AIsphere", "ModelBest", "Lightwheel", "Vast", "Luchen", "HelloTalk",
    "Appxy", "Dahua", "Easyroid", "VeePro", "Romangic", "WayShot"
]

def is_cn_developer(dev_name: str, dev_url: str = "") -> bool:
    text = (dev_name + " " + dev_url).lower()
    return any(kw.lower() in text for kw in CN_DEV_KEYWORDS)

# ========== 深度 +86 手机号提取 ==========
PHONE_PATTERN = re.compile(r'(?:\+?86[\s\-]?)?(1[3-9]\d{9})')

def extract_phone_from_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
        matches = PHONE_PATTERN.findall(soup.get_text(separator=' '))
        if matches:
            for m in matches:
                if len(m) == 11 and m.startswith("1"):
                    return f"+86 {m}"
        return ""
    except Exception:
        return ""

# ========== 极其严格的首发时间判定 ==========
def is_appstore_strict_release(release_str: str, current_version_str: str) -> bool:
    """App Store：必须是近 60 天内首发，且不能是老应用更新"""
    if not release_str: return False
    try:
        release_dt = datetime.datetime.strptime(release_str[:10], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # 1. 绝对限制：首发时间超过 60 天直接滚蛋
        if (now - release_dt).days > 60:
            return False
            
        # 2. 如果是老应用重上架：当前版本更新日期比起首发日期晚了 30 天以上，绝对是老游戏！
        if current_version_str:
            cv_dt = datetime.datetime.strptime(current_version_str[:10], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
            if (cv_dt - release_dt).days > 30:
                return False
                
        return True
    except Exception:
        return False

def is_gplay_strict_release(released_str: str) -> bool:
    """Google Play：只认 released 字段，解析失败或时间不对直接抛弃"""
    if not released_str: return False
    try:
        # 格式如 "Oct 18, 2023"
        release_dt = datetime.datetime.strptime(released_str, "%b %d, %Y").replace(tzinfo=datetime.timezone.utc)
        if (datetime.datetime.now(datetime.timezone.utc) - release_dt).days <= 60:
            return True
        return False
    except Exception:
        return False

# ========== 抓取 App Store ==========
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
                    release_date = info.get("releaseDate", "")
                    current_version_date = info.get("currentVersionReleaseDate", "")
                    
                    # 严苛时间拦截
                    if not is_appstore_strict_release(release_date, current_version_date): continue

                    dev_name = info.get("artistName", "")
                    dev_url = info.get("sellerUrl", "") or info.get("artistViewUrl", "")
                    
                    # 严苛主体拦截
                    if not is_cn_developer(dev_name, dev_url): continue

                    items.append({
                        "name": info.get("trackName", ""),
                        "platform": "app_store",
                        "category": cat_key,
                        "domestic": dev_name,
                        "overseas": f"{country_name} App Store",
                        "expected": "预约中" if datetime.datetime.strptime(release_date[:10], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc) > datetime.datetime.now(datetime.timezone.utc) else "已上线",
                        "expected_raw": release_date[:10],
                        "source_ts": datetime.date.today().isoformat(),
                        "source_label": f"App Store {country_name}",
                        "source_url": info.get("trackViewUrl", ""),
                        "basis": "P1 严格首发/预约",
                        "contact": "—",
                        "pinned": False
                    })
            except Exception as e:
                print(f"App Store {country_name}/{cat_key} 失败: {e}")
    return items

# ========== 抓取 Google Play ==========
def scrape_gplay(country_code: str, country_name: str):
    items = []
    for cat_key, keyword in GPLAY_CATEGORIES.items():
        try:
            results = search(keyword, lang="en", country=country_code, n_hits=30)
            for r in results:
                app_id = r.get("appId")
                if not app_id: continue
                
                detail = gplay_app(app_id, lang="en", country=country_code)
                released = detail.get("released", "")
                
                # 严苛时间拦截：不再用 updated 兜底，只认首发
                if not is_gplay_strict_release(released): continue
                
                dev_name = detail.get("developer", "")
                dev_url = detail.get("developerWebsite", "") or detail.get("url", "")
                
                # 严苛主体拦截 + 电话
                phone = extract_phone_from_url(dev_url)
                is_cn = is_cn_developer(dev_name, dev_url)
                if not phone and not is_cn: continue

                items.append({
                    "name": detail.get("title", ""),
                    "platform": "google",
                    "category": cat_key,
                    "domestic": dev_name,
                    "overseas": f"{country_name} Google Play",
                    "expected": "已上线",
                    "expected_raw": released,
                    "source_ts": datetime.date.today().isoformat(),
                    "source_label": f"Google Play {country_name}",
                    "source_url": detail.get("url", ""),
                    "basis": "P1 严格首发",
                    "contact": phone or "国内企业",
                    "pinned": False
                })
        except Exception as e:
            print(f"Google Play {country_name}/{cat_key} 失败: {e}")
    return items

# ========== 合并保存（含一次性大清洗） ==========
def merge_and_save(existing, new_items):
    # 1. 彻底清洗：把旧库里所有 app_store 和 google 的数据全部干掉，重新洗牌
    name_map = {}
    cleaned_count = 0
    for item in existing.get("items", []):
        if item.get("platform") in ["app_store", "google"]:
            cleaned_count += 1
            continue
        name_map[item["name"]] = item

    # 2. 加入洗白后的新数据
    for item in new_items:
        name_map[item["name"]] = item

    cutoff_date = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    kept = [v for v in name_map.values() if v.get("source_ts", "9999") >= cutoff_date]

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.datetime.utcnow().isoformat() + "Z", "items": kept}, f, ensure_ascii=False, indent=2)
    print(f"清洗了 {cleaned_count} 条旧脏数据。本次抓取新增 {len(new_items)} 条，最终保留 {len(kept)} 条。")

if __name__ == "__main__":
    existing = json.load(open(DATA_FILE, "r", encoding="utf-8")) if os.path.exists(DATA_FILE) else {"items": []}
    merge_and_save(existing, scrape_all_stores() if 'scrape_all_stores' in globals() else scrape_appstore("us", "美国") + scrape_gplay("us", "美国"))
