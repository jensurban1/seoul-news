import requests
import json
import re
from datetime import datetime, timezone, timedelta
from html import unescape
from pathlib import Path

KST = timezone(timedelta(hours=9))
OUT_PATH = Path(__file__).parent.parent / "data" / "sibo.json"
LIST_URL = "https://event.seoul.go.kr/seoulsibo/list.do"
VIEW_URL = "https://event.seoul.go.kr/seoulsibo/view.do?id={id}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SeoulSiboBot/1.0)",
    "Referer": "https://event.seoul.go.kr/seoulsibo/list.do",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

GU_REGIONS = [
    ("도심권", ["종로구","중구","용산구"]),
    ("동북권", ["성동구","광진구","동대문구","중랑구","성북구","강북구","도봉구","노원구"]),
    ("서북권", ["은평구","서대문구","마포구"]),
    ("서남권", ["양천구","강서구","구로구","금천구","영등포구","동작구","관악구"]),
    ("동남권", ["서초구","강남구","송파구","강동구"]),
]
ALL_GU = [g for _, gs in GU_REGIONS for g in gs]

ADMIN_KW = ["공시송달","과태료","압류","체납","공매","이행강제금","영업정지","과징금","대집행","청문","행정처분","사용료 부과","직권말소","경고처분","불법","단속","고발"]

TOPIC_RULES = [
    ("renewal", ["정비구역","정비계획","재개발","재건축","주택재개발","주택재건축","뉴타운","모아타운","모아주택","소규모재건축","소규모재개발","자율주택정비","도시환경정비","재정비촉진","관리처분","사업시행인가","추진위원회","조합설립인가","가로주택정비"]),
    ("law",     ["입법예고","조례 제정","조례 개정","조례 폐지","규칙 제정","규칙 개정","규칙 폐지","훈령","예규"]),
    ("urban",   ["도시관리계획","도시기본계획","지구단위계획","용도지역","용도지구","용도구역","개발제한구역","도시개발","입지규제최소구역","특별계획구역","경관계획","도시재생","광역도시계획","개발행위"]),
    ("housing", ["공공주택","공동주택","분양권","임대주택","주거환경","주택공급","분양가","주택조합","지역주택조합","민간임대"]),
    ("infra",   ["공원","도로","하천","광장","주차장","녹지","도시계획시설","학교","의료시설","문화시설","수도","상수도","하수도","철도"]),
]
TOPIC_LABEL = {"renewal":"정비사업","urban":
