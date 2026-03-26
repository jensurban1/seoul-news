import requests
import json
import re
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET
from pathlib import Path

KST = timezone(timedelta(hours=9))
RSS_URL = "https://seoulboard.seoul.go.kr/rss/RSSGenerator?bbsNo=158"
OUT_PATH = Path(__file__).parent.parent / "data" / "news.json"

CATEGORY_RULES = [
    (r"교통|버스|지하철|도로|주차|철도|환승", "교통"),
    (r"주택|아파트|임대|전세|월세|부동산|청약", "주택"),
    (r"복지|돌봄|노인|어르신|장애|청년|아동|출산|저출생|육아|보육", "복지"),
    (r"문화|예술|공원|축제|행사|전시|박물관|도서관|공연", "문화"),
    (r"환경|공기|미세먼지|녹지|숲|기후|탄소|쓰레기", "환경"),
    (r"안전|소방|재난|방역|범죄|치안", "안전"),
    (r"경제|일자리|창업|취업|소상공인|산업|스타트업", "경제"),
]

def categorize(title):
    for pattern, cat in CATEGORY_RULES:
        if re.search(pattern, title):
            return cat
    return "행정"

def clean_title(title):
    title = re.sub(r"\((석간|조간|자료제공|해명)\)\s*", "", title)
    title = re.sub(r"\[.+?\]$", "", title)
    return title.strip()

def parse_date(pub_date_str):
    if not pub_date_str:
        return ""
    formats = ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_date_str.strip(), fmt)
            return dt.astimezone(KST).strftime("%Y-%m-%d")
        except Exception:
            continue
    return pub_date_str[:10]

def fetch_news():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SeoulNewsBot/1.0)"}
    resp = requests.get(RSS_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    root = ET.fromstring(resp.text)
    items = []
    for item in root.findall(".//item"):
        title_raw = item.findtext("title", "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        dept = item.findtext("author", "").strip()
        items.append({
            "title": clean_title(title_raw),
            "link": link,
            "dept": dept,
            "category": categorize(title_raw),
            "date": parse_date(pub_date),
        })
    existing = []
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get("items", [])
    existing_links = {i["link"] for i in existing}
    new_items = [i for i in items if i["link"] not in existing_links]
    merged = items + [i for i in existing if i["link"] not in {x["link"] for x in items}]
    merged.sort(key=lambda x: x["date"], reverse=True)
    merged = merged[:500]
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    result = {
        "updated_at": now_kst,
        "total": len(merged),
        "new_today": len(new_items),
        "items": merged,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"완료: 전체 {len(merged)}건 (오늘 신규 {len(new_items)}건)")

if __name__ == "__main__":
    fetch_news()
