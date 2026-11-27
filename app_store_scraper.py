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

# ========== 扩充后的国家/地区列表 (16个) ==========
COUNTRIES = {
    # 海湾六国
    "sa": "沙特", "ae": "阿联酋", "qa": "卡塔尔", "kw": "科威特", "bh": "巴林", "om": "阿曼",
    # 其他中东/北非
    "eg": "埃及", "tr": "土耳其",
    # 北美
    "us": "美国", "ca": "加拿大",
    # 东亚
    "jp": "日本", "kr": "韩国", "tw": "中国台湾", "hk": "中国香港",
    # 东南亚
    "id": "印尼", "my": "马来西亚", "th": "泰国", "vn": "越南", "ph": "菲律宾",
}

APPSTORE_GENRES = {
    "game": "6014", "lifestyle": "6012", "utilities": "6002", "social": "6005"
}

# 增加 Google Play 的预约关键词搜索
GPLAY_CATEGORIES = {
    "game": ["new mobile game", "pre-register game", "pre-register rpg"],
    "lifestyle": ["new lifestyle app", "pre-register lifestyle"],
    "utilities": ["new utility app"],
    "social": ["new social app"],
}

# ========== 国内开发者识别 ==========
CN_DEV_KEYWORDS = [
    "科技", "网络", "信息", "软件", "互动", "游戏", "数码", "无线", "移动", "娱乐", "文化", "传媒",
    "北京", "上海", "深圳", "广州", "杭州", "成都", "厦门", "福州", "苏州", "武汉", "珠海", "南京", "西安",
    ".cn", "zh_", "cn_",
    "Tencent", "NetEase", "ByteDance", "Alibaba", "Baidu", "Xiaomi", "Huawei", "Bilibili",
    "FunPlus", "Lilith", "miHoYo", "HoYoverse", "Yostar", "Hypergryph", "Papergames",
    "Yotta", "LongE", "Perfect World", "37 Interactive", "Efun", "IGG", "Tap4Fun", "Habby",
    "Farlight", "Dragonest", "Archosaur", "Moonton", "KingsGroup", "Onemt", "Joycast",
    "Manus", "Genspark", "Meshy", "Tripo", "PixVerse", "DeepSeek", "Moonshot", "StepFun",
    "01.AI", "XVERSE", "AIsphere", "ModelBest", "Lightwheel", "Vast", "Luchen", "HelloTalk",
    "Appxy", "Dahua", "Easyroid", "VeePro", "Romangic", "WayShot",
    "Century", "Kingsoft", "Cheetah", "Changyou", "Shanda", "Youzu", "Giant", "Perfect",
]

def is_cn_developer(dev_name: str, dev_url: str = "") -> bool:
    text = (dev_name + " " + dev_url).lower()
    return any(kw.lower() in text for kw in CN_DEV_KEYWORDS)

# ========== +86 手机号提取 ==========
PHONE_PATTERN = re.compile(r'(?:\+?86[\s\-]?)?(1[3-9]\d{9})')

def extract_phone_from_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
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

# ========== 严格首发时间判定 ==========
def is_appstore_strict_release(release_str: str, current_version_str: str) -> bool:
    if not release_str: return False
    try:
        release_dt = datetime.datetime.strptime(release_str[:10], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        if release_dt > now: return True
        if (now - release_dt).days > 90: return False
        if current_version_str:
            cv_dt = datetime.datetime.strptime(current_version_str[:10], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
            if (cv_dt - release_dt).days > 30: return False
        return True
    except Exception:
        return False

def is_gplay_strict_release(released_str: str) -> bool:
    if not released_str: return False
    try:
        release_dt = datetime.datetime.strptime(released_str, "%b %d, %Y").replace(tzinfo=datetime.timezone.utc)
        if (datetime.datetime.now(datetime.timezone.utc) - release_dt).days <= 90:
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
                    
                    if not is_appstore_strict_release(release_date, current_version_date): continue

                    dev_name = info.get("artistName", "")
                    dev_url = info.get("sellerUrl", "") or info.get("artistViewUrl", "")
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
                        "basis": "P1 App Store 近3月首发/预约",
                        "contact": "—",
                        "pinned": False
                    })
            except Exception as e:
                print(f"App Store {country_name}/{cat_key} 失败: {e}")
    return items

# ========== 抓取 Google Play ==========
def scrape_gplay(country_code: str, country_name: str):
    items = []
    for cat_key, keywords in GPLAY_CATEGORIES.items():
        for keyword in keywords:
            try:
                results = search(keyword, lang="en", country=country_code, n_hits=30)
                for r in results:
                    app_id = r.get("appId")
                    if not app_id: continue
                    
                    detail = gplay_app(app_id, lang="en", country=country_code)
                    released = detail.get("released", "")
                    is_preregister = "pre-register" in keyword.lower()
                    
                    # 非预约产品严格限制时间；预约产品放行
                    if not is_preregister and not is_gplay_strict_release(released): continue
                    
                    dev_name = detail.get("developer", "")
                    dev_url = detail.get("developerWebsite", "") or detail.get("url", "")
                    
                    phone = extract_phone_from_url(dev_url)
                    is_cn = is_cn_developer(dev_name, dev_url)
                    if not phone and not is_cn: continue

                    items.append({
                        "name": detail.get("title", ""),
                        "platform": "google",
                        "category": cat_key,
                        "domestic": dev_name,
                        "overseas": f"{country_name} Google Play",
                        "expected": "预约中" if is_preregister or not released else "已上线",
                        "expected_raw": released or "预约阶段",
                        "source_ts": datetime.date.today().isoformat(),
                        "source_label": f"Google Play {country_name}",
                        "source_url": detail.get("url", ""),
                        "basis": "P1 Google 近3月首发/预约 (+86/国内企业)",
                        "contact": phone or "国内企业(未留+86)",
                        "pinned": False
                    })
            except Exception as e:
                print(f"Google Play {country_name}/{cat_key}/{keyword} 失败: {e}")
    return items

# ========== 抓取 TapTap 国内预约榜 ==========
def scrape_taptap_cn():
    items = []
    url = "https://www.taptap.cn/webapiv2/app-top/v2/hits?platform=android&type_name=reserve&dataSource=Android"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
        "Referer": "https://www.taptap.cn/",
        "Accept": "application/json, text/plain, */*",
        "X-UA": "V=1&PN=WebM&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=iOS&DS=Android&UID=12f0a48b-bd25-4dce-9d50-27924e83da1d&OS=iOS&OSV=18.5"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        game_list = data.get("data", {}).get("list", [])
        for game in game_list:
            title = game.get("title") or game.get("name", "未知游戏")
            app_id = game.get("app_id") or game.get("id")
            source_url = f"https://www.taptap.cn/app/{app_id}" if app_id else f"https://www.taptap.cn/search/{urllib.parse.quote(title)}"
            
            items.append({
                "name": title,
                "platform": "other",
                "category": "game",
                "domestic": "国内厂商",
                "overseas": "中国大陆",
                "expected": "预约中",
                "expected_raw": "TapTap 国内预约",
                "source_ts": datetime.date.today().isoformat(),
                "source_label": "TapTap 国内预约榜",
                "source_url": source_url,
                "basis": "P0 国内即将上线",
                "contact": "—",
                "pinned": False
            })
    except Exception as e:
        print(f"TapTap.cn 抓取失败: {e}")
    return items

# ========== 抓取 TapTap 国际版预约榜 ==========
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
            source_url = f"https://www.taptap.io/app/{app_id}" if app_id else f"https://www.taptap.io/search/{urllib.parse.quote(title)}"
            
            items.append({
                "name": title,
                "platform": "other",
                "category": "game",
                "domestic": "国内出海厂商",
                "overseas": "全球",
                "expected": "预约中",
                "expected_raw": "TapTap 国际预约",
                "source_ts": datetime.date.today().isoformat(),
                "source_label": "TapTap 国际预约榜",
                "source_url": source_url,
                "basis": "P0 海外即将上线",
                "contact": "—",
                "pinned": False
            })
    except Exception as e:
        print(f"TapTap.io 抓取失败: {e}")
    return items

# ========== 主函数与合并 ==========
def scrape_all_stores():
    all_items = []
    for code, name in COUNTRIES.items():
        print(f"正在抓取 {name} ({code}) ...")
        all_items.extend(scrape_appstore(code, name))
        all_items.extend(scrape_gplay(code, name))
        time.sleep(0.5)
        
    print("正在抓取 TapTap 国内预约榜...")
    all_items.extend(scrape_taptap_cn())
    
    print("正在抓取 TapTap 国际预约榜...")
    all_items.extend(scrape_taptap_global())
    
    return all_items

def merge_and_save(existing, new_items):
    # 保留旧数据中的 "other" 类型（三方资讯），清掉旧的应用商店数据
    name_map = {}
    for item in existing.get("items", []):
        if item.get("platform") not in ["app_store", "google"]:
            name_map[item["name"]] = item

    for item in new_items:
        name_map[item["name"]] = item

    cutoff_date = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    kept = [v for v in name_map.values() if v.get("source_ts", "9999") >= cutoff_date]

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.datetime.utcnow().isoformat() + "Z", "items": kept}, f, ensure_ascii=False, indent=2)
    print(f"抓取完成。本次新增 {len(new_items)} 条，最终库中共 {len(kept)} 条。")

if __name__ == "__main__":
    existing = json.load(open(DATA_FILE, "r", encoding="utf-8")) if os.path.exists(DATA_FILE) else {"items": []}
    merge_and_save(existing, scrape_all_stores())
