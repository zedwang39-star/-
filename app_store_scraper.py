import json
import os
import datetime
import re
import time
import requests
import urllib.parse
from google_play_scraper import search, app as gplay_app

DATA_FILE = "data.json"

COUNTRIES = {
    "sa": "沙特", "ae": "阿联酋", "qa": "卡塔尔", "kw": "科威特", "bh": "巴林", "om": "阿曼",
    "eg": "埃及", "tr": "土耳其", "us": "美国", "ca": "加拿大",
    "jp": "日本", "kr": "韩国", "tw": "中国台湾", "hk": "中国香港",
    "id": "印尼", "my": "马来西亚", "th": "泰国", "vn": "越南", "ph": "菲律宾",
}

APPSTORE_GENRES = {"game": "6014", "lifestyle": "6012", "utilities": "6002", "social": "6005"}

GPLAY_CATEGORIES = {
    "game": ["new mobile game", "pre-register game"],
    "lifestyle": ["new lifestyle app"],
    "utilities": ["new utility app"],
    "social": ["new social app"],
}

# 仅排除明显的纯海外巨头，保留中小出海团队
OVERSEAS_BLACKLIST = ["Facebook", "Meta", "Google", "Apple", "Amazon", "Microsoft", "Netflix", "Spotify", "TikTok", "Supercell", "Zynga", "King", "EA", "Gameloft", "Riot", "Roblox", "Epic Games"]

def is_target_developer(dev_name: str) -> bool:
    return not any(bad.lower() in dev_name.lower() for bad in OVERSEAS_BLACKLIST)

def is_within_180_days(release_str: str) -> bool:
    """半年内首发或未来预约，宽松时间窗以保障数据量"""
    if not release_str: return False
    try:
        for fmt in ("%Y-%m-%d", "%b %d, %Y"):
            try:
                dt = datetime.datetime.strptime(release_str[:10], fmt).replace(tzinfo=datetime.timezone.utc)
                now = datetime.datetime.now(datetime.timezone.utc)
                return dt > now or (now - dt).days <= 180
            except ValueError:
                continue
        return False
    except Exception:
        return False

def scrape_appstore(country_code: str, country_name: str) -> list:
    items = []
    for cat_key, genre_id in APPSTORE_GENRES.items():
        for feed_type in ["topfreeapplications", "topgrossingapplications"]:
            url = f"https://itunes.apple.com/{country_code}/rss/{feed_type}/limit=50/genre={genre_id}/json"
            try:
                r = requests.get(url, timeout=5)  # 短超时，失败即跳过
                r.raise_for_status()
                for entry in r.json().get("feed", {}).get("entry", []):
                    app_id = entry.get("id", {}).get("attributes", {}).get("im:id")
                    if not app_id: continue
                    # Lookup 也用短超时
                    lr = requests.get(f"https://itunes.apple.com/lookup?id={app_id}&country={country_code}", timeout=5)
                    result = lr.json().get("results", [])
                    if not result: continue
                    info = result[0]
                    release_date = info.get("releaseDate", "")
                    if not is_within_180_days(release_date): continue
                    dev_name = info.get("artistName", "")
                    if not is_target_developer(dev_name): continue
                    items.append({
                        "name": info.get("trackName", ""), "platform": "app_store", "category": cat_key,
                        "domestic": dev_name, "overseas": f"{country_name} App Store",
                        "expected": "预约中" if datetime.datetime.strptime(release_date[:10], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc) > datetime.datetime.now(datetime.timezone.utc) else "已上线",
                        "expected_raw": release_date[:10], "source_ts": datetime.date.today().isoformat(),
                        "source_label": f"App Store {country_name}", "source_url": info.get("trackViewUrl", ""),
                        "basis": "P1 半年内首发/预约", "contact": "—", "pinned": False
                    })
            except Exception:
                pass  # 静默跳过，绝不阻塞
    return items

def scrape_gplay(country_code: str, country_name: str) -> list:
    items = []
    for cat_key, keywords in GPLAY_CATEGORIES.items():
        for keyword in keywords:
            try:
                results = search(keyword, lang="en", country=country_code, n_hits=15)
                for r in results:
                    app_id = r.get("appId")
                    if not app_id: continue
                    detail = gplay_app(app_id, lang="en", country=country_code)
                    released = detail.get("released", "")
                    is_preregister = "pre-register" in keyword.lower()
                    if not is_preregister and not is_within_180_days(released): continue
                    dev_name = detail.get("developer", "")
                    if not is_target_developer(dev_name): continue
                    items.append({
                        "name": detail.get("title", ""), "platform": "google", "category": cat_key,
                        "domestic": dev_name, "overseas": f"{country_name} Google Play",
                        "expected": "预约中" if is_preregister or not released else "已上线",
                        "expected_raw": released or "预约阶段", "source_ts": datetime.date.today().isoformat(),
                        "source_label": f"Google Play {country_name}", "source_url": detail.get("url", ""),
                        "basis": "P1 半年内/预约", "contact": "—", "pinned": False
                    })
            except Exception:
                pass
    return items

def scrape_taptap(is_global=False) -> list:
    """TapTap 国内/国际预约榜（预约 = 即将上线）"""
    items = []
    domain = "taptap.io" if is_global else "taptap.cn"
    url = f"https://www.{domain}/webapiv2/app-top/v2/hits?platform=android&type_name=reserve&dataSource=Android"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15",
        "Referer": f"https://www.{domain}/",
        "X-UA": "V=1&PN=WebM&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=iOS&DS=Android&OS=iOS&OSV=18.5"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        for game in resp.json().get("data", {}).get("list", []):
            title = game.get("title") or game.get("name", "未知游戏")
            app_id = game.get("app_id") or game.get("id")
            items.append({
                "name": title, "platform": "other", "category": "game",
                "domestic": "国内出海厂商" if is_global else "国内厂商",
                "overseas": "全球" if is_global else "中国大陆",
                "expected": "预约中", "expected_raw": "TapTap 预约", "source_ts": datetime.date.today().isoformat(),
                "source_label": f"TapTap {'国际' if is_global else '国内'}预约榜",
                "source_url": f"https://www.{domain}/app/{app_id}" if app_id else f"https://www.{domain}/search/{urllib.parse.quote(title)}",
                "basis": "P0 预约榜（即将上线）", "contact": "—", "pinned": False
            })
    except Exception:
        pass
    return items

def scrape_all() -> list:
    all_items = []
    for code, name in COUNTRIES.items():
        all_items.extend(scrape_appstore(code, name))
        all_items.extend(scrape_gplay(code, name))
        time.sleep(0.1)
    all_items.extend(scrape_taptap(is_global=False))
    all_items.extend(scrape_taptap(is_global=True))
    return all_items

def merge_and_save(existing, new_items):
    name_map = {}
    for item in existing.get("items", []):
        if item.get("platform") not in ["app_store", "google"]:
            name_map[item["name"]] = item
    for item in new_items:
        name_map[item["name"]] = item
    cutoff = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    kept = [v for v in name_map.values() if v.get("source_ts", "9999") >= cutoff]
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.datetime.utcnow().isoformat() + "Z", "items": kept}, f, ensure_ascii=False, indent=2)
    print(f"完成。新增 {len(new_items)} 条，库中共 {len(kept)} 条。")

if __name__ == "__main__":
    existing = json.load(open(DATA_FILE, "r", encoding="utf-8")) if os.path.exists(DATA_FILE) else {"items": []}
    merge_and_save(existing, scrape_all())
