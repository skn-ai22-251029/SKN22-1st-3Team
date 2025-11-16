import sys
import pathlib
from utils.ui import load_global_css

# 현재 app.py 경로: .../src/dashboard/app.py
BASE_DIR = pathlib.Path(__file__).resolve().parent
SRC_DIR = BASE_DIR.parent  # .../src

# db.connection 불러오기 위해 src를 파이썬 path에 추가
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st
from streamlit_option_menu import option_menu

from components.layout import page_header


def main():
    st.set_page_config(layout="wide")
    # 기본 홈 페이지에서는 CSS만 먼저 로드해둔다.
    load_global_css()
    page_header(
        "📊 국내 자동차 시장 트렌드 분석 프로젝트",
        "SKNetworks Family AI Camp 22기 - '제로백': Zero-base에서 개발자가 되어가는 과정",
    )

    st.markdown("---")

    st.markdown("## 📄 페이지 구성")
    st.markdown(
        """
    **1) Overview**  
    - 최신 월 기준 현대/기아 모델들의 관심도·판매량·보급률 비교  

    **2) 관심도 분석**  
    - 원하는 월 기준 Top-N 관심도 모델 비교  
    - 네이버·구글·디바이스별 검색 지수  

    **3) 보급률 분석**  
    - 월간 시장 점유율 기반 보급률 비교  

    **4) 상세 분석**  
    - 특정 모델의 기간 전체 타임라인 분석  
    - 최신 블로그 Top3, 키워드, 워드클라우드 제공  

    **5) 시장 포지션**
    - 선택한 기준 월에 대해 각 모델의 관심도와 보급률을 비교

    **6) 관리자(Admin)**  
    - ETL 상태 확인 및 관리 기능  
    """
    )

    st.markdown("---")
    st.markdown("## 📘 용어 정리")
    st.info("산출 과정이나 자세한 내용은 docs/word_definition.md를 참고해주세요.")
    st.markdown(
        """
    **관심도 점수**  
    0.7 × 네이버 검색량 비중 + 0.3 × 구글 트렌드 지수 (없으면 네이버 기준)

    **보급률 (Adoption Rate)**  
    월 판매량 ÷ 전체 시장 판매량 × 100

    **블로그 여론 데이터**  
    네이버 블로그 Top3 → 본문 NLP 분석 → 명사 빈도 → 워드클라우드 생성
    """
    )

    st.markdown("---")
    st.markdown("## 🔗 데이터 출처")
    st.markdown(
        """
    - 네이버 데이터랩 API
    - 다나와 자동차  
    - 구글 트렌드  
    - 네이버 블로그 검색 API  
    """
    )

    st.markdown("---")
    st.info("좌측 메뉴를 선택하여 각 분석 페이지로 이동하세요!")


if __name__ == "__main__":
    main()
