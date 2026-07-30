# main.py
# ------------------------------------------------------------
# 전국 시군구별 14~19세 인구 비율 단계구분도 Streamlit 앱
# ------------------------------------------------------------
# 사용하는 외부 라이브러리:
# - streamlit: 웹앱 화면 만들기
# - pandas: 표 데이터 처리
# - plotly: 지도 그리기
# - requests: GeoJSON 경계 파일 가져오기
# ------------------------------------------------------------

import streamlit as st
import pandas as pd
import plotly.express as px
import requests


# ------------------------------------------------------------
# 1. 기본 설정
# ------------------------------------------------------------

st.set_page_config(
    page_title="전국 14~19세 인구 비율 지도",
    page_icon="🗺️",
    layout="wide"
)

POPULATION_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEOJSON_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"

# 14세부터 19세까지를 대상 나이로 사용합니다.
TARGET_AGES = list(range(14, 20))
TARGET_COLS = [f"계_{age}세" for age in TARGET_AGES]

# 단계구분도 구간입니다.
# right=False 이므로 19는 두 번째 구간에 들어갑니다.
BIN_EDGES = [-float("inf"), 5, 10, 15, 20, float("inf")]
BIN_LABELS = [
    "5% 미만",
    "5% 이상 10% 미만",
    "10% 이상 15% 미만",
    "15% 이상 20% 미만",
    "20% 이상"
]

# 낮은 비율은 옅게, 높은 비율은 진하게 보이도록 색을 지정합니다.
COLOR_MAP = {
    "5% 미만": "#fff5f0",
    "5% 이상 10% 미만": "#fcbba1",
    "10% 이상 15% 미만": "#fc9272",
    "15% 이상 20% 미만": "#fb6a4a",
    "20% 이상": "#cb181d",
    "자료 없음": "#dddddd"
}


# ------------------------------------------------------------
# 2. 귀여운 화면 스타일
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

        .small-note {
            color: #777777;
            font-size: 14px;
        }
    </style>
    """,
    unsafe_allow_html=True
)


# ------------------------------------------------------------
# 3. 코드 정리 함수
# ------------------------------------------------------------

def normalize_code(series, length):
    """
    행정구역 코드는 계산할 숫자가 아니라 이름표입니다.
    그래서 반드시 글자로 다루고, 필요한 자리수만큼 0을 채워 줍니다.
    """
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(length)
    )


# ------------------------------------------------------------
# 4. 데이터 불러오기 및 가공
# ------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_population_data():
    """
    인구 데이터를 읽고,
    가장 최신 연도의 시군구별 14~19세 인구 비율을 계산합니다.
    """

    # CSV에는 남/여/계 열이 모두 있지만, 여기서는 남녀 합계인 '계_' 열만 읽습니다.
    # '코드'는 행정동 코드 10자리이므로 반드시 글자로 읽습니다.
    raw = pd.read_csv(
        POPULATION_URL,
        compression="gzip",
        dtype={"코드": "string"},
        usecols=lambda col: col in ["연도", "코드"] or col.startswith("계_")
    )

    # 연도는 최신 연도를 찾기 위해 숫자로 바꿉니다.
    raw["연도"] = pd.to_numeric(raw["연도"], errors="coerce")

    latest_year = int(raw["연도"].max())

    # 최신 연도만 남깁니다.
    df = raw[raw["연도"] == latest_year].copy()

    # 행정동 코드 10자리를 글자로 정리합니다.
    df["코드"] = normalize_code(df["코드"], 10)

    # 앞 5자리가 시군구 코드입니다.
    df["시군구코드"] = df["코드"].str[:5]

    # 전체 인구 계산에 사용할 '계_' 열 목록입니다.
    total_cols = [col for col in df.columns if col.startswith("계_")]

    # 필요한 나이 열이 모두 있는지 확인합니다.
    missing_cols = [col for col in TARGET_COLS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"인구 데이터에 필요한 열이 없습니다: {missing_cols}")

    # 인구 열을 숫자로 바꿉니다.
    # 혹시 쉼표가 들어간 값이 있어도 처리할 수 있게 문자열 치환을 한 번 해 줍니다.
    for col in total_cols:
        df[col] = (
            df[col]
            .astype("string")
            .str.replace(",", "", regex=False)
        )
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 행정동 단위 자료를 시군구 단위로 합칩니다.
    grouped = df.groupby("시군구코드", as_index=False).agg(
        대상인구=(TARGET_COLS[0], "sum")
    )

    # 여러 열을 합쳐야 하므로 groupby 뒤에 따로 계산합니다.
    target_sum = df.groupby("시군구코드")[TARGET_COLS].sum().sum(axis=1)
    total_sum = df.groupby("시군구코드")[total_cols].sum().sum(axis=1)

    result = pd.DataFrame({
        "코드": target_sum.index.astype(str),
        "대상인구": target_sum.values,
        "전체인구": total_sum.values
    })

    # 비율 = 14~19세 인구 / 전체 인구 * 100
    result["비율"] = result["대상인구"] / result["전체인구"] * 100

    return latest_year, result


@st.cache_data(show_spinner=False)
def load_geojson_data():
    """
    시군구 경계 GeoJSON을 읽습니다.
    지도와 인구 데이터는 이름이 아니라 5자리 '코드'로 맞춥니다.
    """

    response = requests.get(GEOJSON_URL, timeout=30)
    response.raise_for_status()
    geojson = response.json()

    rows = []

    for feature in geojson["features"]:
        props = feature.get("properties", {})

        rows.append({
            "코드": str(props.get("코드", "")).strip().zfill(5),
            "시도": props.get("시도", ""),
            "시군구": props.get("시군구", "")
        })

        # GeoJSON 안의 코드도 혹시 모를 상황에 대비해 5자리 글자로 정리합니다.
        feature["properties"]["코드"] = str(props.get("코드", "")).strip().zfill(5)

    boundary_df = pd.DataFrame(rows)

    return geojson, boundary_df


@st.cache_data(show_spinner=False)
def make_map_dataframe():
    """
    인구 데이터와 경계 데이터를 코드 기준으로 합칩니다.
    """

    latest_year, population_df = load_population_data()
    geojson, boundary_df = load_geojson_data()

    # 이름이 같은 시군구가 여러 시도에 있을 수 있으므로 반드시 '코드'로 합칩니다.
    map_df = boundary_df.merge(
        population_df,
        on="코드",
        how="left"
    )

    # 구간 나누기
    map_df["구간"] = pd.cut(
        map_df["비율"],
        bins=BIN_EDGES,
        labels=BIN_LABELS,
        right=False
    )

    # 자료가 없는 지역이 있다면 회색으로 보이도록 '자료 없음'으로 표시합니다.
    map_df["구간"] = map_df["구간"].astype("object").fillna("자료 없음")

    return latest_year, geojson, map_df


# ------------------------------------------------------------
# 5. 화면 제목
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
# 6. 데이터 준비
# ------------------------------------------------------------

try:
    with st.spinner("데이터를 불러오고 지도를 준비하는 중이에요 🐣"):
        latest_year, geojson, map_df = make_map_dataframe()

except Exception as e:
    st.error("데이터를 불러오거나 처리하는 중 문제가 생겼습니다.")
    st.exception(e)
    st.stop()


# ------------------------------------------------------------
# 7. 간단한 요약 정보
# ------------------------------------------------------------

valid_df = map_df.dropna(subset=["비율"]).copy()

col_a, col_b, col_c, col_d = st.columns(4)

with col_a:
    st.metric("사용 연도", f"{latest_year}년")

with col_b:
    st.metric("시군구 수", f"{len(map_df):,}개")

with col_c:
    national_target = valid_df["대상인구"].sum()
    national_total = valid_df["전체인구"].sum()
    national_rate = national_target / national_total * 100
    st.metric("전국 14~19세 비율", f"{national_rate:.2f}%")

with col_d:
    st.metric("전국 14~19세 인구", f"{int(national_target):,}명")

st.caption(
    "구간 경계값은 요청하신 기준인 19% · 23% · 28% · 38%를 그대로 사용했습니다."
)


# ------------------------------------------------------------
# 8. Plotly 단계구분도 만들기
# ------------------------------------------------------------

legend_order = BIN_LABELS + ["자료 없음"]

fig = px.choropleth(
    map_df,
    geojson=geojson,
    locations="코드",
    featureidkey="properties.코드",
    color="구간",
    color_discrete_map=COLOR_MAP,
    category_orders={"구간": legend_order},
    custom_data=[
        "시도",
        "시군구",
        "비율",
        "대상인구",
        "전체인구",
        "구간"
    ]
)

# 마우스를 올렸을 때 보이는 내용입니다.
fig.update_traces(
    marker_line_color="#555555",
    marker_line_width=0.45,
    hovertemplate=(
        "<b>%{customdata[1]}</b><br>"
        "시도: %{customdata[0]}<br>"
        "14~19세 인구 비율: %{customdata[2]:.2f}%<br>"
        "14~19세 인구: %{customdata[3]:,}명<br>"
        "전체 인구: %{customdata[4]:,}명<br>"
        "구간: %{customdata[5]}"
        "<extra></extra>"
    )
)

# 배경 지도 타일 없이 행정구역 경계만 보이게 합니다.
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
        bgcolor="rgba(255,255,255,0.85)",
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
# 9. 지도 아래 표 만들기
# ------------------------------------------------------------

st.markdown("## 📊 시군구별 14~19세 인구 비율 순위")

def make_rank_table(source_df, ascending=False):
    """
    높은 곳 또는 낮은 곳 10개를 표로 만들기 위한 함수입니다.
    """

    table = (
        source_df
        .dropna(subset=["비율"])
        .sort_values("비율", ascending=ascending)
        .head(10)
        .copy()
    )

    table.insert(0, "순위", range(1, len(table) + 1))

    table = table.rename(columns={
        "비율": "14~19세 인구 비율(%)",
        "대상인구": "14~19세 인구",
        "전체인구": "전체 인구"
    })

    return table[
        [
            "순위",
            "시도",
            "시군구",
            "코드",
            "14~19세 인구 비율(%)",
            "14~19세 인구",
            "전체 인구",
            "구간"
        ]
    ]


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
            "14~19세 인구 비율(%)": st.column_config.NumberColumn(
                "14~19세 인구 비율(%)",
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
            "14~19세 인구 비율(%)": st.column_config.NumberColumn(
                "14~19세 인구 비율(%)",
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
# 10. 하단 안내
# ------------------------------------------------------------

st.markdown("---")
st.markdown(
    """
    <div class="small-note">
        💡 인구 자료는 읍·면·동 단위에서 시군구 코드 앞 5자리로 묶어 계산했습니다.<br>
        💡 지도 경계와 인구 자료는 지역 이름이 아니라 5자리 시군구 코드로 연결했습니다.<br>
        💡 이 앱은 배경 지도 타일 없이 GeoJSON 경계만 사용합니다.
    </div>
    """,
    unsafe_allow_html=True
)
