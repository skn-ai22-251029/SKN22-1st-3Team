from datetime import date as DateType
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.images import image_card
from components.layout import page_header, section, two_columns_ratio
from utils.ui import load_global_css

import queries


def _format_month(d: DateType) -> str:
    return d.strftime("%Y-%m")


def render():
    load_global_css()
    page_header(
        "📊 Overview – 국내 자동차 시장 한눈에 보기",
        "현대/기아 자동차 시장의 판매량, 관심도, 블로그 및 워드 클라우드를 한 곳에 나타냈습니다.",
    )

    latest_month = queries.get_latest_month_for_overview()
    if latest_month is None:
        st.warning("아직 model_monthly_sales / model_monthly_interest 데이터가 없습니다.")
        return

    latest_month = latest_month.replace(day=1)
    brand_list = queries.get_brand_list()

    with section(title="기준 월 · 제조사 · TOP N 필터"):
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

    df_top = queries.get_overview_top_models(
        month=month, brand_name=brand_param, top_n=top_n
    )

    if df_top.empty:
        st.info("선택한 조건에 해당하는 데이터가 없습니다.")
        return

    df_top_sorted = df_top.sort_values(
        ["sales_units", "interest_score"],
        ascending=[False, False],
    )

    total_sales = pd.to_numeric(df_top["sales_units"], errors="coerce").fillna(0).sum()
    if "interest_score" in df_top:
        interest_series = pd.to_numeric(df_top["interest_score"], errors="coerce")
        avg_interest = (
            interest_series.dropna().mean()
            if not interest_series.dropna().empty
            else None
        )
    else:
        avg_interest = None

    with section(title="판매량 vs 관심도 (TOP N)"):
        kpi_cols = st.columns(4)
        with kpi_cols[0]:
            st.metric("TOP N 총 판매량", f"{int(total_sales):,} 대")
        with kpi_cols[1]:
            if avg_interest is not None:
                st.metric("평균 관심도 점수", f"{avg_interest*100:.1f}")
            else:
                st.metric("평균 관심도 점수", "데이터 없음")
        with kpi_cols[2]:
            st.metric("선택된 제조사", brand_name)
        with kpi_cols[3]:
            st.metric("기준 월", _format_month(month))

        chart_df = df_top_sorted.copy()
        chart_df["label"] = chart_df["brand_name"] + " " + chart_df["model_name_kr"]

        sales_series = pd.to_numeric(chart_df["sales_units"], errors="coerce").fillna(0)

        if "interest_score" in chart_df:
            interest_series = (
                pd.to_numeric(chart_df["interest_score"], errors="coerce").fillna(0)
                * 100
            )
        else:
            interest_series = pd.Series([0] * len(chart_df), index=chart_df.index)

        chart_data = pd.DataFrame(
            {
                "모델": chart_df["label"],
                "판매량": sales_series,
                "관심도 점수": interest_series,
            }
        )

        fig = go.Figure()
        fig.add_bar(
            x=chart_data["모델"],
            y=chart_data["판매량"],
            name="판매량(대)",
            yaxis="y1",
        )
        fig.add_trace(
            go.Scatter(
                x=chart_data["모델"],
                y=chart_data["관심도 점수"],
                name="관심도 점수(0~100)",
                mode="lines+markers",
                yaxis="y2",
            )
        )
        fig.update_layout(
            xaxis=dict(title="모델"),
            yaxis=dict(title="판매량(대)", side="left"),
            yaxis2=dict(
                title="관심도 점수(0~100)",
                overlaying="y",
                side="right",
            ),
            legend=dict(orientation="h", y=-0.2),
            margin=dict(l=40, r=40, t=10, b=40),
        )

        st.plotly_chart(fig, width="stretch")
        st.markdown(
            '<div class="note-text">관심도 점수는 네이버/구글 지수를 0~100으로 정규화한 후, '
            "0.7 × 네이버 + 0.3 × 구글(구글 지수 없으면 네이버만 사용)으로 계산됩니다.</div>",
            unsafe_allow_html=True,
        )

    with section(title="선택 모델 상세 요약"):
        select_col1, _ = st.columns([2, 3])
        with select_col1:
            model_options = df_top_sorted[
                ["model_id", "brand_name", "model_name_kr"]
            ].copy()
            model_options["label"] = (
                model_options["brand_name"] + " " + model_options["model_name_kr"]
            )
            selected_label = st.selectbox(
                "모델 선택", options=model_options["label"].tolist()
            )

        selected_row = model_options[model_options["label"] == selected_label].iloc[0]
        selected_model_id = int(selected_row["model_id"])
        selected_model_name = selected_row["label"]

        sub_left, sub_right = two_columns_ratio(1, 1)

        with sub_left:
            with section(
                title=f"📈 최근 6개월 판매/보급률 – {selected_model_name}", spacing=False
            ):
                sales_df = queries.get_model_recent_sales(
                    selected_model_id, months_back=6
                )
                if sales_df.empty:
                    st.info("최근 6개월 판매 데이터가 없습니다.")
                else:
                    chart_df = sales_df.copy()
                    chart_df["월"] = chart_df["month"].apply(_format_month)
                    chart_df["adoption_rate"] = pd.to_numeric(
                        chart_df["adoption_rate"], errors="coerce"
                    )
                    chart_df["보급률(%)"] = (chart_df["adoption_rate"] * 100).round(2)
                    st.bar_chart(
                        chart_df.set_index("월")[["sales_units", "보급률(%)"]],
                        width="stretch",
                    )

        with sub_right:
            with section(
                title=f"🔥 최근 6개월 관심도 – {selected_model_name}", spacing=False
            ):
                interest_df = queries.get_model_recent_interest(
                    selected_model_id, months_back=6
                )
                if interest_df.empty:
                    st.info("최근 6개월 관심도 데이터가 없습니다.")
                else:
                    chart_df = interest_df.copy()
                    chart_df["월"] = chart_df["month"].apply(_format_month)
                    line_df = chart_df.set_index("월")[
                        ["naver_search_index", "google_trend_index"]
                    ]
                    line_df.rename(
                        columns={
                            "naver_search_index": "네이버 지수",
                            "google_trend_index": "구글 트렌드",
                        },
                        inplace=True,
                    )
                    st.line_chart(line_df, width="stretch")

    with section(title="📝 블로그 리뷰 & 워드클라우드"):
        blog_month = queries.get_latest_blog_month_for_model(selected_model_id)
        if blog_month is None:
            st.info("해당 모델에 대한 블로그 워드클라우드 데이터가 아직 없습니다.")
            return

        wc_col, article_col = two_columns_ratio(1, 1)

        with wc_col:
            with section(
                title=f"워드클라우드 – {_format_month(blog_month)}", spacing=False
            ):
                image_path = queries.get_blog_wordcloud_image_path(
                    selected_model_id, blog_month
                )
                if image_path:
                    image_card(
                        title="Word Cloud",
                        image_url=image_path,
                        caption=f"{selected_model_name} – {_format_month(blog_month)} 기준",
                    )
                else:
                    st.info("워드클라우드 이미지가 없습니다.")

                tokens_df = queries.get_blog_tokens_for_model_month(
                    selected_model_id, blog_month, top_n=20
                )
                if tokens_df.empty:
                    st.info("토큰 분석 데이터가 없습니다.")
                else:
                    tokens_df.rename(
                        columns={
                            "token": "단어",
                            "total_count": "등장 횟수",
                            "token_rank": "순위",
                        },
                        inplace=True,
                    )
                    st.dataframe(tokens_df, width="stretch", height=300)

        with article_col:
            with section(
                title=f"상위 블로그 글 – {_format_month(blog_month)}", spacing=False
            ):
                articles_df = queries.get_blog_articles_for_model_month(
                    selected_model_id, blog_month, limit=3
                )
                if articles_df.empty:
                    st.info("블로그 글 데이터가 없습니다.")
                else:
                    for _, row in articles_df.iterrows():
                        st.markdown(f"**[{row['title']}]({row['url']})**")
                        if row.get("summary"):
                            st.write(row["summary"][:300] + "...")
                        if row.get("posted_at"):
                            st.caption(f"작성일: {row['posted_at']}")
                        st.markdown("---")


if __name__ == "__main__":
    render()
