import requests
import json
import re
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET
from html import unescape
from pathlib import Path

KST = timezone(timedelta(hours=9))
RSS_URL = "https://seoulboard.seoul.go.kr/rss/RSSGenerator?bbsNo=158"
LIST_URL = "https://www.seoul.go.kr/news/news_report.do?bbsNo=158&curPage={page}&cntPerPage=10"
OUT_PATH = Path(__file__).parent.parent / "data" / "news.json"
# 초기 수집 시 가져올 최대 페이지 수 (10건/페이지 * 150 = 1500건 약 6개월치)
HISTORY_PAGES = 150

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

def normalize(s):
    return re.sub(r'[\s\W]', '', unescape(s)).strip()

def fetch_html_page(page, headers):
    """HTML 목록 한 페이지 파싱 -> [{title, link, dept, date}]"""
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
        # 제목
        title_match = re.search(r'>([^<]{4,})</a>', tds[1])
        if not title_match:
            continue
        raw_title = title_match.group(1).strip()
        # onclick에서 글번호
        seq_match = re.search(r'fnTbbsView.*?(\d{6,})', tds[1])
        if not seq_match:
            continue
        seq = seq_match.group(1)
        link = f'https://www.seoul.go.kr/news/news_report.do#view/{seq}'
        dept = re.sub(r'<[^>]+>', '', tds[2]).strip()
        dept = unescape(dept)
        date_raw = re.sub(r'<[^>]+>', '', tds[3]).strip()
        # 날짜 정규화 YYYY-MM-DD
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

def fetch_dept_map_rss(headers):
    """RSS 제목 기반 부서 매핑 (최신 5페이지)"""
    dept_map = {}
    try:
        for page in range(1, 6):
            for it in fetch_html_page(page, headers):
                dept_map[normalize(it['title'])] = it['dept']
    except Exception as e:
        print(f'dept_map error: {e}')
    return dept_map

def fetch_news():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SeoulNewsBot/1.0)"}
    
    # 기존 데이터 로드
    existing = []
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
            existing = data.get('items', [])
    existing_links = {i['link'] for i in existing}
    
    # 초기 실행 여부 판단 (기존 500건 미만이면 과거 데이터 대량 수집)
    is_initial = len(existing) < 500
    
    if is_initial:
        print(f'초기 수집 모드: 최대 {HISTORY_PAGES}페이지 수집 시작...')
        new_items = []
        for page in range(1, HISTORY_PAGES + 1):
            try:
                items = fetch_html_page(page, headers)
                if not items:
                    print(f'  페이지 {page}: 데이터 없음, 중단')
                    break
                added = [i for i in items if i['link'] not in existing_links]
                new_items.extend(added)
                existing_links.update(i['link'] for i in added)
                if page % 10 == 0:
                    print(f'  {page}페이지 완료, 누적 {len(new_items)}건')
            except Exception as e:
                print(f'  페이지 {page} 오류: {e}')
                break
        print(f'초기 수집 완료: {len(new_items)}건')
        merged = new_items + existing
    else:
        # 일반 모드: RSS + 최신 HTML 페이지
        print('일반 수집 모드')
        resp = requests.get(RSS_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        root = ET.fromstring(resp.text)
        dept_map = fetch_dept_map_rss(headers)
        new_items = []
        for item in root.findall(".//item"):
            title_raw = unescape(item.findtext("title", "").strip())
            link = (item.findtext("link") or "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            clean = clean_title(title_raw)
            dept = dept_map.get(normalize(clean), '')
            if not dept:
                dept = dept_map.get(normalize(title_raw), '')
            if link not in existing_links:
                new_items.append({
                    "title": clean,
                    "link": link,
                    "dept": dept,
                    "category": categorize(title_raw),
                    "date": parse_date(pub_date),
                })
        print(f'신규 {len(new_items)}건')
        merged = new_items + existing
    
    merged.sort(key=lambda x: x['date'], reverse=True)
    merged = merged[:5000]  # 최대 5000건 보관
    
    now_kst = datetime.now(KST).strftime('%Y-%m-%d %H:%M')
    result = {
        "updated_at": now_kst,
        "total": len(merged),
        "new_today": len(new_items) if not is_initial else 0,
        "items": merged,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'완료: 전체 {len(merged)}건')

if __name__ == "__main__":
    fetch_news()
