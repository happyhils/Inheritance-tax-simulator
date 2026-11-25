import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="상속세 이주 손익분기 시뮬레이터", layout="wide")

st.title("🌏 상속세 국가 간 이주 손익분기 시뮬레이터")
st.caption(
    "재산 구성(부동산·주식·사업체·예금)을 넣으면 26개국의 상속세를 비교하고, "
    "이주 비용까지 고려해 '재산이 얼마부터 이주가 이득인지' 계산합니다. (2026년 11월 기준 · 교육용 단순화 모델)"
)

# =====================================================================
# 1. 나라별 데이터 불러오기 (countries.csv — 나라를 추가하려면 이 파일에 한 줄만 추가)
# =====================================================================
@st.cache_data
def load_countries():
    return pd.read_csv("countries.csv")

countries = load_countries()

# =====================================================================
# 2. 입력값
# =====================================================================
with st.sidebar:
    st.header("💰 재산 구성 (억 원)")
    real_estate = st.number_input("부동산", min_value=0.0, value=30.0, step=1.0)
    stocks = st.number_input("주식·금융투자", min_value=0.0, value=15.0, step=1.0)
    business = st.number_input("사업체 지분 (가업)", min_value=0.0, value=0.0, step=1.0)
    cash = st.number_input("예금·현금", min_value=0.0, value=5.0, step=1.0)

    st.header("👨‍👩‍👧 가족·이주 조건")
    heirs = st.slider("상속받을 자녀 수", 1, 5, 2)
    move_cost = st.number_input(
        "이주 비용 (억 원)", min_value=0.0, value=10.0, step=1.0,
        help="이사·비자·세무 자문·생활비 차이 등 이주에 드는 총비용 추정치",
    )

    st.header("⚙️ 세부 조건")
    gain_ratio = st.slider(
        "자산 가격 중 '오른 부분(미실현 이익)' 비율 (%)", 0, 100, 50,
        help="캐나다는 사망 시 자산을 판 것으로 보고, 오른 가격에 세금을 매깁니다.",
    ) / 100
    home_exempt = st.checkbox("부동산은 거주 주택 (캐나다 주택 면제 적용)", value=True)
    family_biz = st.checkbox("한국 가업상속공제 요건 충족", value=False,
                             help="중소·중견기업을 10년 이상 경영 등 요건을 모두 충족한 경우")
    biz_years = st.select_slider("가업 경영 기간", options=["10년 이상", "20년 이상", "30년 이상"],
                                 disabled=not family_biz)

total = real_estate + stocks + business + cash
if total <= 0:
    st.warning("왼쪽에서 재산을 입력해 주세요.")
    st.stop()

# =====================================================================
# 3. 상속세 계산 함수
# =====================================================================
def parse_brackets(text):
    """'0:0.10;100:0.20' → [(0, 0.10), (100, 0.20)]"""
    if pd.isna(text) or text == "":
        return []
    return [tuple(map(float, part.split(":"))) for part in str(text).split(";")]


def bracket_tax(amount, brackets, mode):
    """누진세 계산. marginal = 구간별로 나눠 계산, whole = 해당 구간 세율을 전체에 적용(독일식)"""
    if amount <= 0 or not brackets:
        return 0.0
    if mode == "whole":
        rate = brackets[0][1]
        for limit, r in brackets:
            if amount > limit:
                rate = r
        return amount * rate
    tax = 0.0
    for i, (start, rate) in enumerate(brackets):
        end = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")
        if amount > start:
            tax += (min(amount, end) - start) * rate
    return tax


def korea_tax(re, st_, biz, csh):
    """한국 상속세 (단위: 원). 자녀만 상속, 배우자 없음 가정."""
    won = 1e8
    estate = (re + st_ + biz + csh) * won
    # 인적공제: 일괄공제 5억 vs (기초공제 2억 + 자녀 1인당 5천만) 중 큰 쪽
    personal = max(5e8, 2e8 + 0.5e8 * heirs)
    # 금융재산공제: 2천만 이하 전액, 1억 이하 2천만, 초과 시 20% (최대 2억)
    fin = (st_ + csh) * won
    fin_ded = fin if fin <= 2e7 else (2e7 if fin <= 1e8 else min(fin * 0.2, 2e8))
    # 가업상속공제
    biz_ded = 0.0
    if family_biz:
        limit = {"10년 이상": 300e8, "20년 이상": 400e8, "30년 이상": 600e8}[biz_years]
        biz_ded = min(biz * won, limit)
    taxable = max(0, estate - personal - fin_ded - biz_ded)
    row = countries[countries["iso3"] == "KOR"].iloc[0]
    tax = bracket_tax(taxable, parse_brackets(row["세율구간"]), "marginal")
    return tax * 0.97  # 신고세액공제 3%


def country_tax_krw(row, re, st_, biz, csh):
    """한 나라의 상속세를 원화로 계산 (단위: 억 원)"""
    method = row["계산방식"]
    if method == "none":
        return 0.0
    if method == "korea":
        return korea_tax(re, st_, biz, csh) / 1e8

    fx = row["원화환율"]                     # 현지통화 1단위 = 몇 원
    estate = (re + st_ + biz + csh) * 1e8 / fx  # 현지통화로 환산
    brackets = parse_brackets(row["세율구간"])
    mode = row["세율적용"]

    if method == "canada":
        gain_assets = (st_ + biz + (0 if home_exempt else re)) * 1e8 / fx
        tax = gain_assets * gain_ratio * 0.5 * 0.5353
    elif method == "estate":      # 유산 전체에서 공제 후 과세 (미국·대만·필리핀)
        tax = bracket_tax(estate - row["공제액"], brackets, mode)
    elif method == "uk":          # 영국: 기본공제 + 주택공제(200만 파운드 초과 시 감소)
        home_value = re * 1e8 / fx
        rnrb = max(0, 175000 - max(0, estate - 2_000_000) / 2)
        rnrb = min(rnrb, home_value)
        tax = bracket_tax(estate - row["공제액"] - rnrb, brackets, mode)
    elif method == "per_heir":    # 자녀 1인당 몫에 각각 공제·과세 (프랑스·독일 등)
        share = estate / heirs
        tax = heirs * bracket_tax(share - row["상속인당공제"], brackets, mode)
    elif method == "split":       # 일본: 전체 공제 후 법정상속분으로 나눠 누진세
        exempt = row["공제액"] + row["상속인당공제"] * heirs
        taxable = max(0, estate - exempt)
        tax = heirs * bracket_tax(taxable / heirs, brackets, mode)
    else:
        tax = 0.0
    return tax * fx / 1e8


def all_taxes(scale=1.0):
    return [
        country_tax_krw(r, real_estate * scale, stocks * scale, business * scale, cash * scale)
        for _, r in countries.iterrows()
    ]

# =====================================================================
# 4. 결과 표 만들기
# =====================================================================
df = countries[["iso3", "국가", "지역", "제도요약"]].copy()
df["상속세 (억 원)"] = [round(t, 2) for t in all_taxes()]
df["실효세율 (%)"] = (df["상속세 (억 원)"] / total * 100).round(1)
korea_tax_now = float(df.loc[df["iso3"] == "KOR", "상속세 (억 원)"].iloc[0])
df["한국 대비 절감액 (억 원)"] = (korea_tax_now - df["상속세 (억 원)"]).round(2)
df["이주비 뺀 순이익 (억 원)"] = (df["한국 대비 절감액 (억 원)"] - move_cost).round(2)
df.loc[df["iso3"] == "KOR", ["한국 대비 절감액 (억 원)", "이주비 뺀 순이익 (억 원)"]] = None

# 지역 필터
all_regions = df["지역"].unique().tolist()
regions = st.multiselect("🗺️ 보고 싶은 지역", all_regions, default=all_regions)
view = df[df["지역"].isin(regions)]

# 핵심 숫자
c1, c2, c3, c4 = st.columns(4)
c1.metric("총 상속재산", f"{total:,.0f}억 원")
c2.metric("한국에 남을 때 상속세", f"{korea_tax_now:,.1f}억 원", f"실효세율 {korea_tax_now / total * 100:.1f}%", delta_color="off")
others = df[df["iso3"] != "KOR"]
top = others["이주비 뺀 순이익 (억 원)"].max()
c3.metric("이주 시 최대 순이익", f"{top:,.1f}억 원")
c4.metric("이주가 이득인 나라 수", f"{(others['이주비 뺀 순이익 (억 원)'] > 0).sum()} / {len(others)}개국")

# 지도 + 막대그래프
left, right = st.columns(2)
with left:
    st.subheader("나라별 실효세율 지도")
    fig_map = px.choropleth(
        view, locations="iso3", color="실효세율 (%)", hover_name="국가",
        hover_data={"iso3": False, "지역": True, "상속세 (억 원)": True},
        color_continuous_scale="Reds", range_color=(0, max(1, df["실효세율 (%)"].max())),
    )
    fig_map.update_geos(showcountries=True, countrycolor="lightgray")
    fig_map.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=420)
    st.plotly_chart(fig_map, width="stretch")
    st.caption("※ 싱가포르·홍콩처럼 작은 나라는 지도에서 잘 안 보이니 오른쪽 그래프를 참고하세요.")
with right:
    st.subheader("나라별 상속세 비교")
    fig_bar = px.bar(
        view.sort_values("상속세 (억 원)"), x="상속세 (억 원)", y="국가", orientation="h",
        color="지역", hover_data=["제도요약"],
    )
    fig_bar.update_layout(height=420 + 12 * max(0, len(view) - 15), margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig_bar, width="stretch")

# 지역별 평균
st.subheader("지역별 평균 실효세율")
region_avg = view.groupby("지역", as_index=False)["실효세율 (%)"].mean().round(1).sort_values("실효세율 (%)", ascending=False)
st.plotly_chart(px.bar(region_avg, x="지역", y="실효세율 (%)", text="실효세율 (%)", color="지역"), width="stretch")

st.subheader("상세 결과")
st.dataframe(view.drop(columns=["iso3"]).sort_values("상속세 (억 원)", ascending=False),
             width="stretch", hide_index=True)

# =====================================================================
# 5. 손익분기점
# =====================================================================
st.subheader("📈 손익분기점: 재산이 얼마부터 이주가 이득일까?")
st.caption("지금 입력한 재산 구성 비율은 그대로 두고, 전체 재산 규모만 키워가며 계산합니다.")
target_name = st.selectbox("비교할 나라", others["국가"].tolist(), index=others["국가"].tolist().index("싱가포르"))
target_row = countries[countries["국가"] == target_name].iloc[0]
korea_row = countries[countries["iso3"] == "KOR"].iloc[0]

max_total = max(300, int(total * 3))
xs = list(range(1, max_total + 1))
saving = []
for x in xs:
    s = x / total
    args = (real_estate * s, stocks * s, business * s, cash * s)
    saving.append(country_tax_krw(korea_row, *args) - country_tax_krw(target_row, *args))

line = pd.DataFrame({"총 재산 (억 원)": xs, "이주로 아끼는 세금 (억 원)": saving, "이주 비용 (억 원)": [move_cost] * len(xs)})
fig_line = px.line(line, x="총 재산 (억 원)", y=["이주로 아끼는 세금 (억 원)", "이주 비용 (억 원)"])
fig_line.update_layout(legend_title_text="", height=380)
st.plotly_chart(fig_line, width="stretch")

break_even = next((x for x, sv in zip(xs, saving) if sv >= move_cost), None)
if break_even:
    st.success(f"**{target_name}**(으)로 이주하면, 총 재산이 **약 {break_even}억 원 이상**일 때부터 아끼는 세금이 이주 비용({move_cost:g}억 원)보다 커집니다.")
else:
    st.warning(f"총 재산 {max_total}억 원까지는 {target_name}(으)로 이주해도 이주 비용을 회수하지 못합니다.")

# =====================================================================
# 6. 데이터·가정·출처
# =====================================================================
with st.expander("📚 나라별 상속세 구조 데이터와 출처"):
    st.dataframe(countries[["국가", "지역", "통화", "원화환율", "제도요약", "출처"]],
                 width="stretch", hide_index=True,
                 column_config={"출처": st.column_config.LinkColumn("출처")})
    st.caption("원화환율은 2026년 11월 중순 기준 근사치입니다. countries.csv 파일에서 수정할 수 있습니다.")

with st.expander("📌 계산 가정과 한계 (꼭 읽어주세요)"):
    st.markdown("""
- **공통 가정:** 피상속인과 재산이 모두 해당 나라로 옮겨갔고, 자녀만 상속받으며(배우자 없음) 재산을 똑같이 나눈다고 가정했습니다. 실제로는 한국 국적자가 이주해도 상속인이 한국 거주자이거나 재산이 한국에 있으면 한국 상속세가 부과될 수 있고, 출국 후 일정 기간 동안 이전 거주국 세금이 계속 적용되는 나라도 있습니다.
- **한국:** 현행 상속세 및 증여세법 기준(10~50%). 일괄공제(또는 기초+자녀공제), 금융재산공제, 가업상속공제, 신고세액공제 3% 반영. 부동산은 시가로 평가한다고 가정(실제로는 기준시가 등으로 낮게 평가될 수 있음). 2026년 정부 개편안(유산취득세 전환, 가업상속공제 개편 등)은 아직 확정되지 않아 반영하지 않았습니다.
- **미국:** 연방 유산세만 계산(주 상속세 제외). 면제액 초과분에 사실상 40%.
- **영국:** 주택공제는 부동산을 자녀에게 물려주는 본인 주택으로 가정. 사업자산 공제(BPR) 등은 제외.
- **독일:** 구간 세율을 과세표준 전체에 적용하는 방식 반영(구간 경계의 완화 규정은 제외). 사업자산 감면 제외.
- **일본:** 법정상속인 수 = 자녀 수로 가정.
- **캐나다:** 상속세 대신 사망 시 양도소득세. 이익의 50%를 소득에 포함하고 최고 한계세율(온타리오 약 53.5%) 적용.
- **환율:** 고정 근사치 사용. 환율이 바뀌면 면제액의 원화 가치도 달라집니다.
- 실제 세금은 개인 상황에 따라 크게 달라지며, 이 프로그램은 교육·탐구용입니다.
""")
