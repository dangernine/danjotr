import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import os
from datetime import datetime
import telegram
import random
import re
import plotly.express as px  # 그래프 생성용

# ==========================================
# [사용자 설정] 아래 주소를 본인 것으로 수정하세요!
# ==========================================
DASHBOARD_URL = "https://dangernine.github.io/danjotr/"  
# (예시: https://아이디.github.io/저장소이름/)

# 추적할 브랜드 목록
TARGET_BRANDS = [
    {"name": "킬리안 (Kilian)", "url": "https://www.jomashop.com/kilian-fragrances.html"},
    {"name": "니샤네 (Nishane)", "url": "https://www.jomashop.com/nishane-fragrances.html"},
    {"name": "디올 (Dior)", "url": "https://www.jomashop.com/fragrances.html?manufacturer=Dior"},
    {"name": "지방시 (Givenchy)", "url": "https://www.jomashop.com/givenchy-fragrances.html"},
    {"name": "프레데릭 말", "url": "https://www.jomashop.com/frederic-malle-fragrances.html"},
    {"name": "아쿠아 디 파르마", "url": "https://www.jomashop.com/collections/fragrances/Acqua-Di-Parma-Fragrances-And-Perfumes~bWFudWZhY3R1cmVyfkFjcXVhJTIwRGklMjBQYXJtYQ"},
    {"name": "톰포드 (Tom Ford)", "url": "https://www.jomashop.com/tom-ford-fragrances.html"}
]

# 환경 변수 및 파일명 설정
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
CSV_FILE = "price_history.csv"  # 데이터 저장 파일
HTML_FILE = "index.html"        # 대시보드 웹페이지 파일

# --- 1. 대시보드(HTML) 생성 함수 ---
def create_dashboard_html(df):
    try:
        # 날짜 형식 변환 및 정렬
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(by='date')

        # Plotly로 인터랙티브 그래프 생성
        fig = px.line(
            df, 
            x="date", 
            y="price", 
            color="name", 
            title="Jomashop Price History (All Brands)",
            markers=True,
            hover_data=["brand", "price"],
            template="plotly_white"
        )
        
        # 그래프 디자인 다듬기
        fig.update_layout(
            xaxis_title="Date",
            yaxis_title="Price ($)",
            legend_title="Product Name",
            hovermode="x unified"
        )
        
        # HTML 파일로 저장
        fig.write_html(HTML_FILE)
        print("📊 대시보드(index.html) 생성 완료")
        return True
    except Exception as e:
        print(f"❌ 대시보드 생성 실패: {e}")
        return False

# --- 2. 텔레그램 전송 함수 ---
async def send_telegram_alert(item, alert_type, old_price=0):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        
        if alert_type == "NEW":
            emoji = "🚨✨"
            title = "신상 입고 알림"
            price_msg = f"💰 **${item['price']:,.0f}**"
        
        elif alert_type == "DROP":
            emoji = "🔻🔥"
            title = "가격 인하 발생"
            diff = old_price - item['price']
            price_msg = (
                f"📉 **${old_price:,.0f} ➡️ ${item['price']:,.0f}**\n"
                f"(Save ${diff:,.0f}!)"
            )
        
        # 메시지 본문 (대시보드 링크 포함)
        msg = (
            f"{emoji} **[{item['brand']}] {title}**\n\n"
            f"📦 {item['name']}\n"
            f"{price_msg}\n\n"
            f"🔗 [구매 링크]({item['link']})\n"
            f"📊 [가격 변동 대시보드]({DASHBOARD_URL})"
        )
        
        # 이미지 있으면 사진 전송, 없으면 텍스트만
        if item.get('image') and item['image'].startswith('http'):
            await bot.send_photo(chat_id=CHAT_ID, photo=item['image'], caption=msg, parse_mode='Markdown')
        else:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            
        print(f"🔔 알림 전송 완료: {item['name']}")
        
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")

# --- 3. 크롤링 관련 함수 ---
async def scroll_to_bottom(page):
    print("   ⬇️ 전체 로딩을 위해 스크롤 중...")
    previous_height = await page.evaluate("document.body.scrollHeight")
    while True:
        await page.keyboard.press("End")
        await asyncio.sleep(1.5)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == previous_height:
            break
        previous_height = new_height

async def scrape_brand_page(page, brand_info):
    name = brand_info['name']
    url = brand_info['url']
    print(f"\n🔎 [{name}] 스캔 시작...")
    
    try:
        await page.goto(url, timeout=60000)
        try:
            await page.wait_for_selector("li.productItem", timeout=20000)
        except:
            print(f"   ⚠️ 상품 없음: {name}")
            return []

        await scroll_to_bottom(page)
        
        product_cards = await page.locator("li.productItem").all()
        items = []

        for card in product_cards:
            try:
                block = card.locator(".productItemBlock")
                sku = await block.get_attribute("data-sku")
                
                link_el = card.locator("a.productName-link")
                link_href = await link_el.get_attribute("href")
                full_link = f"https://www.jomashop.com{link_href}"
                
                if not sku: sku = full_link 
                title = await link_el.get_attribute("title") or await link_el.inner_text()
                
                img_el = card.locator("img.productImg").first
                img_src = await img_el.get_attribute("src")

                price = 0.0
                price_el = card.locator(".now-price")
                if await price_el.count() > 0:
                    price_text = await price_el.inner_text()
                    price = float(re.sub(r'[^0-9.]', '', price_text))

                items.append({
                    'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'brand': name,
                    'name': title,
                    'price': price,
                    'sku': sku,
                    'link': full_link,
                    'image': img_src
                })
            except:
                continue
        
        print(f"   ✅ {len(items)}개 발견")
        return items

    except Exception as e:
        print(f"   ❌ 에러 발생: {e}")
        return []

# --- 4. 메인 실행 로직 ---
async def main():
    print("--- 🚀 조마샵 봇 시작 ---")
    
    # 1. 기존 데이터 로드 (비교용)
    if os.path.exists(CSV_FILE):
        try:
            history_df = pd.read_csv(CSV_FILE)
            history_df['date'] = pd.to_datetime(history_df['date'])
            # 최신 상태 추출 (SKU별 마지막 가격)
            last_status = history_df.sort_values('date').groupby('sku').last()
            price_map = last_status['price'].to_dict()
            known_skus = set(history_df['sku'].unique())
            print(f"📂 기존 데이터: {len(known_skus)}개 상품 로드됨")
        except:
            history_df = pd.DataFrame()
            price_map = {}
            known_skus = set()
    else:
        history_df = pd.DataFrame()
        price_map = {}
        known_skus = set()

    new_data_list = []
    
    # 2. 브라우저 실행 및 크롤링
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()

        for brand in TARGET_BRANDS:
            current_items = await scrape_brand_page(page, brand)
            
            for item in current_items:
                sku = item['sku']
                price = item['price']
                
                # 수집된 데이터는 무조건 저장 리스트에 추가
                new_data_list.append(item)

                # --- 비교 및 알림 로직 ---
                if sku not in known_skus:
                    # 신상 발견 (첫 실행 아닐 때만 알림)
                    if len(known_skus) > 0:
                        await send_telegram_alert(item, "NEW")
                        known_skus.add(sku) # 중복 알림 방지
                
                elif sku in price_map:
                    old_price = price_map[sku]
                    # 가격 인하 발견
                    if old_price > 0 and price > 0 and price < old_price:
                        await send_telegram_alert(item, "DROP", old_price)
                        price_map[sku] = price # 중복 알림 방지

            # 브랜드 간 딜레이
            await asyncio.sleep(random.uniform(2, 5))

        await browser.close()

    # 3. 데이터 저장 및 대시보드 업데이트
    if new_data_list:
        new_df = pd.DataFrame(new_data_list)
        save_cols = ['date', 'brand', 'name', 'price', 'sku', 'link'] 
        
        # CSV 파일에 누적 저장 (append mode)
        if os.path.exists(CSV_FILE):
            new_df[save_cols].to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
        else:
            new_df[save_cols].to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
            
        print(f"\n💾 데이터 저장 완료.")
        
        # ★ 전체 데이터를 다시 읽어서 대시보드(HTML) 재생성
        full_df = pd.read_csv(CSV_FILE)
        create_dashboard_html(full_df)

    else:
        print("\n⚠️ 수집된 데이터가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main())
