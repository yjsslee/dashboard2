import os
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st


st.set_page_config(
    page_title="두산에너빌리티 6개월 차트",
    page_icon="📈",
    layout="wide",
)


# ---------------------------------------------------------
# 설정
# ---------------------------------------------------------
STOCK_CODE = "034020"  # 두산에너빌리티
STOCK_NAME = "두산에너빌리티"


def get_secret(name: str, default: str = "") -> str:
    """Streamlit Secrets 우선, 없으면 환경변수에서 읽습니다."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.getenv(name, default)).strip()


APP_KEY = get_secret("KIWOOM_APP_KEY")
APP_SECRET = get_secret("KIWOOM_APP_SECRET")
ENV = get_secret("KIWOOM_ENV", "mock").lower()

if ENV not in {"mock", "real"}:
    ENV = "mock"

BASE_URL = (
    "https://mockapi.kiwoom.com"
    if ENV == "mock"
    else "https://api.kiwoom.com"
)


# ---------------------------------------------------------
# 키움 REST API
# ---------------------------------------------------------
def get_access_token(app_key: str, app_secret: str) -> str:
    """OAuth 2.0 Client Credentials 방식으로 접근토큰을 발급합니다."""
    url = f"{BASE_URL}/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": app_secret,
    }
    headers = {"Content-Type": "application/json;charset=UTF-8"}

    response = requests.post(url, headers=headers, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()

    if str(data.get("return_code", "0")) not in {"0", "0000"}:
        raise RuntimeError(data.get("return_msg", "접근토큰 발급에 실패했습니다."))

    token = data.get("token")
    if not token:
        raise RuntimeError("키움 API 응답에서 접근토큰을 찾지 못했습니다.")
    return token


@st.cache_data(ttl=300, show_spinner=False)
def fetch_daily_chart(app_key: str, app_secret: str, end_date: str) -> pd.DataFrame:
    """두산에너빌리티 일봉을 조회하고 최근 6개월만 반환합니다."""
    token = get_access_token(app_key, app_secret)

    url = f"{BASE_URL}/api/dostk/chart"
    rows = []
    cont_yn = "N"
    next_key = ""

    # 최근 6개월보다 충분히 넓은 범위에서 시작해 연속조회합니다.
    # ka10081은 1회 최대 600봉이므로 일반적으로 6개월은 1회 응답으로도 충분합니다.
    for _ in range(5):
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {token}",
            "api-id": "ka10081",
            "cont-yn": cont_yn,
            "next-key": next_key,
        }
        payload = {
            "stk_cd": STOCK_CODE,
            "base_dt": end_date,
            "upd_stkpc_tp": "1",
        }

        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()

        return_code = str(data.get("return_code", "0"))
        if return_code not in {"0", "0000"}:
            raise RuntimeError(data.get("return_msg", "차트 조회에 실패했습니다."))

        rows.extend(data.get("stk_dt_pole_chart_qry", []) or [])

        cont_yn = response.headers.get("cont-yn", "N").upper()
        next_key = response.headers.get("next-key", "")
        if cont_yn != "Y" or not next_key:
            break

    if not rows:
        raise RuntimeError("차트 데이터가 없습니다.")

    df = pd.DataFrame(rows)
    required = ["dt", "open_pric", "high_pric", "low_pric", "cur_prc", "trde_qty"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise RuntimeError(f"차트 응답 필드가 예상과 다릅니다: {missing}")

    df = df[required].copy()
    df["날짜"] = pd.to_datetime(df["dt"].astype(str), format="%Y%m%d", errors="coerce")

    # 키움 차트 가격에는 부호가 전일 대비 방향을 나타내는 경우가 있으므로
    # 차트용 가격은 부호를 제거한 절댓값으로 변환합니다.
    for column in ["open_pric", "high_pric", "low_pric", "cur_prc", "trde_qty"]:
        df[column] = pd.to_numeric(
            df[column].astype(str).str.replace(",", "", regex=False).str.replace("+", "", regex=False),
            errors="coerce",
        )

    df = df.dropna(subset=["날짜", "open_pric", "high_pric", "low_pric", "cur_prc"])
    df = df.drop_duplicates(subset=["날짜"]).sort_values("날짜")

    start_date = pd.Timestamp(end_date) - pd.DateOffset(months=6)
    df = df[(df["날짜"] >= start_date) & (df["날짜"] <= pd.Timestamp(end_date))]

    if df.empty:
        raise RuntimeError("최근 6개월에 해당하는 차트 데이터가 없습니다.")

    return df


# ---------------------------------------------------------
# 화면
# ---------------------------------------------------------
st.title("📈 두산에너빌리티 6개월 주가 차트")
st.caption("키움증권 REST API · 주식일봉차트조회요청(ka10081) · 수정주가 적용")

with st.sidebar:
    st.subheader("조회 설정")
    st.write(f"종목: **{STOCK_NAME} ({STOCK_CODE})**")
    st.write(f"API 환경: **{'모의투자' if ENV == 'mock' else '실전투자'}**")
    refresh = st.button("🔄 데이터 새로고침", use_container_width=True)

if refresh:
    st.cache_data.clear()
    st.rerun()

if not APP_KEY or not APP_SECRET:
    st.error("키움 API 인증정보가 설정되지 않았습니다.")
    st.info(
        "Streamlit Cloud에서는 Settings → Secrets에 KIWOOM_APP_KEY, "
        "KIWOOM_APP_SECRET을 등록하세요. 기본 환경은 모의투자(mock)입니다."
    )
    st.code(
        '[secrets]\n'
        'KIWOOM_APP_KEY = "여기에_APP_KEY"\n'
        'KIWOOM_APP_SECRET = "여기에_APP_SECRET"\n'
        'KIWOOM_ENV = "mock"',
        language="toml",
    )
    st.stop()

end_date = datetime.now().strftime("%Y%m%d")

try:
    with st.spinner("키움증권에서 두산에너빌리티 6개월 데이터를 가져오는 중입니다..."):
        df = fetch_daily_chart(APP_KEY, APP_SECRET, end_date)
except requests.HTTPError as exc:
    st.error(f"키움 API HTTP 오류: {exc}")
    st.stop()
except Exception as exc:
    st.error(f"차트 조회 오류: {exc}")
    st.stop()

latest = df.iloc[-1]
first = df.iloc[0]
change_pct = ((latest["cur_prc"] / first["cur_prc"]) - 1) * 100

c1, c2, c3, c4 = st.columns(4)
c1.metric("최근 종가", f"{latest['cur_prc']:,.0f}원")
c2.metric("6개월 시작 종가", f"{first['cur_prc']:,.0f}원")
c3.metric("6개월 수익률", f"{change_pct:+.2f}%")
c4.metric("조회 거래일", f"{len(df):,}일")

chart_df = df.set_index("날짜")[["open_pric", "high_pric", "low_pric", "cur_prc"]].rename(
    columns={
        "open_pric": "시가",
        "high_pric": "고가",
        "low_pric": "저가",
        "cur_prc": "종가",
    }
)

st.subheader("6개월 일봉")
st.line_chart(chart_df, height=500)

with st.expander("최근 거래일 데이터 보기"):
    table = df.tail(20).copy()
    table["날짜"] = table["날짜"].dt.strftime("%Y-%m-%d")
    table = table.rename(
        columns={
            "날짜": "날짜",
            "open_pric": "시가",
            "high_pric": "고가",
            "low_pric": "저가",
            "cur_prc": "종가",
            "trde_qty": "거래량",
        }
    )
    st.dataframe(table[["날짜", "시가", "고가", "저가", "종가", "거래량"]], use_container_width=True, hide_index=True)

st.caption("※ 이 프로그램은 조회 전용이며 주문 기능은 포함하지 않습니다. API 키와 Secret은 GitHub에 저장하지 마세요.")
