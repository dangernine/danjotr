import streamlit as st
import pandas as pd
import plotly.express as px
import os

# 페이지 설정
st.set_page_config(page_title="Jomashop Price Tracker", layout="wide")

# 제목 및 설명
st.title("🛍️ Jomashop Price Tracker Dashboard")
st.markdown("조마샵 향수 가격 변동 내역을 실시간으로 확인하세요.")

# CSV 파일 로드
CSV_FILE = "price_history.csv"

if os.path.exists(CSV_FILE):
    try:
        # [핵심 수정 1] 데이터 읽기 시 에러 방지 옵션 추가
        df = pd.read_csv(CSV_FILE, on_bad_lines='skip')
        
        # 날짜 변환 및 정렬
        df['date'] = pd.to_datetime(df['date'], errors='coerce') # 날짜 에러나면 NaT로 처리
        df = df.dropna(subset=['date']) # 날짜 없는 행 제거
        df = df.sort_values(by='date')

        # [핵심 수정 2] 'brand' 컬럼이 없을 경우 대비 (호환성)
        if 'brand' not in df.columns:
            df['brand'] = 'Unknown' # 임시 브랜드명 부여

        # 사이드바: 브랜드 필터
        st.sidebar.header("Filter Options")
        all_brands = sorted(df['brand'].unique().astype(str))
        selected_brands = st.sidebar.multiselect("Select Brands", all_brands, default=all_brands)

        # 선택된 브랜드만 필터링
        filtered_df = df[df['brand'].isin(selected_brands)]

        if filtered_df.empty:
            st.warning("선택한 브랜드의 데이터가 없습니다.")
        else:
            # --- 메인 지표 (KPI) ---
            col1, col2, col3 = st.columns(3)
            
            # SKU 기준 총 상품 수 (SKU 없으면 Name이나 Link 사용)
            id_col = 'sku' if 'sku' in df.columns else 'link'
            total_items = filtered_df[id_col].nunique()
            
            with col1:
                st.metric("Total Products Tracked", f"{total_items} items")
            
            with col2:
                # 가장 최근 데이터 기준 평균 가격
                latest_date = filtered_df['date'].max()
                latest_data = filtered_df[filtered_df['date'] == latest_date]
                avg_price = latest_data['price'].mean()
                st.metric("Average Price (Latest)", f"${avg_price:,.0f}")
            
            with col3:
                st.metric("Last Update", latest_date.strftime('%Y-%m-%d %H:%M'))

            st.divider()

            # --- 탭 구성 ---
            tab1, tab2 = st.tabs(["📈 Price History Graph", "📋 Raw Data"])

            with tab1:
                st.subheader("Price Trends Over Time")
                
                # 상품 선택
                all_products = sorted(filtered_df['name'].unique().astype(str))
                # 기본 선택은 최대 5개까지만
                default_selection = all_products[:5] if len(all_products) > 0 else []
                
                selected_products = st.multiselect("Select Products to Compare", all_products, default=default_selection)
                
                if selected_products:
                    chart_data = filtered_df[filtered_df['name'].isin(selected_products)]
                    
                    # [핵심 수정 3] Plotly 호버 데이터 동적 설정
                    hover_data_cols = {"price": ":.2f"}
                    if 'brand' in chart_data.columns:
                        hover_data_cols["brand"] = True
                    
                    # Plotly 인터랙티브 그래프 생성
                    fig = px.line(chart_data, x="date", y="price", color="name", 
                                  markers=True, title="Price History by Product",
                                  hover_data=hover_data_cols,
                                  template="plotly_white")
                    
                    fig.update_layout(xaxis_title="Date", yaxis_title="Price ($)", hovermode="x unified")
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("비교할 상품을 선택해주세요.")

            with tab2:
                st.subheader("Recent Data Logs")
                # 최신순 정렬해서 보여주기
                st.dataframe(filtered_df.sort_values(by='date', ascending=False), use_container_width=True)

    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
        st.write("CSV 파일 형식이 손상되었을 수 있습니다. 관리자에게 문의하세요.")

else:
    st.warning("아직 데이터 파일(price_history.csv)이 생성되지 않았습니다. 봇이 한 번 실행될 때까지 기다려주세요.")
