import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="상속세 이주 손익분기 시뮬레이터", layout="wide")

st.title("🌏 상속세 이주 손익분기 시뮬레이터")
st.caption(
    "한국에 남을 때와 다른 나라로 이주할 때의 상속세를 비교하고, "
    "이주 비용까지 고려해 '얼마부터 이주가 이득인지' 계산합니다. (2026년 기준 · 단순화 모델)"
)

# ---------------- 입력값 ----------------
with st.sidebar:
    st.header("⚙️ 입력값")
    estate = st.number_input("상속 재산 (억 원)", min_value=1.0, max_value=10000.0, value=50.0, step=5.0)
    move_cost = st.number_input(
        "이주 비용 (억 원)", min_value=0.0, value=10.0, step=1.0,
        help="이사·비자·생활비 차이 등 이주에 드는 총비용 추정치",
    )
    gain_ratio = st.slider(
        "재산 중 미실현 이익 비율 (%)", 0, 100, 50,
        help="캐나다는 사망 시 자산을 판 것으로 보고, 오른 가격(이익)에 세금을 매깁니다.",
    ) / 100
    krw_per_usd = st.number_input("환율 (원/달러)", min_value=500, max_value=3000, value=1400, step=10)


# ---------------- 나라별 상속세 계산 (단위: 억 원) ----------------
def tax_korea(e):
    """한국: 일괄공제 5억 후 10~50% 누진세율 (자녀 상속, 배우자 없음 가정)"""
    t = max(0, e - 5)
    if t <= 1:
        return t * 0.10
    elif t <= 5:
        return t * 0.20 - 0.1
    elif t <= 10:
        return t * 0.30 - 0.6
    elif t <= 30:
        return t * 0.40 - 1.6
    else:
        return t * 0.50 - 4.6


def tax_usa(e):
    """미국: 1,500만 달러 면제 후 사실상 40% (연방세만)"""
    exemption = 15_000_000 * krw_per_usd / 1e8  # 억 원으로 변환
    return max(0, e - exemption) * 0.40


def tax_canada(e):
    """캐나다: 상속세 없음. 대신 사망 시 이익의 50%를 소득으로 보고 최고 약 53.5% 과세"""
    return e * gain_ratio * 0.5 * 0.535


def tax_zero(e):
    return 0.0


COUNTRIES = [
    # 이름, 지역, 지도 코드, 계산 함수, 제도 설명
    ("한국", "동아시아", "KOR", tax_korea, "상속세 10~50%"),
    ("미국", "북미", "USA", tax_usa, "연방 상속세 40% (1,500만 달러 면제)"),
    ("캐나다", "북미", "CAN", tax_canada, "상속세 없음 · 사망 시 양도소득세"),
    ("싱가포르", "동남아시아", "SGP", tax_zero, "상속세 폐지 (2008)"),
    ("호주", "오세아니아", "AUS", tax_zero, "상속세 폐지 (1979)"),
    ("뉴질랜드", "오세아니아", "NZL", tax_zero, "상속세 폐지 (1992)"),
]

rows = []
korea_tax = tax_korea(estate)
for name, region, iso, fn, rule in COUNTRIES:
    tax = fn(estate)
    saving = korea_tax - tax
    rows.append({
        "국가": name,
        "지역": region,
        "iso": iso,
        "제도": rule,
        "상속세 (억 원)": round(tax, 2),
        "실효세율 (%)": round(tax / estate * 100, 1),
        "한국 대비 절감액 (억 원)": round(saving, 2),
        "이주비 뺀 순이익 (억 원)": None if name == "한국" else round(saving - move_cost, 2),
    })
df = pd.DataFrame(rows)

# ---------------- 지역 필터 ----------------
regions = st.multiselect("🗺️ 보고 싶은 지역", df["지역"].unique().tolist(), default=df["지역"].unique().tolist())
view = df[df["지역"].isin(regions)]

# ---------------- 핵심 숫자 ----------------
c1, c2, c3 = st.columns(3)
c1.metric("한국에 남을 때 상속세", f"{korea_tax:,.1f}억 원")
c2.metric("한국 실효세율", f"{korea_tax / estate * 100:.1f}%")
others_df = df[df["국가"] != "한국"]
top = others_df["이주비 뺀 순이익 (억 원)"].max()
best_names = "·".join(others_df[others_df["이주비 뺀 순이익 (억 원)"] == top]["국가"])
c3.metric("가장 유리한 이주국", best_names, f"순이익 {top:,.1f}억 원")

# ---------------- 지도 + 막대그래프 ----------------
left, right = st.columns(2)
with left:
    st.subheader("나라별 실효세율 지도")
    fig_map = px.choropleth(
        view, locations="iso", color="실효세율 (%)", hover_name="국가",
        hover_data={"iso": False, "지역": True, "제도": True, "상속세 (억 원)": True},
        color_continuous_scale="Reds", range_color=(0, max(1, df["실효세율 (%)"].max())),
    )
    fig_map.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=380)
    st.plotly_chart(fig_map, width="stretch")
with right:
    st.subheader("나라별 상속세 비교")
    fig_bar = px.bar(
        view.sort_values("상속세 (억 원)"), x="상속세 (억 원)", y="국가", orientation="h",
        color="지역", text="상속세 (억 원)",
    )
    fig_bar.update_layout(height=380, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig_bar, width="stretch")

st.dataframe(view.drop(columns=["iso"]), width="stretch", hide_index=True)

# ---------------- 손익분기점 ----------------
st.subheader("📈 손익분기점: 재산이 얼마부터 이주가 이득일까?")
others = [c[0] for c in COUNTRIES if c[0] != "한국"]
target = st.selectbox("비교할 나라", others, index=others.index("싱가포르"))
target_fn = {c[0]: c[3] for c in COUNTRIES}[target]

max_e = max(200, int(estate * 2))
xs = list(range(1, max_e + 1))
line = pd.DataFrame({
    "재산 (억 원)": xs,
    "이주로 아끼는 세금 (억 원)": [tax_korea(x) - target_fn(x) for x in xs],
    "이주 비용 (억 원)": [move_cost] * len(xs),
})
fig_line = px.line(line, x="재산 (억 원)", y=["이주로 아끼는 세금 (억 원)", "이주 비용 (억 원)"])
fig_line.update_layout(legend_title_text="", height=380)
st.plotly_chart(fig_line, width="stretch")

break_even = next((x for x in xs if tax_korea(x) - target_fn(x) >= move_cost), None)
if break_even:
    st.success(f"**{target}**(으)로 이주하면, 상속 재산이 **약 {break_even}억 원 이상**일 때부터 아끼는 세금이 이주 비용보다 커집니다.")
else:
    st.warning(f"{max_e}억 원까지는 {target}(으)로 이주해도 이주 비용을 회수하지 못합니다.")

# ---------------- 가정과 한계 ----------------
with st.expander("📌 계산 가정과 한계 (꼭 읽어주세요)"):
    st.markdown("""
- **한국:** 현행 상속세 및 증여세법 기준. 일괄공제 5억 원 후 10~50% 누진세율. 자녀에게 상속, 배우자 없음 가정. 금융재산공제·신고세액공제 등은 생략. 정부의 유산취득세 전환 개정안은 아직 확정되지 않아 반영하지 않음.
- **미국:** 2026년 연방 상속세 면제액 1,500만 달러, 초과분 40%. 주(州) 상속세는 제외.
- **캐나다:** 상속세는 없지만 사망 시 자산을 판 것으로 보고(deemed disposition) 이익의 50%를 소득에 포함. 최고 한계세율 약 53.5%(온타리오 기준) 가정. 주거용 주택 면제 등은 생략.
- **싱가포르·호주·뉴질랜드:** 상속세 없음. 단, 호주는 상속받은 자산을 나중에 팔 때 양도소득세가 생길 수 있음.
- **공통:** 한국 국적자가 해외로 이주해도 상속인이 한국 거주자이거나 재산이 한국에 있으면 한국 상속세가 부과될 수 있음. 이 모델은 '피상속인과 재산이 모두 해외로 옮겨간 경우'를 가정한 단순 비교입니다.
- 실제 세금은 개인 상황에 따라 크게 달라지며, 이 프로그램은 교육·탐구용입니다.
""")
