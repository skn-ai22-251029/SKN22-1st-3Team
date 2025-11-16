# src/dashboard/pages/05_시장 포지션.py

from datetime import date as DateType
from typing import List

import pandas as pd
import plotly.express as px
import streamlit as st

import queries
from utils.ui import load_global_css


def _format_month(d: DateType) -> str:
    return d.strftime("%Y-%m")


def render():
    load_global_css()

    # --------------------------------------------------
    # 1) 타이틀
    # --------------------------------------------------
    st.markdown(
        '<div class="page-title">📍 시장 포지션 맵</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="page-subtitle">'
        "선택한 기준 월에 대해 각 모델의 관심도와 보급률을 한눈에 비교합니다."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # --------------------------------------------------
    # 2) 사용 가능한 월 목록 조회
    # --------------------------------------------------
    months: List[DateType] = queries.get_position_months()
    if not months:
        st.warning("포지션 분석에 사용할 수 있는 월간 데이터가 없습니다.")
        return

    month_labels = [_format_month(m) for m in months]
    default_index = len(months) - 1  # 가장 최신 월을 기본값으로

    col_m, col_b, col_f = st.columns([2, 2, 2])

    with col_m:
        selected_label = st.selectbox(
            "기준 월 선택",
            options=month_labels,
            index=default_index,
        )
        selected_month = months[month_labels.index(selected_label)]

    # --------------------------------------------------
    # 3) 데이터 로딩 (해당 월 기준)
    # --------------------------------------------------
    df = queries.get_model_position_map(selected_month)

    if df.empty:
        st.info("선택한 월에 대한 관심도/보급률 데이터가 없습니다.")
        return

    # 보급률 퍼센트로 변환
    df["adoption_rate"] = pd.to_numeric(df["adoption_rate"], errors="coerce").fillna(
        0.0
    )
    df["adoption_rate_pct"] = (df["adoption_rate"] * 100.0).round(3)

    df["sales_units"] = pd.to_numeric(df["sales_units"], errors="coerce").fillna(0)
    df["interest_score"] = pd.to_numeric(df["interest_score"], errors="coerce").fillna(
        0.0
    )

    # 표시용 레이블
    df["label"] = df["brand_name"] + " " + df["model_name_kr"]

    # --------------------------------------------------
    # 4) 브랜드 / 필터 설정
    # --------------------------------------------------
    with col_b:
        brand_options = ["전체"] + sorted(df["brand_name"].unique().tolist())
        selected_brand = st.selectbox("브랜드 필터", options=brand_options)

    # 최소 판매량 / 최소 관심도 필터
    with col_f:
        min_sales = int(df["sales_units"].max() * 0.05)  # 기본값: 상위 5% 정도 기준
        min_interest = float(
            df["interest_score"].max() * 0.1
        )  # 기본값: 상위 10% 정도 기준

        sales_threshold = st.number_input(
            "최소 월 판매량 필터",
            min_value=0,
            max_value=int(df["sales_units"].max()),
            value=min_sales,
            step=10,
        )
        interest_threshold = st.number_input(
            "최소 관심도 점수 필터",
            min_value=0.0,
            max_value=float(df["interest_score"].max()),
            value=round(min_interest, 1),
            step=1.0,
        )

    # 브랜드 필터 적용
    filtered = df.copy()
    if selected_brand != "전체":
        filtered = filtered[filtered["brand_name"] == selected_brand]

    # 수치 필터 적용
    filtered = filtered[
        (filtered["sales_units"] >= sales_threshold)
        & (filtered["interest_score"] >= interest_threshold)
    ]

    if filtered.empty:
        st.info("필터 조건에 해당하는 모델이 없습니다. 필터 값을 낮춰 보세요.")
        return

    # --------------------------------------------------
    # 5) 포지션 맵 (관심도 × 보급률 버블 차트)
    # --------------------------------------------------
    st.markdown("#### 관심도 × 보급률 포지션 맵")

    fig = px.scatter(
        filtered,
        x="interest_score",
        y="adoption_rate_pct",
        size="sales_units",
        color="brand_name",
        hover_name="label",
        hover_data={
            "brand_name": True,
            "model_name_kr": True,
            "sales_units": True,
            "adoption_rate_pct": True,
            "interest_score": True,
            "model_id": False,
        },
        labels={
            "interest_score": "관심도 점수",
            "adoption_rate_pct": "보급률(%)",
            "sales_units": "판매량(대)",
            "brand_name": "브랜드",
        },
    )

    fig.update_layout(
        xaxis=dict(title="관심도 점수", zeroline=False),
        yaxis=dict(title="보급률(%)", zeroline=False),
        margin=dict(l=40, r=40, t=10, b=60),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    st.plotly_chart(fig, width="stretch")

    # --------------------------------------------------
    # 6) 하단 요약 테이블
    # --------------------------------------------------
    st.markdown("#### 모델별 요약 표")

    display_cols = [
        "brand_name",
        "model_name_kr",
        "sales_units",
        "adoption_rate_pct",
        "interest_score",
    ]

    display_df = (
        filtered[display_cols]
        .sort_values(["brand_name", "sales_units"], ascending=[True, False])
        .rename(
            columns={
                "brand_name": "브랜드",
                "model_name_kr": "모델명",
                "sales_units": "판매량(대)",
                "adoption_rate_pct": "보급률(%)",
                "interest_score": "관심도 점수",
            }
        )
    )

    st.dataframe(display_df, width="stretch")


if __name__ == "__main__":
    render()
