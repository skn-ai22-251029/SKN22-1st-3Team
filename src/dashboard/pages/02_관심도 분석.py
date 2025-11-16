# src/dashboard/pages/02_Interest.py

from datetime import date as DateType
from typing import Optional, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.layout import two_columns_ratio
from components.charts import build_interest_chart
from utils.ui import load_global_css

import queries


def _format_month(d: DateType) -> str:
    return d.strftime("%Y-%m")


def render():
    load_global_css()

    # --------------------------------------------------
    # 1) 페이지 타이틀
    # --------------------------------------------------
    st.markdown(
        '<div class="page-title">📈 관심도 분석</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="page-subtitle">네이버/구글 검색 지수를 기반으로 모델별 관심도를 비교하고, '
        "디바이스·성별 상세 지표까지 확인할 수 있습니다.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # --------------------------------------------------
    # 2) 기준 월 / 제조사 / TOP N 필터
    # --------------------------------------------------
    latest_month = queries.get_latest_month_for_overview()
    if latest_month is None:
        st.warning("아직 관심도/판매 데이터가 없습니다.")
        return

    latest_month = latest_month.replace(day=1)

    brand_list: List[str] = queries.get_brand_list()
    col_filter1, col_filter2, col_filter3 = st.columns([2, 2, 1])

    with col_filter1:
        # 연도/월 선택 → 내부적으로는 항상 YYYY-MM-01
        years = list(range(2023, latest_month.year + 1))
        months = list(range(1, 13))

        col_y, col_m = st.columns(2)
        with col_y:
            selected_year = st.selectbox(
                "연도",
                options=years,
                index=years.index(latest_month.year),
            )
        with col_m:
            selected_month = st.selectbox(
                "월",
                options=months,
                index=latest_month.month - 1,
            )

        month = DateType(selected_year, selected_month, 1)

    with col_filter2:
        brand_name = st.selectbox(
            "제조사 선택",
            options=["전체"] + brand_list,
            index=0,
        )
        brand_param: Optional[str] = None if brand_name == "전체" else brand_name

    with col_filter3:
        top_n = st.number_input("TOP N", min_value=5, max_value=30, value=10, step=1)

    # --------------------------------------------------
    # 3) 관심도 Top N 차트
    #    - queries.get_overview_top_models 재사용 후 interest_score 기준 정렬
    # --------------------------------------------------
    df = queries.get_overview_top_models(
        month=month,
        brand_name=brand_param,
        top_n=top_n
        * 3,  # 여유 있게 불러와서 아래에서 interest_score 순으로 TOP N만 사용
    )

    if df.empty:
        st.info("선택한 조건에 해당하는 관심도 데이터가 없습니다.")
        return

    if "interest_score" not in df.columns:
        st.error(
            "쿼리 결과에 interest_score 컬럼이 없습니다. 로더/쿼리를 확인해주세요."
        )
        return

    df_sorted = df.sort_values("interest_score", ascending=False).head(top_n)

    # KPI 영역 (간단 요약)
    total_models = len(df_sorted)
    avg_naver = (
        pd.to_numeric(df_sorted["naver_search_index"], errors="coerce").dropna().mean()
    )
    avg_google = (
        pd.to_numeric(df_sorted["google_trend_index"], errors="coerce").dropna().mean()
    )

    kpi_cols = st.columns(4)
    with kpi_cols[0]:
        st.metric("대상 모델 수", f"{total_models} 개")
    with kpi_cols[1]:
        st.metric(
            "평균 네이버 지수",
            f"{avg_naver:.1f}" if pd.notna(avg_naver) else "데이터 없음",
        )
    with kpi_cols[2]:
        st.metric(
            "평균 구글 트렌드",
            f"{avg_google:.1f}" if pd.notna(avg_google) else "데이터 없음",
        )
    with kpi_cols[3]:
        st.metric("기준 월", _format_month(month))

    st.markdown("")

    # 메인 관심도 차트
    st.markdown(
        '<div class="section-title">관심도 Top N 모델</div>',
        unsafe_allow_html=True,
    )
    # -----------------------------
    # 막대(bar) → 선(line) 그래프로 변경
    # -----------------------------
    df_line = df_sorted.copy()

    # 라벨 조합
    df_line["label"] = df_line["brand_name"] + " " + df_line["model_name_kr"]

    # 관심도 점수(0~1 → 0~100)
    df_line["interest_score"] = (
        pd.to_numeric(df_line["interest_score"], errors="coerce").fillna(0.0) * 100.0
    )

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df_line["label"],
            y=df_line["interest_score"],
            mode="lines+markers",
            name="관심도 점수(0~100)",
            line=dict(width=3),
            marker=dict(size=9),
            text=df_line["interest_score"].round(1),
            textposition="top center",
        )
    )

    # y 축 범위 여유 확보
    y_max = max(100, float(df_line["interest_score"].max()) * 1.2)

    fig.update_layout(
        xaxis=dict(title="모델"),
        yaxis=dict(title="관심도 점수(0~100)", range=[0, y_max]),
        margin=dict(l=40, r=40, t=10, b=80),
    )

    st.plotly_chart(fig, width="stretch")
    st.markdown(
        '<div class="note-text">'
        "관심도 점수는 네이버/구글 지수를 0~100으로 정규화한 후, "
        "0.7 × 네이버 + 0.3 × 구글(구글 지수가 없으면 네이버만 사용)으로 계산합니다."
        "</div>",
        unsafe_allow_html=True,
    )

    # --------------------------------------------------
    # 4) 모델별 관심도 요약 테이블
    # --------------------------------------------------
    st.markdown("---")
    st.markdown(
        '<div class="section-title">모델별 관심도 요약</div>',
        unsafe_allow_html=True,
    )

    summary_df = df_sorted[
        [
            "brand_name",
            "model_name_kr",
            "naver_search_index",
            "google_trend_index",
            "interest_score",
        ]
    ].copy()

    summary_df["interest_score"] = (summary_df["interest_score"] * 100).round(1)
    summary_df.rename(
        columns={
            "brand_name": "브랜드",
            "model_name_kr": "모델명",
            "naver_search_index": "네이버 지수",
            "google_trend_index": "구글 트렌드",
            "interest_score": "관심도 점수(0~100)",
        },
        inplace=True,
    )

    st.dataframe(summary_df, height=400)

    # --------------------------------------------------
    # 5) 네이버 디테일 지표 (device / gender)
    # --------------------------------------------------
    st.markdown("---")
    st.markdown(
        '<div class="section-title">네이버 상세 지표 (디바이스·성별)</div>',
        unsafe_allow_html=True,
    )

    detail_df = queries.load_interest_detail(month, brand_param)

    if detail_df.empty:
        st.info(
            "해당 월에 대해 저장된 네이버 디테일 데이터가 없습니다. "
            "model_monthly_interest_detail 로더를 확인해주세요."
        )
        return

    # RAW 표 먼저 보여주기
    with st.expander("RAW 데이터 보기 (model_monthly_interest_detail)", expanded=False):
        st.dataframe(detail_df, height=400)

    # 모델 × (device, gender) 피벗 집계
    pivot_df = detail_df.pivot_table(
        index=["brand_name", "model_name_kr"],
        columns=["device", "gender"],
        values="ratio",
        aggfunc="sum",
        fill_value=0.0,
    )

    # 컬럼 이름 정리: ('pc','male') → 'pc_male'
    pivot_df.columns = [
        f"{dev or 'all'}_{gender or 'all'}" for (dev, gender) in pivot_df.columns
    ]
    pivot_df = pivot_df.reset_index()

    st.markdown(
        '<div class="section-subtitle">모델별 네이버 검색 비중 (디바이스×성별 합산)</div>',
        unsafe_allow_html=True,
    )
    st.dataframe(pivot_df, height=500)


if __name__ == "__main__":
    render()
