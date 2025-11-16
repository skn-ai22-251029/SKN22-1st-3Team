# src/dashboard/pages/03_보급률 분석.py

from datetime import date as DateType
from typing import Optional, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

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
        '<div class="page-title">🚗 보급률 분석</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="page-subtitle">'
        "다나와 판매 데이터를 기반으로, 월별 모델 보급률(점유율)을 비교합니다."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # --------------------------------------------------
    # 2) 기준 월 / 제조사 / TOP N 필터
    # --------------------------------------------------
    latest_month = queries.get_latest_month_for_overview()
    if latest_month is None:
        st.warning("아직 판매/보급률 데이터가 없습니다.")
        return

    latest_month = latest_month.replace(day=1)

    brand_list: List[str] = queries.get_brand_list()
    col_filter1, col_filter2, col_filter3 = st.columns([2, 2, 1])

    with col_filter1:
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
    # 3) 보급률 Top N 차트
    # --------------------------------------------------
    df = queries.get_monthly_sales_top_models(
        month=month,
        brand_name=brand_param,
        top_n=top_n,
    )

    if df.empty:
        st.info("선택한 조건에 해당하는 보급률 데이터가 없습니다.")
        return

    # 보급률(%) 계산: adoption_rate 있으면 그대로 사용, 없으면 sales_units / market_total_units
    df_chart = df.copy()

    df_chart["adoption_rate"] = pd.to_numeric(
        df_chart["adoption_rate"], errors="coerce"
    )

    # 보조 계산: adoption_rate가 없고 total이 있으면 계산
    mask_need_calc = (
        df_chart["adoption_rate"].isna() & df_chart["market_total_units"].notna()
    )
    df_chart.loc[mask_need_calc, "adoption_rate"] = (
        df_chart.loc[mask_need_calc, "sales_units"]
        / df_chart.loc[mask_need_calc, "market_total_units"]
    )

    df_chart["adoption_rate_pct"] = df_chart["adoption_rate"].fillna(0.0) * 100.0

    df_chart["label"] = df_chart["brand_name"] + " " + df_chart["model_name_kr"]

    # KPI
    total_models = len(df_chart)
    total_units = int(df_chart["sales_units"].sum())
    avg_adoption = float(df_chart["adoption_rate_pct"].mean())

    kpi_cols = st.columns(4)
    with kpi_cols[0]:
        st.metric("대상 모델 수", f"{total_models} 개")
    with kpi_cols[1]:
        st.metric("총 판매대수(Top N 합)", f"{total_units:,} 대")
    with kpi_cols[2]:
        st.metric(
            "평균 보급률(Top N)",
            f"{avg_adoption:.2f} %",
        )
    with kpi_cols[3]:
        st.metric("기준 월", _format_month(month))

    st.markdown("")
    st.markdown(
        '<div class="section-title">보급률 Top N 모델</div>',
        unsafe_allow_html=True,
    )

    # 차트: 보급률(%) bar + 라벨
    fig = go.Figure()

    fig.add_bar(
        x=df_chart["label"],
        y=df_chart["adoption_rate_pct"],
        name="보급률(점유율, %)",
        text=df_chart["adoption_rate_pct"].round(2),
        textposition="outside",
    )

    y_max = max(10.0, float(df_chart["adoption_rate_pct"].max()) * 1.2)

    fig.update_layout(
        xaxis=dict(title="모델"),
        yaxis=dict(title="보급률(점유율, %)", range=[0, y_max]),
        margin=dict(l=40, r=40, t=10, b=80),
    )

    st.plotly_chart(fig, width="stretch")

    st.markdown(
        '<div class="note-text">'
        "보급률은 (해당 모델 월 판매량 / 전체 시장 판매량) × 100 으로 계산되며, "
        "market_total_units가 없는 경우 저장된 adoption_rate 값만 사용합니다."
        "</div>",
        unsafe_allow_html=True,
    )

    # --------------------------------------------------
    # 4) 모델별 보급률 요약 테이블
    # --------------------------------------------------
    st.markdown("---")
    st.markdown(
        '<div class="section-title">모델별 보급률 요약 (Top N)</div>',
        unsafe_allow_html=True,
    )

    summary_df = df_chart[
        [
            "brand_name",
            "model_name_kr",
            "sales_units",
            "adoption_rate_pct",
            "market_total_units",
        ]
    ].copy()

    summary_df.rename(
        columns={
            "brand_name": "브랜드",
            "model_name_kr": "모델명",
            "sales_units": "판매량(대)",
            "adoption_rate_pct": "보급률(%)",
            "market_total_units": "전체 시장 판매량(대)",
        },
        inplace=True,
    )

    st.dataframe(summary_df, height=400)

    # --------------------------------------------------
    # 5) 다나와 RAW 데이터 테이블
    # --------------------------------------------------
    st.markdown("---")
    st.markdown(
        '<div class="section-title">다나와 월간 판매 RAW 데이터</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-subtitle">'
        "선택한 월·제조사에 대해 수집된 모든 모델의 판매/보급률 데이터를 그대로 보여줍니다."
        "</div>",
        unsafe_allow_html=True,
    )

    raw_df = queries.get_monthly_sales_raw(month, brand_param)

    if raw_df.empty:
        st.info("해당 조건에 대한 RAW 판매 데이터가 없습니다.")
        return

    raw_df["adoption_rate_pct"] = (
        pd.to_numeric(raw_df["adoption_rate"], errors="coerce").fillna(0.0) * 100.0
    )

    display_df = raw_df[
        [
            "brand_name",
            "model_name_kr",
            "sales_units",
            "adoption_rate_pct",
            "market_total_units",
            "source",
        ]
    ].copy()

    display_df.rename(
        columns={
            "brand_name": "브랜드",
            "model_name_kr": "모델명",
            "sales_units": "판매량(대)",
            "adoption_rate_pct": "보급률(%)",
            "market_total_units": "전체 시장 판매량(대)",
            "source": "출처",
        },
        inplace=True,
    )

    st.dataframe(display_df, height=500)


if __name__ == "__main__":
    render()
