import requests
import json
import re
from datetime import datetime, timezone, timedelta
from html import unescape
from pathlib import Path

KST = timezone(timedelta(hours=9))
LIST_URL = "https://www.seoul.go.kr/news/news_report.do?bbsNo=158&curPage={page}&cntPerPage=10"
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
    title = unescape(title)
    title = re.sub(r"\((석간|조간|자료제공|해명)\)\s*", "", title)
    title = re.sub(r"\[.+?\]$", "", title)
    return title.strip()

def fetch_page(page, headers):
    url = LIST_URL.format(page=page)
    resp = requests.get(url, headers=headers, timeout=20)
    resp.encoding = "utf-8"
    html = resp.text
    items = []
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    for row in rows:
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(tds) < 4:
            continue
        title_match = re.search(r'>([^<]{4,})</a>', tds[1])
        if not title_match:
            continue
        raw_title = title_match.group(1).strip()
        seq_match = re.search(r'fnTbbsView.*?(\d{6,})', tds[1])
        if not seq_match:
            continue
        seq = seq_match.group(1)
        link = f'https://www.seoul.go.kr/news/news_report.do#view/{seq}'
        dept = unescape(re.sub(r'<[^>]+>', '', tds[2]).strip())
        date_raw = re.sub(r'<[^>]+>', '', tds[3]).strip()
        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', date_raw)
        date = date_m.group(1) if date_m else ''
        items.append({
            "title": clean_title(raw_title),
            "link": link,
            "dept": dept,
            "category": categorize(raw_title),
            "date": date,
        })
    return items

def fetch_news():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SeoulNewsBot/1.0)"}

    existing = []
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get("items", [])

    existing_links = {i["link"] for i in existing}

    # 항상 최신 10페이지(100건) 긁어서 누락 없이 수집
    new_items = []
    for page in range(1, 11):
        try:
            items = fetch_page(page, headers)
            if not items:
                break
            added = [i for i in items if i["link"] not in existing_links]
            new_items.extend(added)
            existing_links.update(i["link"] for i in added)
        except Exception as e:
            print(f"페이지 {page} 오류: {e}")
            break

    print(f"신규 수집: {len(new_items)}건")

    merged = new_items + existing
    merged.sort(key=lambda x: x["date"], reverse=True)
    merged = merged[:5000]

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
    print(f"완료: 전체 {len(merged)}건")

if __name__ == "__main__":
    fetch_news()
