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
CUTOFF_DAYS = 90

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

# 扩充后的国内出海厂商词库（含 AI 新锐）
CN_DEV_KEYWORDS = [
    "科技", "网络", "信息", "软件", "互动", "游戏", "数码", "无线", "移动", "娱乐", "文化", "传媒",
    "北京", "上海", "深圳", "广州", "杭州", "成都", "厦门", "福州", "苏州", "武汉", "珠海",
    ".cn", "china", "chinese", "zh_", "cn_",
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

# ========== 增强版 +86 手机号提取（深度访问官网） ==========
PHONE_PATTERN = re.compile(r'(?:\+?86[\s\-]?)?(1[3-9]\d{9})')

def extract_phone_from_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 优先在“联系我们”或“应用支持”相关的文本块中查找
        text = soup.get_text(separator=' ')
        matches = PHONE_PATTERN.findall(text)
        if matches:
            # 过滤掉明显不是手机号的字符串（如纯数字 ID）
            for m in matches:
                if len(m) == 11 and m.startswith("1"):
                    return f"+86 {m}"
        
        # 回退：直接在 HTML 源码中匹配
        matches = PHONE_PATTERN.findall(r.text)
        for m in matches:
            if len(m) == 11 and m.startswith("1"):
                return f"+86 {m}"
        return ""
    except Exception:
        return ""

# ========== 严格的首发时间判定 ==========
def is_appstore_first_release(release_str: str, current_version_str: str) -> bool:
    """App Store：严格使用 releaseDate（首发），并校验非老应用更新"""
    if not release_str: return False
    try:
        release_dt = datetime.datetime.fromisoformat(release_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # 未来日期（预约产品）直接通过
        if release_dt > now:
            return True
        
        # 过去 60 天内首发
        if (now - release_dt).days <= 60:
            # 额外校验：如果 currentVersionReleaseDate 存在且远晚于 releaseDate，说明是老应用更新
            if current_version_str:
                cv_dt = datetime.datetime.fromisoformat(current_version_str.replace("Z", "+00:00"))
                if (cv_dt - release_dt).days > 30:  # 版本发布比首发晚 30 天以上，判定为老应用
                    return False
            return True
        return False
    except Exception:
        return False

def is_gplay_first_release(released_str: str, updated_ts: int, installs_str: str) -> bool:
    """Google Play：优先使用 released，回退到 updated 但要求低安装量"""
    try:
        if released_str:
            # 尝试解析 "Oct 18, 2010" 或 ISO 格式
            for fmt in ("%b %d, %Y", "%Y-%m-%d"):
                try:
                    release_dt = datetime.datetime.strptime(released_str, fmt).replace(tzinfo=datetime.timezone.utc)
                    if (datetime.datetime.now(datetime.timezone.utc) - release_dt).days <= CUTOFF_DAYS:
                        return True
                    else:
                        return False
                except ValueError:
                    continue
    except Exception:
        pass
    
    # 回退逻辑：如果 released 解析失败，用 updated 但要求安装量较低（新应用特征）
    if updated_ts:
        updated_dt = datetime.datetime.fromtimestamp(updated_ts / 1000, tz=datetime.timezone.utc)
        if (datetime.datetime.now(datetime.timezone.utc) - updated_dt).days <= 60:
            # 简单判断安装量：包含 "10,000+" 以下视为新应用
            if installs_str and ("0+" in installs_str or "1,000+" in installs_str or "5,000+" in installs_str or "10,000+" in installs_str):
                return True
    return False

# ========== App Store 抓取（严格首发时间） ==========
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
                    
                    # 严格首发时间判定
                    if not is_appstore_first_release(release_date, current_version_date): continue

                    dev_name = info.get("artistName", "")
                    dev_url = info.get("sellerUrl", "") or info.get("artistViewUrl", "")
                    
                    # App Store 只校验国内主体，不强制手机号
                    if not is_cn_developer(dev_name, dev_url): continue

                    items.append({
                        "name": info.get("trackName", ""),
                        "platform": "app_store",
                        "category": cat_key,
                        "domestic": dev_name,
                        "overseas": f"{country_name} App Store",
                        "expected": "预约中" if datetime.datetime.fromisoformat(release_date.replace("Z", "+00:00")) > datetime.datetime.now(datetime.timezone.utc) else "已上线",
                        "expected_raw": release_date[:10],
                        "source_ts": datetime.date.today().isoformat(),
                        "source_label": f"App Store {country_name}",
                        "source_url": info.get("trackViewUrl", ""),
                        "basis": "P1 App Store 近2月首发/预约",
                        "contact": "—",  # App Store 不强制抓手机号
                        "pinned": False
                    })
            except Exception as e:
                print(f"App Store {country_name}/{cat_key} 失败: {e}")
    return items

# ========== Google Play 抓取（强制 +86 或国内企业） ==========
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
                updated = detail.get("updated", 0)
                installs = detail.get("installs", "")
                
                # 严格首发时间判定
                if not is_gplay_first_release(released, updated, installs): continue
                
                dev_name = detail.get("developer", "")
                dev_url = detail.get("developerWebsite", "") or detail.get("url", "")
                
                # 核心：必须抓到 +86 手机号，或者是国内开发者
                phone = extract_phone_from_url(dev_url)
                is_cn = is_cn_developer(dev_name, dev_url)
                
                if not phone and not is_cn:
                    continue

                items.append({
                    "name": detail.get("title", ""),
                    "platform": "google",
                    "category": cat_key,
                    "domestic": dev_name,
                    "overseas": f"{country_name} Google Play",
                    "expected": "已上线",
                    "expected_raw": released or "近期上架",
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

# ========== 新增：AppAgg RSS 补充美国区数据 ==========
def scrape_appagg_us():
    """通过 AppAgg RSS 抓取美国区新应用，再用 iTunes API 校验"""
    items = []
    # AppAgg 美国区新应用 RSS（可根据需要调整分类）
    rss_url = "https://appagg.com/rss/new/?hl=en&country=us"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(rss_url, headers=headers, timeout=20)
        # 简单解析 RSS 中的 title 和 link
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', r.text)
        links = re.findall(r'<link>(.*?)</link>', r.text)
        for title, link in zip(titles[1:], links[1:]):  # 跳过 channel 的 title
            # 从链接中提取 app_id（AppAgg 链接通常包含 store id）
            app_id_match = re.search(r'id=(\d+)', link)
            if not app_id_match: continue
            app_id = app_id_match.group(1)
            
            # 用 iTunes Lookup API 校验首发时间
            lr = requests.get(f"https://itunes.apple.com/lookup?id={app_id}&country=us", timeout=10)
            result = lr.json().get("results", [])
            if not result: continue
            info = result[0]
            release_date = info.get("releaseDate", "")
            current_version_date = info.get("currentVersionReleaseDate", "")
            if not is_appstore_first_release(release_date, current_version_date): continue
            
            dev_name = info.get("artistName", "")
            if not is_cn_developer(dev_name, info.get("sellerUrl", "")): continue
            
            items.append({
                "name": info.get("trackName", ""),
                "platform": "app_store",
                "category": "game",
                "domestic": dev_name,
                "overseas": "美国 App Store (AppAgg)",
                "expected": "预约中" if datetime.datetime.fromisoformat(release_date.replace("Z", "+00:00")) > datetime.datetime.now(datetime.timezone.utc) else "已上线",
                "expected_raw": release_date[:10],
                "source_ts": datetime.date.today().isoformat(),
                "source_label": "App Store 美国 (聚合)",
                "source_url": info.get("trackViewUrl", ""),
                "basis": "P1 AppAgg 美国区补充",
                "contact": "—",
                "pinned": False
            })
    except Exception as e:
        print(f"AppAgg 美国区补充失败: {e}")
    return items

def scrape_all_stores():
    all_items = []
    for code, name in COUNTRIES.items():
        print(f"正在抓取 {name} ...")
        all_items.extend(scrape_appstore(code, name))
        all_items.extend(scrape_gplay(code, name))
        time.sleep(1)
    print("正在抓取 AppAgg 美国区补充...")
    all_items.extend(scrape_appagg_us())
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
    # 强行清空旧数据，只保留本次抓取
    existing = {"items": []} 
    merge_and_save(existing, scrape_all_stores())
