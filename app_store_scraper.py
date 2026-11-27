import json
import os
import datetime
import re
import time
import requests
import urllib.parse
import xml.etree.ElementTree as ET
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
    "game": ["pre-register game", "new mobile game"],
    "lifestyle": ["pre-register lifestyle"],
    "utilities": ["new utility app"],
    "social": ["new social app"],
}

OVERSEAS_BLACKLIST = ["Facebook", "Meta", "Google", "Apple", "Amazon", "Microsoft", "Netflix", "Spotify", "TikTok", "Supercell", "Zynga", "King", "EA", "Gameloft", "Riot", "Roblox", "Epic Games"]

def is_target_developer(dev_name: str) -> bool:
    return not any(bad.lower() in dev_name.lower() for bad in OVERSEAS_BLACKLIST)

def is_within_180_days(date_str: str) -> bool:
    if not date_str: return False
    try:
        for fmt in ("%Y-%m-%d", "%b %d, %Y", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.datetime.strptime(date_str[:19], fmt).replace(tzinfo=datetime.timezone.utc)
                now = datetime.datetime.now(datetime.timezone.utc)
                return dt > now or (now - dt).days <= 180
            except ValueError:
                continue
        return False
    except Exception:
        return False

# ========== 新增：AppAgg 非榜单新上架 RSS ==========
def scrape_appagg_rss():
    """从 AppAgg 抓取纯新上架的应用/游戏，打破榜单限制"""
    items = []
    # AppAgg 提供了按类别和时间的新上架 RSS
    rss_urls = [
        ("https://appagg.com/rss/new/?hl=en", "app_store", "AppAgg 新上架应用"),
        ("https://appagg.com/rss/new-games/?hl=en", "app_store", "AppAgg 新上架游戏")
    ]
    
    for url, platform, label in rss_urls:
        try:
            req = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            root = ET.fromstring(req.content)
            entries = root.findall(".//item")
            
            for entry in entries[:30]: # 每个源取前30条
                title = (entry.findtext("title") or "").strip()
                link = (entry.findtext("link") or "").strip()
                pub_date = (entry.findtext("pubDate") or "")
                
                if not title or not link: continue
                # 粗略过滤非近期数据
                if not is_within_180_days(pub_date) and pub_date: continue
                
                # 判断是否包含出海/国内厂商特征（通过标题或粗略过滤）
                # 这里不再做严苛的开发者过滤，因为 RSS 不提供，交给用户在前端人工筛选
                items.append({
                    "name": title,
                    "platform": platform, 
                    "category": "game" if "game" in url else "app",
                    "domestic": "未知（待核实）", 
                    "overseas": "海外（非榜单新上架）",
                    "expected": "已上线", 
                    "expected_raw": pub_date[:16] if pub_date else "近期",
                    "source_ts": datetime.date.today().isoformat(),
                    "source_label": label, 
                    "source_url": link,
                    "basis": "P1 RSS 源时间轴", 
                    "contact": "—", 
                    "pinned": False
                })
        except Exception as e:
            print(f"AppAgg RSS 抓取失败: {e}")
            
    return items

# ========== App Store 榜单抓取（保留作为补充） ==========
def scrape_appstore(country_code: str, country_name: str) -> list:
    items = []
    for cat_key, genre_id in APPSTORE_GENRES.items():
        for feed_type in ["topfreeapplications"]: # 只抓免费榜，减轻压力
            url = f"https://itunes.apple.com/{country_code}/rss/{feed_type}/limit=50/genre={genre_id}/json"
            try:
                r = requests.get(url, timeout=5)
                r.raise_for_status()
                for entry in r.json().get("feed", {}).get("entry", []):
                    app_id = entry.get("id", {}).get("attributes", {}).get("im:id")
                    if not app_id: continue
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
                        "expected": "预约中" if is_within_180_days(release_date) and datetime.datetime.strptime(release_date[:10], "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc) > datetime.datetime.now(datetime.timezone.utc) else "已上线",
                        "expected_raw": release_date[:10], "source_ts": datetime.date.today().isoformat(),
                        "source_label": f"App Store {country_name}", "source_url": info.get("trackViewUrl", ""),
                        "basis": "P1 榜单半年内首发/预约", "contact": "—", "pinned": False
                    })
            except Exception:
                pass
    return items

# ========== Google Play 搜索抓取（保留预约搜索） ==========
def scrape_gplay(country_code: str, country_name: str) -> list:
    items = []
    for cat_key, keywords in GPLAY_CATEGORIES.items():
        for keyword in keywords:
            try:
                results = search(keyword, lang="en", country=country_code, n_hits=10)
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
                        "basis": "P1 预约/半年内首发", "contact": "—", "pinned": False
                    })
            except Exception:
                pass
    return items

# ========== TapTap 预约榜 ==========
def scrape_taptap(is_global=False) -> list:
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
    
    print("1. 抓取 AppAgg 非榜单新上架...")
    all_items.extend(scrape_appagg_rss())
    
    print("2. 抓取 16 国 App Store 榜单补充...")
    for code, name in COUNTRIES.items():
        all_items.extend(scrape_appstore(code, name))
        all_items.extend(scrape_gplay(code, name))
        time.sleep(0.1)
        
    print("3. 抓取 TapTap 预约榜...")
    all_items.extend(scrape_taptap(is_global=False))
    all_items.extend(scrape_taptap(is_global=True))
    
    return all_items

def merge_and_save(existing, new_items):
    name_map = {}
    # 保留非商店数据（如第三方资讯）
    for item in existing.get("items", []):
        if item.get("platform") not in ["app_store", "google"]:
            name_map[item["name"]] = item
    # 加入新抓取的数据
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
