import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import os
from datetime import datetime, timedelta
import telegram
import random
import re
import plotly.express as px # 그래프 그리기용

# --- 1. 사용자 설정 ---
# 본인의 깃허브 아이디와 저장소 이름으로 주소를 수정하세요!
# 예: https://gildong.github.io/jomashop-bot/
DASHBOARD_URL = "https://[본인아이디].github.io/[저장소이름]/"

TARGET_BRANDS = [
    {"name": "킬리안 (Kilian)", "url": "https://www.jomashop.com/kilian-fragrances.html"},
    {"name": "니샤네 (Nishane)", "url": "https://www.jomashop.com/nishane-fragrances.html"},
    {"name": "디올 (Dior)", "url": "https://www.jomashop.com/fragrances.html?manufacturer=Dior"},
    {"name": "지방시 (Givenchy)", "url": "https://www.jomashop.com/givenchy-fragrances.html"},
    {"name": "프레데릭 말", "url": "https://www.jomashop.com/frederic-malle-fragrances.html"},
    {"name": "아쿠아 디 파르마", "url": "https://www.jomashop.com/collections/fragrances/Acqua-Di-Parma-Fragrances-And-Perfumes~bWFudWZhY3R1cmVyfkFjcXVhJTIwRGklMjBQYXJtYQ"},
    {"name": "톰포드 (Tom Ford)", "url": "https://www.jomashop.com/tom-ford-fragrances.html"}
]

# --- 2. 환경 변수 및 설정 ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '') 
CHAT_ID = os.environ.get('CHAT_ID', '')
CSV_FILE = "price_history.csv" 
HTML_FILE = "index.html" # 생성될 대시보드 파일명

# --- 3. 대시보드(HTML) 생성 함수 ---
def create_dashboard_html(df):
    try:
        # 날짜 형식 변환
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
            hover_data=["brand", "price"]
        )
        
        # HTML 파일로 저장 (CDN 의존성 없이 생성)
        fig.write_html(HTML_FILE)
        print("📊 대시보드(index.html) 업데이트 완료")
        return True
    except Exception as e:
        print(f"❌ 대시보드 생성 실패: {e}")
        return False

# --- 4. 텔레그램 전송 함수 ---
async def send_telegram_alert(item, alert_type, old_price=0):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        
        if alert_type == "NEW":
            emoji = "🚨✨"
            title = "신상 입고"
            price_msg = f"💰 **${item['price']:,.0f}**"
        
        elif alert_type == "DROP":
            emoji = "🔻🔥"
            title = "가격 인하"
            diff = old_price - item['price']
            price_msg = (
                f"📉 **${old_price:,.0f} ➡️ ${item['price']:,.0f}**\n"
                f"(Save ${diff:,.0f}!)"
            )
        
        # 메시지에 대시보드 링크 추가
        msg = (
            f"{emoji} **[{item['brand']}] {title}**\n\n"
            f"📦 {item['name']}\n"
            f"{price_msg}\n\n"
            f"🔗 [구매 링크]({item['link']})\n"
            f"📊 [가격 변동 대시보드]({DASHBOARD_URL})"
        )
        
        # 이미지 전송
        if item.get('image') and item['image'].startswith('http'):
            await bot.send_photo(chat_id=CHAT_ID, photo=item['image'], caption=msg, parse_mode='Markdown')
        else:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            
        print(f"🔔 알림 전송: {item['name']}")
        
    except Exception as e:
        print(f"❌ 텔레그램 실패: {e}")

# --- 5. 크롤링 관련 함수들 ---
async def scroll_to_bottom(page):
    print("   ⬇️ 스크롤 중...")
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
                    'link': full_link, # link 통일
                    'image': img_src
                })
            except:
                continue
        
        print(f"   ✅ {len(items)}개 발견")
        return items

    except Exception as e:
        print(f"   ❌ 에러: {e}")
        return []

# --- 6. 메인 로직 ---
async def main():
    print("--- 🚀 조마샵 봇 시작 ---")
    
    # 1. 기존 데이터 로드
    if os.path.exists(CSV_FILE):
        try:
            history_df = pd.read_csv(CSV_FILE)
            history_df['date'] = pd.to_datetime(history_df['date'])
            # 최신 가격 맵 생성
            last_status = history_df.sort_values('date').groupby('sku').last()
            price_map = last_status['price'].to_dict()
            known_skus = set(history_df['sku'].unique())
            print(f"📂 기존 데이터: {len(known_skus)}개 상품")
        except:
            history_df = pd.DataFrame()
            price_map = {}
            known_skus = set()
    else:
        history_df = pd.DataFrame()
        price_map = {}
        known_skus = set()

    new_data_list = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()

        for brand in TARGET_BRANDS:
            current_items = await scrape_brand_page(page, brand)
            
            for item in current_items:
                sku = item['sku']
                price = item['price']
                new_data_list.append(item)

                # 알림 로직
                if sku not in known_skus:
                    if len(known_skus) > 0:
                        await send_telegram_alert(item, "NEW")
                        known_skus.add(sku)
                elif sku in price_map:
                    old_price = price_map[sku]
                    if old_price > 0 and price > 0 and price < old_price:
                        await send_telegram_alert(item, "DROP", old_price)
                        price_map[sku] = price 

            await asyncio.sleep(random.uniform(2, 5))

        await browser.close()

    # 2. 데이터 저장 및 대시보드 업데이트
    if new_data_list:
        new_df = pd.DataFrame(new_data_list)
        save_cols = ['date', 'brand', 'name', 'price', 'sku', 'link'] # 저장은 필요한 것만
        
        # CSV 누적 저장
        if os.path.exists(CSV_FILE):
            new_df[save_cols].to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
        else:
            new_df[save_cols].to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
            
        print(f"\n💾 데이터 저장 완료.")
        
        # ★ 대시보드 파일(index.html) 재생성 ★
        # 전체 데이터를 다시 읽어서 그래프 그리기
        full_df = pd.read_csv(CSV_FILE)
        create_dashboard_html(full_df)

    else:
        print("\n⚠️ 데이터 없음")

if __name__ == "__main__":
    asyncio.run(main())
