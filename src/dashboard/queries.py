# src/dashboard/queries.py

from __future__ import annotations

from datetime import date as DateType, datetime
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import text

from db.connection import get_engine

Params = Optional[Dict[str, Any]]


def _fetch_all(query: str, params: Params = None):
    """SELECT 쿼리를 실행해 모든 행을 반환하는 공통 함수."""
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(text(query), params or {}).fetchall()


def _fetch_one(query: str, params: Params = None):
    """SELECT 쿼리를 실행해 단일 행을 반환한다."""
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(text(query), params or {}).fetchone()


def _fetch_value(query: str, params: Params = None):
    """단일 스칼라 값을 반환하는 헬퍼."""
    row = _fetch_one(query, params)
    if row is None:
        return None
    try:
        return row[0]
    except (KeyError, TypeError, IndexError):
        return row


def _read_df(query: str, params: Params = None) -> pd.DataFrame:
    """pd.read_sql 호출을 공통화."""
    engine = get_engine()
    return pd.read_sql(text(query), engine, params=params)


# -------------------------------------------------------
# 공통: 최신 month, 브랜드 목록
# -------------------------------------------------------


def get_latest_month_for_overview() -> Optional[DateType]:
    """
    Overview 기본 기준 월: '판매량 데이터가 존재하는 가장 최근 월'.

    일부 환경에서 result.fetchone()이 Row가 아닌 튜플을 반환할 수 있으므로,
    인덱스 0 기반으로 안전하게 처리한다.
    """
    latest = _fetch_value("SELECT MAX(month) AS latest_month FROM model_monthly_sales")

    if latest is None:
        return None

    # datetime으로 들어오면 date만 추출
    if isinstance(latest, datetime):
        return latest.date()
    return latest


def get_brand_list() -> List[str]:
    """
    car_model 기준으로 브랜드 리스트(현대/기아 등) 반환.
    """
    rows = _fetch_all(
        """
        SELECT DISTINCT brand_name
        FROM car_model
        ORDER BY brand_name
        """
    )
    return [r[0] for r in rows]


# -------------------------------------------------------
# Overview 메인: 최신 월 기준 판매/관심도 TOP N
# -------------------------------------------------------


@dataclass
class OverviewTopRow:
    model_id: int
    brand_name: str
    model_name_kr: str
    sales_units: Optional[int]
    adoption_rate: Optional[float]
    naver_search_index: Optional[int]
    google_trend_index: Optional[int]
    danawa_pop_rank: Optional[int]
    danawa_pop_rank_size: Optional[int]


def get_overview_top_models(
    month: date,
    brand_name: Optional[str] = None,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    특정 month + 브랜드 기준으로
    판매량/보급률 + 관심도(네이버/구글) + 다나와 랭킹을 한 번에 조회.

    반환: DataFrame
      columns = [
        'model_id', 'brand_name', 'model_name_kr',
        'sales_units', 'adoption_rate',
        'naver_search_index', 'google_trend_index',
        'danawa_pop_rank', 'danawa_pop_rank_size'
      ]
    """
    sql = """
        SELECT
            cm.model_id,
            cm.brand_name,
            cm.model_name_kr,
            s.sales_units,
            s.adoption_rate,
            i.naver_search_index,
            i.google_trend_index,
            i.danawa_pop_rank,
            i.danawa_pop_rank_size
        FROM car_model AS cm
        LEFT JOIN model_monthly_sales AS s
            ON s.model_id = cm.model_id
            AND s.month = :month
        LEFT JOIN model_monthly_interest AS i
            ON i.model_id = cm.model_id
            AND i.month = :month
        WHERE (:brand_name IS NULL OR cm.brand_name = :brand_name)
          AND (
                s.sales_units IS NOT NULL
             OR i.naver_search_index IS NOT NULL
             OR i.google_trend_index IS NOT NULL
          )
        ORDER BY
            COALESCE(s.sales_units, 0) DESC,
            cm.brand_name,
            cm.model_name_kr
        LIMIT :top_n
        """

    params = {
        "month": month,
        "brand_name": brand_name,
        "top_n": int(top_n),
    }

    rows = _fetch_all(sql, params)

    df = pd.DataFrame(
        rows,
        columns=[
            "model_id",
            "brand_name",
            "model_name_kr",
            "sales_units",
            "adoption_rate",
            "naver_search_index",
            "google_trend_index",
            "danawa_pop_rank",
            "danawa_pop_rank_size",
        ],
    )

    # 관심도 score 계산 (0.7 * 네이버 + 0.3 * 구글, 구글 없으면 네이버만)
    if not df.empty:
        # 네이버/구글 0~1 정규화 (각 컬럼의 최대값 기준)
        def _norm(col: str) -> pd.Series:
            if col not in df or df[col].isna().all():
                return pd.Series([None] * len(df))
            max_val = df[col].max()
            if not max_val or max_val == 0:
                return pd.Series([None] * len(df))
            return df[col] / max_val

        df["naver_norm"] = _norm("naver_search_index")
        df["google_norm"] = _norm("google_trend_index")

        def _interest_row(row) -> Optional[float]:
            n = row.get("naver_norm")
            g = row.get("google_norm")
            if pd.isna(n) and pd.isna(g):
                return None
            if pd.isna(g) or g is None:
                # 구글 없으면 네이버만
                return float(n) if n is not None else None
            if pd.isna(n) or n is None:
                # 네이버 없고 구글만 있다면 구글만 (혹시 모를 케이스 대비)
                return float(g)
            # 둘 다 있으면 0.7 / 0.3
            return 0.7 * float(n) + 0.3 * float(g)

        df["interest_score"] = df.apply(_interest_row, axis=1)

    return df


# -------------------------------------------------------
# Overview: 특정 모델의 최근 6개월 판매/관심도
# -------------------------------------------------------


def get_model_recent_sales(model_id: int, months_back: int = 6) -> pd.DataFrame:
    """
    특정 모델의 최근 N개월 판매 추이.
    반환 컬럼: month, sales_units, market_total_units, adoption_rate
    """
    sql = """
        SELECT
            month,
            sales_units,
            market_total_units,
            adoption_rate
        FROM model_monthly_sales
        WHERE model_id = :model_id
        ORDER BY month DESC
        LIMIT :limit
        """
    rows = _fetch_all(sql, {"model_id": model_id, "limit": int(months_back)})

    df = pd.DataFrame(
        rows,
        columns=["month", "sales_units", "market_total_units", "adoption_rate"],
    )
    # 그래프용으로 오래된 월이 왼쪽으로 가게 정렬
    return df.sort_values("month") if not df.empty else df


def get_model_recent_interest(model_id: int, months_back: int = 6) -> pd.DataFrame:
    """
    특정 모델의 최근 N개월 관심도 추이.
    반환 컬럼: month, naver_search_index, google_trend_index, danawa_pop_rank
    """
    sql = """
        SELECT
            month,
            naver_search_index,
            google_trend_index,
            danawa_pop_rank
        FROM model_monthly_interest
        WHERE model_id = :model_id
        ORDER BY month DESC
        LIMIT :limit
        """
    rows = _fetch_all(sql, {"model_id": model_id, "limit": int(months_back)})

    df = pd.DataFrame(
        rows,
        columns=[
            "month",
            "naver_search_index",
            "google_trend_index",
            "danawa_pop_rank",
        ],
    )
    return df.sort_values("month") if not df.empty else df


# -------------------------------------------------------
# Overview: 블로그/워드클라우드 (최신 월)
# -------------------------------------------------------


def get_latest_blog_month_for_model(model_id: int) -> Optional[date]:
    """
    해당 모델에 대해 blog_token_monthly 기준으로 가장 최신 month 반환.
    블로그 데이터 없으면 None.
    """
    return _fetch_value(
        """
        SELECT MAX(month) AS latest_month
        FROM blog_token_monthly
        WHERE model_id = :model_id
        """,
        {"model_id": model_id},
    )


def get_blog_tokens_for_model_month(
    model_id: int, month: date, top_n: int = 20
) -> pd.DataFrame:
    """
    blog_token_monthly에서 해당 모델/월의 토큰 랭킹 반환.
    """
    sql = """
        SELECT
            token,
            total_count,
            token_rank
        FROM blog_token_monthly
        WHERE model_id = :model_id
          AND month = :month
        ORDER BY token_rank ASC
        LIMIT :limit
        """
    rows = _fetch_all(
        sql,
        {"model_id": model_id, "month": month, "limit": int(top_n)},
    )
    return pd.DataFrame(rows, columns=["token", "total_count", "token_rank"])


def get_blog_wordcloud_image_path(model_id: int, month: date) -> Optional[str]:
    """
    blog_wordcloud에서 해당 모델/월의 이미지 경로 1개 반환.
    """
    row = _fetch_one(
        """
        SELECT image_path
        FROM blog_wordcloud
        WHERE model_id = :model_id
          AND month = :month
        ORDER BY id DESC
        LIMIT 1
        """,
        {"model_id": model_id, "month": month},
    )
    if not row:
        return None
    try:
        return row["image_path"]
    except (KeyError, TypeError):
        return row[0]


def get_blog_articles_for_model_month(
    model_id: int, month: date, limit: int = 3
) -> pd.DataFrame:
    """
    blog_article에서 해당 모델/월 기준 상위 N개 블로그 글 정보 반환.
    """
    sql = """
        SELECT
            title,
            url,
            summary,
            posted_at,
            search_rank
        FROM blog_article
        WHERE model_id = :model_id
          AND month = :month
        ORDER BY search_rank ASC
        LIMIT :limit
        """
    rows = _fetch_all(
        sql,
        {"model_id": model_id, "month": month, "limit": int(limit)},
    )
    return pd.DataFrame(
        rows,
        columns=["title", "url", "summary", "posted_at", "search_rank"],
    )


def load_interest_detail(month: DateType, brand_name: Optional[str]) -> pd.DataFrame:
    """
    model_monthly_interest_detail 테이블에서
    해당 월(+제조사 필터)의 RAW 네이버 디테일 데이터를 불러온다.
    """
    base_sql = """
        SELECT
            d.model_id,
            c.brand_name,
            c.model_name_kr,
            d.device,
            d.gender,
            d.age_group,
            d.ratio
        FROM model_monthly_interest_detail d
        JOIN car_model c ON c.model_id = d.model_id
        WHERE d.month = :month
    """
    params = {"month": month}

    if brand_name is not None:
        base_sql += " AND c.brand_name = :brand_name"
        params["brand_name"] = brand_name

    base_sql += """
        ORDER BY
            c.brand_name,
            c.model_name_kr,
            d.device,
            d.gender,
            d.age_group
    """

    return _read_df(base_sql, params=params)


def get_monthly_sales_top_models(
    month: DateType,
    brand_name: Optional[str],
    top_n: int,
) -> pd.DataFrame:
    """
    보급률(점유율) Top N 모델 조회.

    반환 컬럼:
        - model_id
        - brand_name
        - model_name_kr
        - month
        - sales_units
        - market_total_units
        - adoption_rate
    """
    base_sql = """
        SELECT
            ms.model_id,
            c.brand_name,
            c.model_name_kr,
            ms.month,
            ms.sales_units,
            ms.market_total_units,
            ms.adoption_rate
        FROM model_monthly_sales ms
        JOIN car_model c ON c.model_id = ms.model_id
        WHERE ms.month = :month
    """

    params = {"month": month}

    if brand_name is not None:
        base_sql += " AND c.brand_name = :brand_name"
        params["brand_name"] = brand_name

    base_sql += """
        ORDER BY
            ms.adoption_rate DESC,
            ms.sales_units DESC
        LIMIT :limit
    """
    params["limit"] = int(top_n)

    return _read_df(base_sql, params=params)


def get_monthly_sales_raw(
    month: DateType,
    brand_name: Optional[str],
) -> pd.DataFrame:
    """
    해당 월 전체 모델의 판매/보급률 RAW 데이터 조회.
    (테이블 아래쪽에 그대로 깔아줄 용도)
    """
    base_sql = """
        SELECT
            ms.model_id,
            c.brand_name,
            c.model_name_kr,
            ms.month,
            ms.sales_units,
            ms.market_total_units,
            ms.adoption_rate,
            ms.source
        FROM model_monthly_sales ms
        JOIN car_model c ON c.model_id = ms.model_id
        WHERE ms.month = :month
    """

    params = {"month": month}

    if brand_name is not None:
        base_sql += " AND c.brand_name = :brand_name"
        params["brand_name"] = brand_name

    base_sql += """
        ORDER BY
            c.brand_name,
            ms.sales_units DESC
    """

    return _read_df(base_sql, params=params)


def get_models_by_brand(brand_name: str) -> pd.DataFrame:
    """
    특정 브랜드의 모델 목록을 반환.
    columns: model_id, brand_name, model_name_kr
    """
    sql = """
        SELECT
            model_id,
            brand_name,
            model_name_kr
        FROM car_model
        WHERE brand_name = :brand_name
        ORDER BY model_name_kr
        """
    return _read_df(sql, params={"brand_name": brand_name})


def get_model_timeseries(
    model_id: int,
    start_month: DateType,
    end_month: DateType,
) -> pd.DataFrame:
    """
    단일 모델에 대해, 기간 내 월별 판매/관심도 타임라인 조회.

    반환 컬럼:
        month,
        naver_search_index,
        google_trend_index,
        sales_units,
        adoption_rate
    """
    sql = """
        SELECT
            m.month,
            m.naver_search_index,
            m.google_trend_index,
            s.sales_units,
            s.adoption_rate
        FROM model_monthly_interest m
        LEFT JOIN model_monthly_sales s
            ON m.model_id = s.model_id
            AND m.month = s.month
        WHERE
            m.model_id = :model_id
            AND m.month BETWEEN :start_month AND :end_month
        ORDER BY
            m.month
        """
    params = {
        "model_id": model_id,
        "start_month": start_month,
        "end_month": end_month,
    }
    return _read_df(sql, params=params)


def get_model_blog_tokens(model_id: int, month: DateType) -> pd.DataFrame:
    """
    blog_token_monthly에서 특정 모델/월의 키워드 랭킹 조회.
    """
    sql = """
        SELECT
            token,
            total_count,
            token_rank
        FROM blog_token_monthly
        WHERE model_id = :model_id
          AND month = :month
        ORDER BY token_rank ASC
        """
    return _read_df(sql, params={"model_id": model_id, "month": month})


def get_model_blog_articles(model_id: int, month: DateType) -> pd.DataFrame:
    """
    blog_article에서 특정 모델/월의 상위 3개 글 조회.
    (search_rank 기준)
    """
    sql = """
        SELECT
            search_rank,
            title,
            url,
            summary
        FROM blog_article
        WHERE model_id = :model_id
          AND month = :month
        ORDER BY search_rank ASC
        LIMIT 3
        """
    return _read_df(sql, params={"model_id": model_id, "month": month})


def get_model_wordcloud_path(model_id: int, month: DateType) -> Optional[str]:
    """
    blog_wordcloud에서 이미지 경로 하나 가져오기.
    없으면 None.
    """
    row = _fetch_one(
        """
        SELECT image_path
        FROM blog_wordcloud
        WHERE model_id = :model_id
          AND month = :month
        LIMIT 1
        """,
        {"model_id": model_id, "month": month},
    )
    if row is None:
        return None
    try:
        return row["image_path"]
    except Exception:
        return row[0]


# ================================
#  블로그 글 3개 조회
# ================================
def load_blog_articles(model_id: int, month: date) -> pd.DataFrame:
    """
    blog_article 테이블에서 모델별 상위 3개 블로그 글을 반환.
    """
    sql = """
        SELECT
            article_id,
            model_id,
            month,
            search_keyword,
            search_rank,
            title,
            url,
            summary,
            content_plain,
            posted_at,
            collected_at
        FROM blog_article
        WHERE model_id = :model_id
          AND month = :month
        ORDER BY search_rank ASC
        LIMIT 3
    """

    return _read_df(sql, params={"model_id": model_id, "month": month})


def get_model_blog_months(model_id: int) -> List[date]:
    """해당 모델에 대해 블로그 글이 저장된 month 목록을 오래된 순으로 반환."""
    rows = _fetch_all(
        """
        SELECT DISTINCT month
        FROM blog_article
        WHERE model_id = :model_id
        ORDER BY month
        """,
        {"model_id": model_id},
    )

    return [row[0] for row in rows]


def get_position_months() -> List[date]:
    """관심도/보급률 포지션맵에서 선택 가능한 month 목록을 반환."""
    rows = _fetch_all(
        """
        SELECT DISTINCT month
        FROM (
            SELECT month FROM model_monthly_sales
            UNION
            SELECT month FROM model_monthly_interest
        ) AS m
        ORDER BY month
        """
    )

    return [row[0] for row in rows]

def get_model_position_map(month: date) -> pd.DataFrame:
    """
    주어진 month 기준으로
    - 브랜드, 모델명
    - 판매량(sales_units), 보급률(adoption_rate)
    - 네이버/구글 지수
    - interest_score (0~100 기준 가중합)
    를 모두 포함하는 포지션맵용 DataFrame 반환.
    """
    sql = """
        SELECT
            c.model_id,
            c.brand_name,
            c.model_name_kr,
            s.sales_units,
            s.adoption_rate,
            i.naver_search_index,
            i.google_trend_index
        FROM car_model c
        LEFT JOIN model_monthly_sales s
            ON s.model_id = c.model_id
           AND s.month = :month
        LEFT JOIN model_monthly_interest i
            ON i.model_id = c.model_id
           AND i.month = :month
        WHERE
            s.sales_units IS NOT NULL
            OR i.naver_search_index IS NOT NULL
            OR i.google_trend_index IS NOT NULL
        ORDER BY
            c.brand_name,
            c.model_name_kr
        """

    df = _read_df(sql, params={"month": month})

    if df.empty:
        return df

    # 숫자 컬럼 정리
    for col in ["sales_units", "adoption_rate", "naver_search_index", "google_trend_index"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # NaN → 0 대체
    df["naver_search_index"] = df["naver_search_index"].fillna(0.0)
    df["google_trend_index"] = df["google_trend_index"].fillna(0.0)

    # 관심도 점수 계산
    has_google = df["google_trend_index"] > 0
    df["interest_score"] = df["naver_search_index"]
    df.loc[has_google, "interest_score"] = (
        0.7 * df.loc[has_google, "naver_search_index"]
        + 0.3 * df.loc[has_google, "google_trend_index"]
    )

    return df


# -------------------------------------------------------
# Admin/운영 보조용 쿼리
# -------------------------------------------------------


def get_admin_table_counts() -> pd.DataFrame:
    """주요 테이블의 레코드 수를 빠르게 확인한다."""
    rows = _fetch_all(
        """
        SELECT 'car_model' AS table_name, COUNT(*) AS cnt FROM car_model
        UNION ALL
        SELECT 'car_model_image', COUNT(*) FROM car_model_image
        UNION ALL
        SELECT 'model_monthly_sales', COUNT(*) FROM model_monthly_sales
        UNION ALL
        SELECT 'model_monthly_interest', COUNT(*) FROM model_monthly_interest
        UNION ALL
        SELECT 'model_monthly_interest_detail', COUNT(*) FROM model_monthly_interest_detail
        UNION ALL
        SELECT 'blog_article', COUNT(*) FROM blog_article
        UNION ALL
        SELECT 'blog_token_monthly', COUNT(*) FROM blog_token_monthly
        UNION ALL
        SELECT 'blog_wordcloud', COUNT(*) FROM blog_wordcloud
        """
    )
    return pd.DataFrame(rows, columns=["table_name", "cnt"])


def get_admin_latest_months() -> pd.DataFrame:
    """각 데이터셋의 최신 month를 반환한다."""
    rows = _fetch_all(
        """
        SELECT 'model_monthly_sales' AS dataset, MAX(month) AS latest_month FROM model_monthly_sales
        UNION ALL
        SELECT 'model_monthly_interest', MAX(month) FROM model_monthly_interest
        UNION ALL
        SELECT 'model_monthly_interest_detail', MAX(month) FROM model_monthly_interest_detail
        UNION ALL
        SELECT 'blog_article', MAX(month) FROM blog_article
        UNION ALL
        SELECT 'blog_token_monthly', MAX(month) FROM blog_token_monthly
        UNION ALL
        SELECT 'blog_wordcloud', MAX(month) FROM blog_wordcloud
        """
    )
    return pd.DataFrame(rows, columns=["dataset", "latest_month"])
