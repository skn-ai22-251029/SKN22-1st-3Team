import streamlit as st
import pathlib


def load_global_css():
    base_dir = pathlib.Path(__file__).resolve().parents[1]  # /src/dashboard
    css_path = base_dir / "assets" / "style.css"

    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    else:
        st.warning(f"CSS 파일을 찾을 수 없습니다: {css_path}")
