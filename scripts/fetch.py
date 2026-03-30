"""
서울시보 목차 자동 수집 스크립트
- 매주 목요일 발행되는 서울시보 목차를 파싱
- 도시계획·건축·토지 관련 항목 분류
- data/sibo.json 저장
"""

import requests
import json
import re
from datetime import datetime, timezone, timedelta
from html import unescape
from pathlib import Path

KST = timezone(timedelta(hours=9))
OUT_PATH = Path(__file__).parent.parent / "data" / "sibo.json"

# 서울시보 목록 페이지
LIST_URL = "https://event.seoul.go.kr/seoulsibo/list.do"
# 서울시보 개별 목차 페이지
VIEW_URL = "https://event.seoul.go.kr/seoulsibo/view.do?id={id}"
# 목차(전체) 검색 Ajax (키워드 없이 호수 전체 목차)
AJAX_URL = "https://event.seoul.go.kr/seoulsibo/listContents.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SeoulSiboBot/1.0)",
    "Referer": "https://event.seoul.go.kr/seoulsibo/list.do",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# ── 25개 자치구 (5권역 지리 순서) ──
GU_REGIONS = [
    ("도심권", ["종로구","중구","용산구"]),
    ("동북권", ["성동구","광진구","동대문구","중랑구","성북구","강북구","도봉구","노원구"]),
    ("서북권", ["은평구","서대문구","마포구"]),
    ("서남권", ["양천구","강서구","구로구","금천구","영등포구","동작구","관악구"]),
    ("동남권", ["서초구","강남구","송파구","강동구"]),
]
ALL_GU = [g for _, gs in GU_REGIONS for g in gs]

# ── 잡공고 키워드 ──
ADMIN_KW = [
    "공시송달","과태료","압류","체납","공매","이행강제금","영업정지",
    "과징금","대집행","청문","행정처분","사용료 부과","직권말소",
    "경고처분","불법","단속","고발"
]

# ── 주제 분류 규칙 (우선순위 순) ──
TOPIC_RULES = [
    ("renewal", [
        "정비구역","정비계획","재개발","재건축","주택재개발","주택재건축",
        "뉴타운","모아타운","모아주택","소규모재건축","소규모재개발",
        "자율주택정비","도시환경정비","재정비촉진","관리처분","사업시행인가",
        "추진위원회","조합설립인가","가로주택정비"
    ]),
    ("law", [
        "입법예고","조례 제정","조례 개정","조례 폐지",
        "규칙 제정","규칙 개정","규칙 폐지","훈령","예규"
    ]),
    ("urban", [
        "도시관리계획","도시기본계획","지구단위계획","용도지역","용도지구",
        "용도구역","개발제한구역","도시개발","입지규제최소구역",
        "특별계획구역","경관계획","도시재생","광역도시계획","개발행위"
    ]),
    ("housing", [
        "공공주택","공동주택","분양권","임대주택","주거환경",
        "주택공급","분양가","주택조합","지역주택조합","민간임대"
    ]),
    ("infra", [
        "공원","도로","하천","광장","주차장","녹지","도시계획시설",
        "학교","의료시설","문화시설","수도","상수도","하수도","철도"
    ]),
]

TOPIC_LABEL = {
    "renewal": "정비사업", "urban": "도시계획", "housing": "주택",
    "infra": "기반시설", "law": "법규", "misc": "기타"
}

# ── 임팩트 분류 ──
def detect_impact(title):
    if re.search(r"해제|실효|일몰|폐지 결정", title):
        return "release"
    if re.search(r"경미한|경미 사항|지형도면|기간 연장|기간연장|연장 결정", title):
        return "minor"
    # 변경·경미·해제 없고 신규 키워드
    if not re.search(r"변경|경미|해제|실효", title):
        if re.search(r"최초 지정|신규 지정|신설 결정|신규 승인|모아타운 선정|신규 선정", title):
            return "new"
        # 지정/결정 키워드 있고 변경 없으면 신규
        if re.search(r"(구역|계획|지구|지역)\s*(지정|결정)\s*(고시)?", title):
            return "new"
    if re.search(r"변경", title) and not re.search(r"경미", title):
        return "major"
    return "neutral"

IMPACT_LABEL = {
    "new": "신규 지정", "major": "주요 변경",
    "minor": "경미한 변경", "release": "해제·실효", "neutral": ""
}

# ── 확정여부 ──
def detect_status(title):
    if re.search(r"결정고시|결정·고시|지정고시|지정·고시|관리처분 인가|사업시행인가|확정", title):
        return "confirmed"
    if re.search(r"열람공고|주민공람|입법예고|\(안\)|계획안", title):
        return "planned"
    return "confirmed"

STATUS_LABEL = {"confirmed": "확정", "planned": "예정"}

def detect_topic(title):
    for topic, kws in TOPIC_RULES:
        if any(kw in title for kw in kws):
            return topic
    return "misc"

def extract_gu(title):
    return [g for g in ALL_GU if g in title]

def is_admin(title):
    return any(kw in title for kw in ADMIN_KW)

def is_relevant(title):
    """도시계획 관련 여부 판단"""
    RELEVANT_KW = [
        "도시","계획","정비","주택","건축","토지","공원","도로","조례","규칙",
        "구역","지구","지역","용도","개발","기반시설","수도","하천"
    ]
    return any(kw in title for kw in RELEVANT_KW)

def make_summary(title, topic, impact, status, gu):
    loc = "·".join(gu) if gu else "해당 지역"
    desc = {
        "renewal": "정비사업(재개발·재건축)",
        "urban": "도시관리계획",
        "housing": "주택 관련 계획",
        "infra": "기반시설 계획",
        "law": "조례·규칙",
        "misc": "관련 사항"
    }.get(topic, "관련 사항")

    if impact == "new":
        return f"{loc}에 {desc}이 신규로 지정·결정되었습니다."
    if impact == "major":
        return f"{loc}의 {desc}이 변경 결정되었습니다."
    if impact == "minor":
        return f"{loc}의 {desc} 경미한 사항이 변경되었습니다."
    if impact == "release":
        return f"{loc}의 {desc}이 해제·실효 처리되었습니다."
    if status == "planned":
        return f"{loc}의 {desc} (안)이 공람 중입니다."
    return f"{loc} {desc} 관련 사항이 고시되었습니다."

def classify_item(title):
    """제목 하나를 분류해서 dict 반환, 관련 없으면 None"""
    title = title.strip()
    if len(title) < 6 or len(title) > 260:
        return None

    admin = is_admin(title)
    if not admin and not is_relevant(title):
        return None

    topic = detect_topic(title)
    status = "admin" if admin else detect_status(title)
    impact = "neutral" if admin else detect_impact(title)
    gu = extract_gu(title)

    return {
        "title": title,
        "topic": topic,
        "status": status,
        "impact": impact,
        "isAdmin": admin,
        "gu": gu,
        "summary": "" if admin else make_summary(title, topic, impact, status, gu),
        "topicLabel": TOPIC_LABEL.get(topic, topic),
        "impactLabel": IMPACT_LABEL.get(impact, ""),
        "statusLabel": STATUS_LABEL.get(status, ""),
    }

# ── 서울시보 목록 파싱 ──
def fetch_sibo_list(session):
    """최신 서울시보 목록 파싱 → [{no, date, id}]"""
    resp = session.get(LIST_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    html = resp.text

    editions = []
    # goView('26630') 패턴으로 id 추출
    rows = re.findall(
        r"goView\('(\d+)'\)[^<]*</a>\s*</td>\s*<td[^>]*>\s*([\d.]+)",
        html
    )
    # 호수 추출
    nos = re.findall(r"제(\d+)호", html)

    for i, (eid, date) in enumerate(rows):
        no = nos[i] if i < len(nos) else ""
        editions.append({"no": no, "date": date.strip(), "id": eid})

    return editions

# ── 개별 시보 목차 파싱 ──
def fetch_sibo_contents(session, edition_id):
    """시보 목차 페이지에서 제목 목록 파싱"""
    url = VIEW_URL.format(id=edition_id)
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        html = resp.text
    except Exception as e:
        print(f"  목차 페이지 오류 (id={edition_id}): {e}")
        return []

    titles = []
    # 테이블 행에서 텍스트 추출
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    for row in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        for td in tds:
            text = re.sub(r"<[^>]+>", "", td).strip()
            text = unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            if 8 < len(text) < 250 and not re.match(r"^\d+$", text):
                titles.append(text)

    # 링크 텍스트도 추출 (목차 항목이 <a> 안에 있는 경우)
    links = re.findall(r'<a[^>]*>([^<]{8,200})</a>', html)
    for t in links:
        t = unescape(t).strip()
        if t and t not in titles:
            titles.append(t)

    # 중복 제거
    seen = set()
    result = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result

# ── 메인 ──
def fetch_sibo():
    session = requests.Session()

    # 기존 데이터 로드
    existing_editions = {}
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            old = json.load(f)
            for ed in old.get("editions", []):
                existing_editions[ed["id"]] = ed

    print("서울시보 목록 조회 중...")
    editions_meta = fetch_sibo_list(session)
    print(f"  목록 {len(editions_meta)}개 확인")

    editions_out = []
    new_count = 0

    for meta in editions_meta:
        eid = meta["id"]

        # 이미 수집한 호수는 기존 데이터 재사용
        if eid in existing_editions:
            editions_out.append(existing_editions[eid])
            print(f"  제{meta['no']}호 ({meta['date']}) — 기존 데이터 재사용")
            continue

        print(f"  제{meta['no']}호 ({meta['date']}) — 새로 수집 중...")
        titles = fetch_sibo_contents(session, eid)
        print(f"    원문 {len(titles)}줄 추출")

        items = []
        seen = set()
        for t in titles:
            if t in seen:
                continue
            seen.add(t)
            item = classify_item(t)
            if item:
                items.append(item)

        main_items = [i for i in items if not i["isAdmin"]]
        admin_items = [i for i in items if i["isAdmin"]]
        print(f"    분류: 주요 {len(main_items)}건 + 잡공고 {admin_items.__len__()}건")

        editions_out.append({
            "id": eid,
            "no": meta["no"],
            "date": meta["date"],
            "items": items,
            "mainCount": len(main_items),
            "adminCount": len(admin_items),
        })
        new_count += 1

    # 최신순 정렬
    editions_out.sort(key=lambda x: x["date"].replace(".", "-"), reverse=True)
    # 최대 52개 (1년치) 보관
    editions_out = editions_out[:52]

    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    result = {
        "updated_at": now_kst,
        "total_editions": len(editions_out),
        "new_today": new_count,
        "editions": editions_out,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n완료: 전체 {len(editions_out)}호, 신규 {new_count}호 수집")

if __name__ == "__main__":
    fetch_sibo()
