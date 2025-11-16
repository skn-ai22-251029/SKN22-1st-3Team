# src/dashboard/pages/04_상세 분석.py

from datetime import date as DateType
from typing import List, Optional

import re
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.images import image_card
from components.layout import page_header, section
from utils.ui import load_global_css

import queries


def _format_month(d: DateType) -> str:
    return d.strftime("%Y-%m")


def strip_tags(html: Optional[str]) -> str:
    """HTML 태그 완전 제거 (XSS 방지용)"""
    if not isinstance(html, str):
        return ""
    clean = re.compile("<.*?>")
    return re.sub(clean, "", html).strip()


def render():
    load_global_css()
    page_header(
        "🔍 모델 상세 분석",
        "특정 모델을 선택하고, 기간 전체에 걸친 관심도·판매 추이를 함께 분석합니다.",
    )

    latest_month = queries.get_latest_month_for_overview()
    if latest_month is None:
        st.warning("아직 관심도/판매 데이터가 없습니다.")
        return

    min_year = 2023
    max_year = latest_month.year
    brand_list: List[str] = queries.get_brand_list()

    with section(title="브랜드 · 모델 · 기간 필터"):
        col1, col2 = st.columns([2, 3])

        with col1:
            brand_name = st.selectbox("브랜드 선택", options=brand_list)
            model_df = queries.get_models_by_brand(brand_name)

            if model_df.empty:
                st.info("해당 브랜드의 모델이 없습니다.")
                return

            model_df["label"] = model_df["brand_name"] + " " + model_df["model_name_kr"]
            model_label = st.selectbox("모델 선택", options=model_df["label"].tolist())
            selected_row = model_df[model_df["label"] == model_label].iloc[0]
            model_id = int(selected_row["model_id"])
            model_name_kr = selected_row["model_name_kr"]

        with col2:
            st.markdown(
                "<div class='section-subtitle'>분석 기간 선택</div>",
                unsafe_allow_html=True,
            )
            col_y1, col_m1, col_y2, col_m2 = st.columns(4)
            with col_y1:
                start_year = st.selectbox(
                    "시작 연도",
                    options=list(range(min_year, max_year + 1)),
                    index=0,
                )
            with col_m1:
                start_month = st.selectbox("시작 월", options=list(range(1, 13)), index=0)
            with col_y2:
                end_year = st.selectbox(
                    "종료 연도",
                    options=list(range(min_year, max_year + 1)),
                    index=list(range(min_year, max_year + 1)).index(latest_month.year),
                )
            with col_m2:
                end_month = st.selectbox(
                    "종료 월",
                    options=list(range(1, 13)),
                    index=latest_month.month - 1,
                )

    start_date = DateType(start_year, start_month, 1)
    end_date = DateType(end_year, end_month, 1)

    if start_date > end_date:
        st.error("시작 월이 종료 월보다 뒤일 수 없습니다.")
        return

    ts_df = queries.get_model_timeseries(
        model_id=model_id,
        start_month=start_date,
        end_month=end_date,
    )

    if ts_df.empty:
        st.info("선택한 기간에 대한 데이터가 없습니다.")
        return

    ts_df = ts_df.sort_values("month")
    ts_df["month_str"] = ts_df["month"].astype(str)
    ts_df["naver_search_index"] = pd.to_numeric(
        ts_df["naver_search_index"], errors="coerce"
    ).fillna(0.0)
    ts_df["google_trend_index"] = pd.to_numeric(
        ts_df["google_trend_index"], errors="coerce"
    ).fillna(0.0)

    has_google = ts_df["google_trend_index"] > 0
    ts_df["interest_score"] = ts_df["naver_search_index"].astype(float)
    ts_df.loc[has_google, "interest_score"] = (
        0.7 * ts_df.loc[has_google, "naver_search_index"]
        + 0.3 * ts_df.loc[has_google, "google_trend_index"]
    )

    ts_df["sales_units"] = pd.to_numeric(ts_df["sales_units"], errors="coerce").fillna(
        0
    )
    adoption_rate = pd.to_numeric(ts_df["adoption_rate"], errors="coerce").astype(
        float
    )
    ts_df = ts_df.assign(adoption_rate=adoption_rate)

    total_units = int(ts_df["sales_units"].sum())
    avg_adoption = float((ts_df["adoption_rate"].fillna(0.0) * 100.0).mean())
    avg_interest = float(ts_df["interest_score"].mean())

    with section(title="핵심 KPI"):
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.metric("모델", f"{brand_name} {model_name_kr}")
        with k2:
            st.metric("기간 총 판매량", f"{total_units:,} 대")
        with k3:
            st.metric("평균 보급률", f"{avg_adoption:.2f} %")
        with k4:
            st.metric("평균 관심도 점수", f"{avg_interest:.1f}")

    with section(title="판매량 vs 관심도 타임라인"):
        fig1 = go.Figure()
        fig1.add_bar(
            x=ts_df["month_str"],
            y=ts_df["sales_units"],
            name="판매량(대)",
            yaxis="y1",
        )
        fig1.add_trace(
            go.Scatter(
                x=ts_df["month_str"],
                y=ts_df["interest_score"],
                mode="lines+markers",
                name="관심도 점수",
                yaxis="y2",
            )
        )
        fig1.update_layout(
            xaxis=dict(title="월"),
            yaxis=dict(title="판매량(대)", side="left"),
            yaxis2=dict(
                title="관심도 점수",
                overlaying="y",
                side="right",
            ),
            margin=dict(l=40, r=40, t=10, b=80),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
        )
        st.plotly_chart(fig1, width="stretch")

    with section(title="네이버 vs 구글 검색 지수"):
        fig2 = go.Figure()
        fig2.add_trace(
            go.Scatter(
                x=ts_df["month_str"],
                y=ts_df["naver_search_index"],
                mode="lines+markers",
                name="네이버",
            )
        )
        if (ts_df["google_trend_index"] > 0).any():
            fig2.add_trace(
                go.Scatter(
                    x=ts_df["month_str"],
                    y=ts_df["google_trend_index"],
                    mode="lines+markers",
                    name="구글 트렌드",
                )
            )
        fig2.update_layout(
            xaxis=dict(title="월"),
            yaxis=dict(title="검색 지수"),
            margin=dict(l=40, r=40, t=10, b=80),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
        )
        st.plotly_chart(fig2, width="stretch")

    with section(title="블로그 / 워드클라우드 스냅샷"):
        blog_months = queries.get_model_blog_months(model_id)

        if not blog_months:
            st.info("이 모델에 대해 저장된 블로그 데이터가 없습니다.")
            return

        month_labels = [_format_month(m) for m in blog_months]
        default_index = len(blog_months) - 1
        selected_label = st.selectbox(
            "블로그/워드클라우드 기준 월 선택",
            options=month_labels,
            index=default_index,
        )
        selected_month = blog_months[month_labels.index(selected_label)]

        tokens_df = queries.get_model_blog_tokens(model_id, selected_month)
        articles_df = queries.get_model_blog_articles(model_id, selected_month)
        image_path = queries.get_blog_wordcloud_image_path(model_id, selected_month)

        col_t, col_w = st.columns([2, 1])

        with col_t:
            with section(title="상위 키워드", spacing=False):
                if tokens_df.empty:
                    st.info("해당 월의 블로그 키워드 데이터가 없습니다.")
                else:
                    display_tokens = tokens_df.copy()
                    display_tokens.rename(
                        columns={
                            "token": "키워드",
                            "total_count": "등장 횟수",
                            "token_rank": "순위",
                        },
                        inplace=True,
                    )
                    st.dataframe(display_tokens, height=300)

        with col_w:
            with section(title="워드클라우드", spacing=False):
                if image_path:
                    image_card(
                        title="Word Cloud",
                        image_url=image_path,
                        caption=f"{brand_name} {model_name_kr} – {_format_month(selected_month)} 기준",
                    )
                else:
                    st.info("워드클라우드 이미지가 없습니다.")

        with section(title="📄 블로그 상위 3개 글", spacing=False):
            if articles_df.empty:
                st.info("해당 월의 블로그 글 데이터가 없습니다.")
            else:
                for _, row in articles_df.head(3).iterrows():
                    title = strip_tags(row["title"])
                    url = row["url"]
                    summary = strip_tags(row.get("summary"))
                    content = strip_tags(row.get("content_plain"))
                    posted_at = row.get("posted_at")
                    posted_at_str = (
                        posted_at.strftime("%Y-%m-%d") if posted_at else "알 수 없음"
                    )

                    st.markdown(f"**[{title}]({url})**")
                    st.caption(f"게시일: {posted_at_str}")

                    preview_text = summary if summary else (content[:300] + "...")
                    st.write(preview_text)
                    st.divider()


if __name__ == "__main__":
    render()
