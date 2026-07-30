# main.py
# ------------------------------------------------------------
# 전국 시군구별 14~19세 인구 비율 단계구분도
# Streamlit Cloud 배포용 앱
# ------------------------------------------------------------
# 필요한 외부 라이브러리:
# - plotly
# - requests
#
# streamlit, pandas, numpy는 기본 설치라고 하셨으므로
# requirements.txt에 추가하지 않아도 됩니다.
# ------------------------------------------------------------

import streamlit as st
import pandas as pd
import plotly.express as px
import requests


# ------------------------------------------------------------
# 1. 앱 기본 설정
# ------------------------------------------------------------

st.set_page_config(
    page_title="전국 14~19세 인구 비율 지도",
    page_icon="🗺️",
    layout="wide"
)


# ------------------------------------------------------------
# 2. 데이터 주소
# ------------------------------------------------------------

POPULATION_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEOJSON_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"


# ------------------------------------------------------------
# 3. 분석할 나이와 구간 설정
# ------------------------------------------------------------

# 14세부터 19세까지를 더해서 사용할 것입니다.
TARGET_AGES = list(range(14, 20))
TARGET_COLS = [f"계_{age}세" for age in TARGET_AGES]

# 요청한 단계구분도 경계값입니다.
# 1% · 3% · 5% · 8%를 기준으로 5개 구간을 만듭니다.
BIN_EDGES = [-float("inf"), 1, 3, 5, 8, float("inf")]

BIN_LABELS = [
    "1% 미만",
    "1% 이상 3% 미만",
    "3% 이상 5% 미만",
    "5% 이상 8% 미만",
    "8% 이상"
]

# 낮은 비율은 옅게, 높은 비율은 진하게 보이도록 색을 정했습니다.
COLOR_MAP = {
    "1% 미만": "#fff5f0",
    "1% 이상 3% 미만": "#fcbba1",
    "3% 이상 5% 미만": "#fc9272",
    "5% 이상 8% 미만": "#fb6a4a",
    "8% 이상": "#cb181d",
    "자료 없음": "#dddddd"
}


# ------------------------------------------------------------
# 4. 화면 꾸미기 CSS
# ------------------------------------------------------------

st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(135deg, #fff7fb 0%, #f7fbff 55%, #fffaf0 100%);
        }

        .title-box {
            padding: 24px 28px;
            border-radius: 24px;
            background: white;
            border: 2px solid #ffd1e6;
            box-shadow: 0 8px 24px rgba(255, 130, 180, 0.16);
            margin-bottom: 18px;
        }

        .main-title {
            font-size: 34px;
            font-weight: 900;
            color: #ff5fa2;
            margin-bottom: 6px;
        }

        .sub-title {
            font-size: 16px;
            color: #666666;
            line-height: 1.6;
        }

        .note-box {
            padding: 14px 18px;
            border-radius: 16px;
            background-color: white;
            border: 1px solid #ffe0ef;
            color: #666666;
            margin: 12px 0 18px 0;
            line-height: 1.7;
        }

        .small-note {
            color: #777777;
            font-size: 14px;
            line-height: 1.7;
        }
    </style>
    """,
    unsafe_allow_html=True
)


# ------------------------------------------------------------
# 5. 행정구역 코드 정리 함수
# ------------------------------------------------------------

def normalize_code(series, length):
    """
    행정구역 코드는 계산하는 숫자가 아니라 이름표입니다.

    예를 들어 코드 앞에 0이 있다면 숫자로 읽을 때 사라질 수 있습니다.
    그래서 문자열로 바꾼 뒤, 필요한 자리수만큼 0을 채워 줍니다.
    """

    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(length)
    )


# ------------------------------------------------------------
# 6. 인구 데이터 불러오기
# ------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_population_data():
    """
    인구 데이터를 읽고,
    가장 최신 연도의 시군구별 14~19세 인구 비율을 계산합니다.

    원본 데이터는 읍·면·동 단위입니다.
    행정동 코드 10자리 중 앞 5자리가 시군구 코드이므로,
    앞 5자리로 묶어서 시군구 단위 인구를 계산합니다.
    """

    # 필요한 열만 읽습니다.
    # '계_' 열은 남녀를 합친 인구입니다.
    # '코드'는 반드시 문자열로 읽습니다.
    raw = pd.read_csv(
        POPULATION_URL,
        compression="gzip",
        dtype={"코드": "string"},
        usecols=lambda col: col in ["연도", "코드"] or col.startswith("계_")
    )

    # 연도를 숫자로 바꾼 뒤 가장 최신 연도를 찾습니다.
    raw["연도"] = pd.to_numeric(raw["연도"], errors="coerce")
    latest_year = int(raw["연도"].max())

    # 가장 최신 연도 자료만 사용합니다.
    df = raw[raw["연도"] == latest_year].copy()

    # 행정동 코드 10자리를 문자열로 정리합니다.
    df["코드"] = normalize_code(df["코드"], 10)

    # 행정동 코드 앞 5자리가 시군구 코드입니다.
    df["시군구코드"] = df["코드"].str[:5]

    # 전체 인구를 계산할 때 쓸 '계_' 열 목록입니다.
    # 계_0세부터 계_100세 이상까지 모두 포함됩니다.
    total_cols = [col for col in df.columns if col.startswith("계_")]

    # 14~19세 열이 실제로 있는지 확인합니다.
    missing_cols = [col for col in TARGET_COLS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"인구 데이터에 필요한 열이 없습니다: {missing_cols}")

    # 인구 열을 숫자로 바꿉니다.
    # 혹시 쉼표가 들어간 값이 있어도 처리할 수 있게 쉼표를 제거합니다.
    for col in total_cols:
        df[col] = (
            df[col]
            .astype("string")
            .str.replace(",", "", regex=False)
        )
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 시군구별 14~19세 인구 합계입니다.
    target_sum = df.groupby("시군구코드")[TARGET_COLS].sum().sum(axis=1)

    # 시군구별 전체 인구 합계입니다.
    total_sum = df.groupby("시군구코드")[total_cols].sum().sum(axis=1)

    # 지도 경계 데이터와 맞출 수 있도록 '코드'라는 이름으로 시군구 코드를 저장합니다.
    result = pd.DataFrame({
        "코드": target_sum.index.astype(str),
        "14~19세 인구": target_sum.values,
        "전체 인구": total_sum.values
    })

    # 비율 = 14~19세 인구 / 전체 인구 * 100
    result["14~19세 인구 비율"] = result["14~19세 인구"] / result["전체 인구"] * 100

    return latest_year, result


# ------------------------------------------------------------
# 7. 지도 경계 GeoJSON 불러오기
# ------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_geojson_data():
    """
    전국 시군구 경계 GeoJSON을 읽습니다.

    지도와 인구 데이터는 지역 이름이 아니라
    5자리 시군구 '코드'로 연결해야 합니다.
    """

    response = requests.get(GEOJSON_URL, timeout=30)
    response.raise_for_status()

    geojson = response.json()

    rows = []

    for feature in geojson["features"]:
        props = feature.get("properties", {})

        # GeoJSON 안의 코드도 5자리 문자열로 정리합니다.
        code = str(props.get("코드", "")).strip().zfill(5)

        rows.append({
            "코드": code,
            "시도": props.get("시도", ""),
            "시군구": props.get("시군구", "")
        })

        # Plotly가 GeoJSON 속성의 코드와 데이터프레임의 코드를 맞출 수 있게 정리합니다.
        feature["properties"]["코드"] = code

    boundary_df = pd.DataFrame(rows)

    return geojson, boundary_df


# ------------------------------------------------------------
# 8. 지도용 데이터 만들기
# ------------------------------------------------------------

@st.cache_data(show_spinner=False)
def make_map_dataframe():
    """
    인구 데이터와 지도 경계 데이터를 합쳐서
    Plotly 지도에 넣을 데이터프레임을 만듭니다.
    """

    latest_year, population_df = load_population_data()
    geojson, boundary_df = load_geojson_data()

    # '남구', '중구'처럼 같은 이름이 여러 시도에 있을 수 있으므로
    # 반드시 이름이 아니라 5자리 '코드'로 합칩니다.
    map_df = boundary_df.merge(
        population_df,
        on="코드",
        how="left"
    )

    # 1%, 3%, 5%, 8% 기준으로 5단계 구간을 만듭니다.
    map_df["비율 구간"] = pd.cut(
        map_df["14~19세 인구 비율"],
        bins=BIN_EDGES,
        labels=BIN_LABELS,
        right=False
    )

    # 자료가 없는 지역이 있을 경우 범례에 '자료 없음'으로 표시합니다.
    map_df["비율 구간"] = map_df["비율 구간"].astype("object").fillna("자료 없음")

    return latest_year, geojson, map_df


# ------------------------------------------------------------
# 9. 순위표 만드는 함수
# ------------------------------------------------------------

def make_rank_table(source_df, ascending=False):
    """
    14~19세 인구 비율이 높은 곳 또는 낮은 곳 10개를 표로 만듭니다.
    """

    table = (
        source_df
        .dropna(subset=["14~19세 인구 비율"])
        .sort_values("14~19세 인구 비율", ascending=ascending)
        .head(10)
        .copy()
    )

    table.insert(0, "순위", range(1, len(table) + 1))

    return table[
        [
            "순위",
            "시도",
            "시군구",
            "코드",
            "14~19세 인구 비율",
            "14~19세 인구",
            "전체 인구",
            "비율 구간"
        ]
    ]


# ------------------------------------------------------------
# 10. 제목 표시
# ------------------------------------------------------------

st.markdown(
    """
    <div class="title-box">
        <div class="main-title">🗺️ 전국 시군구별 14~19세 인구 비율 지도</div>
        <div class="sub-title">
            가장 최신 연도의 읍·면·동 인구를 시군구 단위로 합산한 뒤,<br>
            전체 인구 중 14세부터 19세까지 인구가 차지하는 비율을 색으로 보여 줍니다.
        </div>
    </div>
    """,
    unsafe_allow_html=True
)


# ------------------------------------------------------------
# 11. 데이터 준비
# ------------------------------------------------------------

try:
    with st.spinner("데이터를 불러오고 지도를 준비하는 중이에요 🐣"):
        latest_year, geojson, map_df = make_map_dataframe()

except Exception as e:
    st.error("데이터를 불러오거나 처리하는 중 문제가 생겼습니다.")
    st.exception(e)
    st.stop()


# ------------------------------------------------------------
# 12. 요약 지표 표시
# ------------------------------------------------------------

valid_df = map_df.dropna(subset=["14~19세 인구 비율"]).copy()

national_target = valid_df["14~19세 인구"].sum()
national_total = valid_df["전체 인구"].sum()
national_rate = national_target / national_total * 100

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("사용 연도", f"{latest_year}년")

with col2:
    st.metric("시군구 수", f"{len(map_df):,}개")

with col3:
    st.metric("전국 14~19세 인구 비율", f"{national_rate:.2f}%")

with col4:
    st.metric("전국 14~19세 인구", f"{int(national_target):,}명")


st.markdown(
    """
    <div class="note-box">
        색 구간은 <b>1% · 3% · 5% · 8%</b>를 기준으로 나누었습니다.
        낮은 비율은 옅은색, 높은 비율은 진한색입니다.
    </div>
    """,
    unsafe_allow_html=True
)


# ------------------------------------------------------------
# 13. 단계구분도 그리기
# ------------------------------------------------------------

legend_order = BIN_LABELS + ["자료 없음"]

fig = px.choropleth(
    map_df,
    geojson=geojson,
    locations="코드",
    featureidkey="properties.코드",
    color="비율 구간",
    color_discrete_map=COLOR_MAP,
    category_orders={"비율 구간": legend_order},
    custom_data=[
        "시도",
        "시군구",
        "14~19세 인구 비율",
        "14~19세 인구",
        "전체 인구",
        "비율 구간"
    ]
)

# 마우스를 올렸을 때 보이는 정보입니다.
# 요청 문구의 '고령화율'은 여기에서 실제 계산값인 '14~19세 인구 비율'로 표시했습니다.
fig.update_traces(
    marker_line_color="#555555",
    marker_line_width=0.45,
    hovertemplate=(
        "<b>%{customdata[1]}</b><br>"
        "시도: %{customdata[0]}<br>"
        "14~19세 인구 비율: %{customdata[2]:.2f}%<br>"
        "14~19세 인구: %{customdata[3]:,}명<br>"
        "전체 인구: %{customdata[4]:,}명<br>"
        "비율 구간: %{customdata[5]}"
        "<extra></extra>"
    )
)

# 배경 지도 타일 없이 GeoJSON 경계만 보이게 합니다.
fig.update_geos(
    fitbounds="locations",
    visible=False
)

fig.update_layout(
    height=760,
    margin=dict(l=0, r=0, t=20, b=0),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    legend_title_text="비율 구간",
    legend=dict(
        orientation="v",
        yanchor="top",
        y=0.98,
        xanchor="left",
        x=0.01,
        bgcolor="rgba(255,255,255,0.88)",
        bordercolor="#eeeeee",
        borderwidth=1
    )
)

st.plotly_chart(
    fig,
    use_container_width=True,
    config={
        "displayModeBar": False,
        "scrollZoom": False
    }
)


# ------------------------------------------------------------
# 14. 지도 아래 순위표 표시
# ------------------------------------------------------------

st.markdown("## 📊 시군구별 14~19세 인구 비율 순위")

high_table = make_rank_table(map_df, ascending=False)
low_table = make_rank_table(map_df, ascending=True)

left_col, right_col = st.columns(2)

with left_col:
    st.markdown("### 🔥 비율 높은 곳 10개")
    st.dataframe(
        high_table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "14~19세 인구 비율": st.column_config.NumberColumn(
                "14~19세 인구 비율",
                format="%.2f%%"
            ),
            "14~19세 인구": st.column_config.NumberColumn(
                "14~19세 인구",
                format="%d명"
            ),
            "전체 인구": st.column_config.NumberColumn(
                "전체 인구",
                format="%d명"
            )
        }
    )

with right_col:
    st.markdown("### 🌱 비율 낮은 곳 10개")
    st.dataframe(
        low_table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "14~19세 인구 비율": st.column_config.NumberColumn(
                "14~19세 인구 비율",
                format="%.2f%%"
            ),
            "14~19세 인구": st.column_config.NumberColumn(
                "14~19세 인구",
                format="%d명"
            ),
            "전체 인구": st.column_config.NumberColumn(
                "전체 인구",
                format="%d명"
            )
        }
    )


# ------------------------------------------------------------
# 15. 하단 안내
# ------------------------------------------------------------

st.markdown("---")

st.markdown(
    """
    <div class="small-note">
        💡 인구 자료는 읍·면·동 단위 자료입니다.<br>
        💡 행정동 코드 10자리 중 앞 5자리를 잘라 시군구 코드로 사용했습니다.<br>
        💡 지도 경계와 인구 자료는 시군구 이름이 아니라 5자리 코드로 연결했습니다.<br>
        💡 배경 지도 타일은 사용하지 않고 GeoJSON 경계만 사용했습니다.<br>
        💡 추가로 필요한 라이브러리는 없습니다. requirements.txt에 plotly와 requests가 있으면 됩니다.
    </div>
    """,
    unsafe_allow_html=True
)
