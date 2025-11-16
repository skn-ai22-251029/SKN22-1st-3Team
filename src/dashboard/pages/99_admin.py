from __future__ import annotations

import os
import shlex
import subprocess
import sys
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from components.layout import page_header, section
from utils.ui import load_global_css

import queries

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _default_run_id() -> str:
    return datetime.now().strftime("%y_%m_%d")


def _default_month_start() -> date:
    today = datetime.today().date()
    return today.replace(day=1)


def _split_multi_value(value: str) -> List[str]:
    if not value:
        return []
    return [token for token in re.split(r"[,\s]+", value.strip()) if token]


ETL_PIPELINES: List[Dict[str, Any]] = [
    {
        "title": "① 다나와 → 모델 메타 + 월간 판매량",
        "summary": "Selenium 크롤링 → CSV 정규화 → car_model/car_model_image 및 model_monthly_sales 적재",
        "tables": [
            {"name": "car_model", "label": "car_model", "dataset_key": None},
            {"name": "car_model_image", "label": "car_model_image", "dataset_key": None},
            {
                "name": "model_monthly_sales",
                "label": "model_monthly_sales",
                "dataset_key": "model_monthly_sales",
            },
        ],
        "steps": [
            "월별 판매/메타 크롤링 (CSV 저장)",
            "정규화 + adoption_rate 산출",
            "car_model 후보 추출 및 메타 업데이트",
            "model_monthly_sales upsert",
        ],
        "commands": [
            {
                "key": "danawa_crawl",
                "label": "다나와 최신 데이터 수집",
                "description": "run_danawa_model_crawl.py – Selenium 기반으로 월별 판매/메타 CSV 추출",
                "script": "src/etl/sales/run_danawa_model_crawl.py",
                "params": [
                    {"name": "run_id", "label": "Run ID", "type": "text", "arg": "--run-id", "default": _default_run_id, "help": "data/raw/danawa/<run_id> 디렉터리명"},
                    {"name": "year", "label": "연도", "type": "int", "arg": "--year", "default": lambda: datetime.today().year, "min_value": 2023},
                    {"name": "start_month", "label": "시작 월", "type": "int", "arg": "--start-month", "default": 1, "min_value": 1, "max_value": 12},
                    {"name": "end_month", "label": "종료 월", "type": "int", "arg": "--end-month", "default": 12, "min_value": 1, "max_value": 12},
                    {"name": "brands", "label": "브랜드 코드 (쉼표/공백 구분)", "type": "text", "arg": "--brands", "default": "hyundai,kia", "split": True},
                    {"name": "headless", "label": "브라우저 숨김(Headless) 사용", "type": "checkbox", "default": True, "flag_when_false": "--no-headless"},
                ],
            },
            {
                "key": "danawa_load",
                "label": "정규화 CSV → DB 반영",
                "description": "load_danawa_sales_to_db.py – normalized CSV를 model_monthly_sales에 적재",
                "script": "src/etl/sales/load_danawa_sales_to_db.py",
                "params": [
                    {"name": "run_id", "label": "Run ID", "type": "text", "arg": "--run-id", "default": _default_run_id},
                    {"name": "brands", "label": "브랜드 코드 (쉼표/공백 구분)", "type": "text", "arg": "--brands", "default": "hyundai,kia", "split": True},
                ],
            },
        ],
    },
    {
        "title": "② 네이버 데이터랩 → 월간 관심도",
        "summary": "Naver DataLab API RAW 적재 → detail 테이블 → model_monthly_interest 집계",
        "tables": [
            {
                "name": "model_monthly_interest_detail",
                "label": "interest_detail",
                "dataset_key": "model_monthly_interest_detail",
            },
            {
                "name": "model_monthly_interest",
                "label": "model_monthly_interest",
                "dataset_key": "model_monthly_interest",
            },
        ],
        "steps": [
            "API 호출 (device×gender)",
            "detail 테이블 upsert",
            "월간 관심도 요약 (naver_search_index)",
        ],
        "commands": [
            {
                "key": "naver_crawl",
                "label": "네이버 API 수집",
                "description": "run_naver_trend_crawl.py – device×gender RAW CSV 저장",
                "script": "src/etl/interest/run_naver_trend_crawl.py",
                "params": [
                    {"name": "run_id", "label": "Run ID", "type": "text", "arg": "--run-id", "default": _default_run_id},
                    {"name": "start_date", "label": "시작일", "type": "date", "arg": "--start-date", "default": _default_month_start},
                    {"name": "end_date", "label": "종료일", "type": "date", "arg": "--end-date", "default": lambda: datetime.today().date()},
                    {"name": "time_unit", "label": "timeUnit", "type": "select", "arg": "--time-unit", "options": ["month", "week", "date"], "default": "month"},
                    {"name": "brands", "label": "대상 브랜드명 (쉼표/공백 구분)", "type": "text", "arg": "--brands", "default": "현대,기아", "split": True},
                    {"name": "limit_models", "label": "모델 제한 (0=전체)", "type": "int", "arg": "--limit-models", "default": 0, "min_value": 0, "skip_if": lambda v: v is None or int(v) <= 0},
                    {"name": "sleep_sec", "label": "API 대기(초)", "type": "float", "arg": "--sleep-sec", "default": 0.3, "min_value": 0.0, "step": 0.1},
                ],
            },
            {
                "key": "naver_detail",
                "label": "detail CSV 적재",
                "description": "load_naver_interest_detail.py – 정규화 detail CSV → model_monthly_interest_detail",
                "script": "src/etl/interest/load_naver_interest_detail.py",
                "params": [
                    {"name": "run_id", "label": "Run ID", "type": "text", "arg": "--run-id", "default": _default_run_id},
                ],
            },
            {
                "key": "naver_aggregate",
                "label": "detail → interest 집계",
                "description": "aggregate_naver_interest.py – model_monthly_interest_detail → model_monthly_interest 집계",
                "script": "src/etl/interest/aggregate_naver_interest.py",
                "params": [],
            },
        ],
    },
    {
        "title": "③ 구글 트렌드 보조 지표",
        "summary": "wide-format CSV 정규화 → google_trend_index 업데이트",
        "tables": [
            {
                "name": "model_monthly_interest",
                "label": "model_monthly_interest",
                "dataset_key": "model_monthly_interest",
            }
        ],
        "steps": [
            "CSV 헤더 매핑 → 모델 매칭",
            "주간 데이터를 월 단위로 변환",
            "google_trend_index upsert",
        ],
        "commands": [
            {
                "key": "google_trend",
                "label": "구글 트렌드 반영",
                "description": (
                    "load_google_trend.py – data/raw/google/<run_id>/ 이하에 샘플과 동일한 구조로 "
                    "직접 업로드한 normalized CSV를 읽어 model_monthly_interest.google_trend_index에 반영합니다."
                ),
                "script": "src/etl/interest/load_google_trend.py",
                "params": [
                    {"name": "run_id", "label": "Run ID", "type": "text", "arg": "--run-id", "default": _default_run_id},
                ],
            }
        ],
    },
    {
        "title": "④ 네이버 블로그 + 워드클라우드",
        "summary": "블로그 3건 검색→ 본문 정제 → 토큰/워드클라우드 생성",
        "tables": [
            {"name": "blog_article", "label": "blog_article", "dataset_key": "blog_article"},
            {
                "name": "blog_token_monthly",
                "label": "blog_token_monthly",
                "dataset_key": "blog_token_monthly",
            },
            {
                "name": "blog_wordcloud",
                "label": "blog_wordcloud",
                "dataset_key": "blog_wordcloud",
            },
        ],
        "steps": [
            "네이버 검색 API로 상위 글 수집",
            "본문 크롤링 + 형태소 분석",
            "blog_article/blog_token_monthly/blog_wordcloud 저장",
        ],
        "commands": [
            {
                "key": "blog_wordcloud",
                "label": "블로그/워드클라우드 실행",
                "description": "run_naver_blog_wordcloud.py – 블로그 텍스트 수집 + Kiwi 분석 + 워드클라우드 생성",
                "script": "src/etl/blog/run_naver_blog_wordcloud.py",
                "params": [
                    {"name": "run_id", "label": "Run ID", "type": "text", "arg": "--run-id", "default": _default_run_id},
                    {"name": "limit_models", "label": "모델 제한 (0=전체)", "type": "int", "arg": "--limit-models", "default": 0, "min_value": 0, "skip_if": lambda v: v is None or int(v) <= 0},
                    {"name": "max_articles", "label": "모델별 수집 글 개수", "type": "int", "arg": "--max-articles", "default": 3, "min_value": 1, "step": 1},
                    {"name": "summary_length", "label": "본문 요약 길이", "type": "int", "arg": "--summary-length", "default": 500, "min_value": 100, "step": 50},
                ],
            }
        ],
    },
]

ADMIN_ACTIONS: List[str] = [
    "다나와 최신 데이터 수집",
    "CSV → DB 반영",
    "네이버 API 호출",
    "detail → interest 집계",
    "구글 트렌드 반영",
    "블로그/워드클라우드 실행",
    "전체 지표 재집계",
    "로그 조회",
]


def _render_param_input(param: Dict[str, Any], prefix: str):
    default = param.get("default")
    if callable(default):
        default = default()
    input_key = f"{prefix}_{param['name']}"
    help_text = param.get("help")
    p_type = param.get("type", "text")

    if p_type == "int":
        return st.number_input(
            param["label"],
            value=int(default or 0),
            min_value=param.get("min_value"),
            max_value=param.get("max_value"),
            step=param.get("step", 1),
            format="%d",
            help=help_text,
            key=input_key,
        )
    if p_type == "float":
        return st.number_input(
            param["label"],
            value=float(default or 0.0),
            min_value=param.get("min_value"),
            max_value=param.get("max_value"),
            step=param.get("step", 0.1),
            help=help_text,
            key=input_key,
        )
    if p_type == "date":
        default_date = default or datetime.today().date()
        return st.date_input(
            param["label"],
            value=default_date,
            help=help_text,
            key=input_key,
        )
    if p_type == "select":
        options = param.get("options", [])
        current = default if default in options else (options[0] if options else None)
        return st.selectbox(
            param["label"],
            options=options,
            index=options.index(current) if current in options else 0,
            help=help_text,
            key=input_key,
        )
    if p_type == "checkbox":
        return st.checkbox(
            param["label"],
            value=bool(default),
            help=help_text,
            key=input_key,
        )
    return st.text_input(
        param["label"],
        value=str(default or ""),
        help=help_text,
        key=input_key,
    )


def _build_cli_args(param_defs: List[Dict[str, Any]], values: Dict[str, Any]) -> List[str]:
    args: List[str] = []
    for param in param_defs:
        name = param["name"]
        arg_name = param.get("arg")
        p_type = param.get("type", "text")
        value = values.get(name)

        if p_type == "checkbox":
            if not value and param.get("flag_when_false"):
                args.append(param["flag_when_false"])
            if value and param.get("flag_when_true"):
                args.append(param["flag_when_true"])
            continue

        if p_type == "date" and isinstance(value, date):
            value = value.strftime("%Y-%m-%d")
        if p_type == "int" and value is not None:
            value = int(value)
        if p_type == "float" and value is not None:
            value = float(value)

        skip_fn = param.get("skip_if")
        if callable(skip_fn) and skip_fn(value):
            continue

        if value in (None, "") or not arg_name:
            continue

        if param.get("split"):
            tokens = _split_multi_value(str(value))
            if tokens:
                args.append(arg_name)
                args.extend(tokens)
        else:
            args.extend([arg_name, str(value)])
    return args


def run_etl_command(script_rel_path: str, cli_args: List[str]) -> tuple[bool, str, str]:
    script_path = PROJECT_ROOT / script_rel_path
    if not script_path.exists():
        message = f"스크립트를 찾을 수 없습니다: {script_path}"
        return False, script_rel_path, message

    cmd = [sys.executable, str(script_path), *cli_args]
    command_str = " ".join(shlex.quote(part) for part in cmd)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        output = result.stdout
        if result.stderr:
            output = (output or "") + ("\n" if output else "") + result.stderr
        if not output:
            output = "(no output)"
        return result.returncode == 0, command_str, output
    except Exception as exc:  # pragma: no cover - Streamlit runtime guard
        return False, command_str, f"명령 실행 실패: {exc}"


def render_etl_command(action: Dict[str, Any]) -> None:
    st.markdown(f"**{action['label']}**")
    if action.get("description"):
        st.caption(action["description"])

    form_key = f"{action['key']}_form"
    with st.form(form_key):
        values: Dict[str, Any] = {}
        for param in action.get("params", []):
            values[param["name"]] = _render_param_input(param, prefix=form_key)
        submitted = st.form_submit_button("실행")

    logs = st.session_state.setdefault("etl_logs", {})
    log_entry = logs.get(action["key"])

    if submitted:
        args = _build_cli_args(action.get("params", []), values)
        with st.spinner("명령 실행 중..."):
            success, command_str, output = run_etl_command(action["script"], args)
        log_entry = {
            "success": success,
            "command": command_str,
            "output": output,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        logs[action["key"]] = log_entry

    if log_entry:
        status = "✅ 성공" if log_entry["success"] else "⚠️ 실패"
        st.write(f"{status} · {log_entry['timestamp']}")
        st.code(f"$ {log_entry['command']}\n\n{log_entry['output']}", language="bash")


def render():
    load_global_css()
    page_header(
        "🛠 Admin / ETL 현황",
        "docs/etl_planning.md 기준으로 주요 데이터 적재 상태와 체크리스트를 정리했습니다.",
    )

    table_counts = queries.get_admin_table_counts()
    latest_months = queries.get_admin_latest_months()

    count_map = (
        dict(zip(table_counts["table_name"], table_counts["cnt"])) if not table_counts.empty else {}
    )
    latest_map = (
        dict(zip(latest_months["dataset"], latest_months["latest_month"]))
        if not latest_months.empty
        else {}
    )

    with section("DB 테이블 레코드 수"):
        if table_counts.empty:
            st.info("조회된 레코드 수가 없습니다.")
        else:
            display_df = table_counts.sort_values("table_name").reset_index(drop=True)
            st.dataframe(display_df, width="stretch")

    with section("데이터셋 최신 월"):
        if latest_months.empty:
            st.info("월 단위 데이터가 아직 없습니다.")
        else:
            display_df = latest_months.copy()
            display_df["latest_month"] = display_df["latest_month"].apply(
                lambda v: v.strftime("%Y-%m") if isinstance(v, (datetime, date)) else v
            )
            st.dataframe(display_df.sort_values("dataset"), width="stretch")

    with section("ETL 라인 점검"):
        for pipeline in ETL_PIPELINES:
            with st.expander(pipeline["title"], expanded=False):
                st.caption(pipeline["summary"])

                table_rows = []
                for tbl in pipeline["tables"]:
                    name = tbl["name"]
                    latest_value = "-"
                    dataset_key = tbl.get("dataset_key")
                    if dataset_key:
                        latest_value = latest_map.get(dataset_key)
                        if isinstance(latest_value, (datetime, date)):
                            latest_value = latest_value.strftime("%Y-%m")
                        elif latest_value is None:
                            latest_value = "-"
                    table_rows.append(
                        {
                            "table": tbl["label"],
                            "rows": f"{int(count_map.get(name, 0)):,}",
                            "latest_month": latest_value or "-",
                        }
                    )
                st.dataframe(pd.DataFrame(table_rows), width="stretch")

                st.markdown("**주요 단계**")
                for step in pipeline["steps"]:
                    st.markdown(f"- {step}")

                if pipeline.get("commands"):
                    st.markdown("**수동 실행**")
                    for command in pipeline["commands"]:
                        render_etl_command(command)
                        st.markdown("---")

    with section("운영 체크리스트"):
        st.markdown(
            "docs/etl_planning.md 3장에 정리된 추천 순서입니다. "
            "각 단계는 상황에 따라 스크립트/노트북을 실행하거나 Airflow/cron에 연결할 수 있습니다."
        )
        for idx, action in enumerate(ADMIN_ACTIONS, start=1):
            st.markdown(f"{idx}. {action}")


if __name__ == "__main__":
    render()
