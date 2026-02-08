import streamlit as st
import pandas as pd
import plotly.express as px
import os

# 페이지 설정
st.set_page_config(page_title="Jomashop Price Tracker", layout="wide")

# 제목
st.title("🛍️ Jomashop Price Tracker Dashboard")
st.markdown("조마샵 향수 가격 변동 내역을 실시간으로 확인하세요.")

# CSV 파일 로드
CSV_FILE = "price_history.csv"

if os.path.exists(CSV_FILE):
    df = pd.read_csv(CSV_FILE)
    
    # 날짜 변환 및 정렬
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(by='date')

    # 사이드바: 브랜드 필터
    st.sidebar.header("Filter Options")
    all_brands = df['brand'].unique()
    selected_brands = st.sidebar.multiselect("Select Brands", all_brands, default=all_brands)

    # 선택된 브랜드만 필터링
    filtered_df = df[df['brand'].isin(selected_brands)]

    # --- 메인 지표 (KPI) ---
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Products Tracked", f"{df['sku'].nunique()} items")
    with col2:
        # 가장 최근 데이터 기준 평균 가격
        latest_date = df['date'].max()
        avg_price = df[df['date'] == latest_date]['price'].mean()
        st.metric("Average Price (Latest)", f"${avg_price:,.0f}")
    with col3:
        st.metric("Last Update", latest_date.strftime('%Y-%m-%d %H:%M'))

    st.divider()

    # --- 탭 구성 ---
    tab1, tab2 = st.tabs(["📈 Price History Graph", "📋 Raw Data"])

    with tab1:
        st.subheader("Price Trends Over Time")
        
        # 상품 선택 (너무 많으면 그래프가 복잡하므로)
        all_products = filtered_df['name'].unique()
        selected_products = st.multiselect("Select Products to Compare", all_products, default=all_products[:5])
        
        if selected_products:
            chart_data = filtered_df[filtered_df['name'].isin(selected_products)]
            
            # Plotly 인터랙티브 그래프 생성
            fig = px.line(chart_data, x="date", y="price", color="name", 
                          markers=True, title="Price History by Product",
                          hover_data={"price": ":.2f", "brand": True})
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("비교할 상품을 선택해주세요.")

    with tab2:
        st.subheader("Recent Data Logs")
        # 최신순 정렬해서 보여주기
        st.dataframe(filtered_df.sort_values(by='date', ascending=False), use_container_width=True)

else:
    st.warning("아직 데이터가 수집되지 않았습니다. 봇이 실행될 때까지 기다려주세요.")
