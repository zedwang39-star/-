import json
import os
import datetime
import re
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

APPSTORE_GENRES = {
    "game": "6014",
    "lifestyle": "6012",
    "utilities": "6002",
    "social": "6005",
}

# Google Play 搜索关键词映射
GPLAY_CATEGORIES = {
    "game": "new game",
    "lifestyle": "new lifestyle app",
    "utilities": "new utility app",
    "social": "new social app",
}

# ========== 国内开发者识别 ==========
CN_DEV_KEYWORDS = [
    "科技", "网络", "信息", "软件", "互动", "游戏", "数码", "无线", "移动",
    "北京", "上海", "深圳", "广州", "杭州", "成都",
    ".cn", "china", "chinese", "zh_", "cn_",
    "Tencent", "NetEase", "ByteDance", "Alibaba", "Baidu", "Xiaomi", "Huawei",
    "Lilith", "Hypergryph", "miHoYo", "HoYoverse", "Yostar", "Papergames",
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
        text = r.text
        matches = PHONE_PATTERN.findall(text)
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

# ========== 时间判断 ==========
def within_3_months(date_str: str) -> bool:
    if not date_str:
        return False
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - dt).days <= CUTOFF_DAYS
    except Exception:
        return False

# ========== App Store 抓取 ==========
def scrape_appstore(country_code: str, country_name: str):
    items = []
    for cat_key, genre_id in APPSTORE_GENRES.items():
        url = (
            f"https://itunes.apple.com/{country_code}/rss/topfreeapplications/"
            f"limit=50/genre={genre_id}/json"
        )
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            entries = data.get("feed", {}).get("entry", [])
            for entry in entries:
                app_id = entry.get("id", {}).get("attributes", {}).get("im:id")
                if not app_id:
                    continue
                lookup_url = f"https://itunes.apple.com/lookup?id={app_id}&country={country_code}"
                lr = requests.get(lookup_url, timeout=10)
                lr.raise_for_status()
                result = lr.json().get("results", [])
                if not result:
                    continue
                info = result[0]
                released = info.get("releaseDate", "")
                if not within_3_months(released):
                    continue

                dev_name = info.get("artistName", "")
                dev_url = info.get("sellerUrl", "") or info.get("artistViewUrl", "")

                if not is_cn_developer(dev_name, dev_url):
                    continue

                phone = extract_phone_from_url(dev_url)

                items.append({
                    "name": info.get("trackName", ""),
                    "category": cat_key,
                    "domestic": dev_name if is_cn_developer(dev_name, dev_url) else "待确认",
                    "overseas": f"{country_name} App Store",
                    "expected": "已上线/预约中" if not info.get("currentVersionReleaseDate") else "已上线",
                    "expected_raw": released[:10] if released else "",
                    "source_ts": datetime.date.today().isoformat(),
                    "source_label": f"App Store {country_name}",
                    "source_url": info.get("trackViewUrl", ""),
                    "basis": "P1 App Store 近3月新上架/预约",
                    "contact": phone or "—",
                    "pinned": False
                })
        except Exception as e:
            print(f"App Store {country_name} / {cat_key} 失败: {e}")
    return items

# ========== Google Play 抓取 ==========
def scrape_gplay(country_code: str, country_name: str):
    items = []
    for cat_key, keyword in GPLAY_CATEGORIES.items():
        try:
            # 修复点：去掉了不支持的 sort 参数
            results = search(
                keyword,
                lang="en",
                country=country_code,
                n_hits=30
            )
            for r in results:
                app_id = r.get("appId")
                if not app_id:
                    continue
                detail = gplay_app(app_id, lang="en", country=country_code)
                
                updated = detail.get("updated", 0)
                # 严格检查更新时间是否在 90 天内
                if updated and (datetime.datetime.now().timestamp() - updated / 1000) > CUTOFF_DAYS * 86400:
                    continue

                dev_name = detail.get("developer", "")
                dev_url = detail.get("developerWebsite", "") or detail.get("url", "")

                if not is_cn_developer(dev_name, dev_url):
                    continue

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
                    "basis": "P1 Google Play 近3月新上架/更新",
                    "contact": phone or "—",
                    "pinned": False
                })
        except Exception as e:
            print(f"Google Play {country_name} / {cat_key} 失败: {e}")
    return items

# ========== 主函数 ==========
def scrape_app_stores():
    all_items = []
    for code, name in COUNTRIES.items():
        print(f"正在抓取 {name} ...")
        all_items.extend(scrape_appstore(code, name))
        all_items.extend(scrape_gplay(code, name))
    return all_items

def merge_and_save(existing, new_items):
    name_map = {item["name"]: item for item in existing.get("items", [])}
    for item in new_items:
        name_map[item["name"]] = item

    cutoff_date = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    kept = []
    for v in name_map.values():
        if v.get("source_ts", "9999") < cutoff_date:
            continue
        if "/" in v.get("name", "") and v.get("source_label") != "TapTap 预约榜":
            continue
        kept.append(v)

    result = {"updated_at": datetime.datetime.utcnow().isoformat() + "Z", "items": kept}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"应用商店抓取完成。新增 {len(new_items)} 条，库中共 {len(kept)} 条。")

if __name__ == "__main__":
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {"items": []}
    new_data = scrape_app_stores()
    merge_and_save(existing, new_data)
