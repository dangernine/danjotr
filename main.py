import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import os
from datetime import datetime, timedelta
import telegram
import random
import re
import plotly.express as px  # 웹 대시보드용
import matplotlib.pyplot as plt  # 텔레그램 전송용 그래프
import matplotlib.dates as mdates
import csv

# ==========================================
# [사용자 설정] 본인의 깃허브 페이지 주소로 수정하세요!
# ==========================================
DASHBOARD_URL = "https://dangernine.github.io/danjotr/"

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

# 환경 변수 및 파일명
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
CSV_FILE = "price_history.csv"
HTML_FILE = "index.html"

# [UI] 텔레그램 전송용 그래프 폰트 설정 (마이너스 깨짐 방지)
plt.rcParams['axes.unicode_minus'] = False

# --- 1. 웹 대시보드(HTML) 생성 함수 (Plotly) ---
def create_dashboard_html(df):
    try:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(by='date')

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
        
        fig.update_layout(
            xaxis_title="Date",
            yaxis_title="Price ($)",
            legend_title="Product Name",
            hovermode="x unified"
        )
        
        fig.write_html(HTML_FILE)
        print("📊 대시보드(index.html) 업데이트 완료")
    except Exception as e:
        print(f"❌ 대시보드 생성 실패: {e}")

# --- 2. 텔레그램용 그래프 생성 함수 (Matplotlib) ---
def create_static_graph(df, sku, product_name):
    # 해당 SKU 데이터만 필터링
    item_df = df[df['sku'] == sku].copy()
    
    # 데이터가 너무 적으면 그래프 안 만듦
    if len(item_df) < 2:
        return None

    item_df['date'] = pd.to_datetime(item_df['date'])
    item_df = item_df.sort_values('date')

    # 최근 3개월치만
    three_months_ago = datetime.now() - timedelta(days=90)
    item_df = item_df[item_df['date'] >= three_months_ago]

    if item_df.empty:
        return None

    # 그래프 그리기
    plt.figure(figsize=(10, 5))
    plt.plot(item_df['date'], item_df['price'], marker='o', linestyle='-', color='#d62728', linewidth=2)
    
    plt.title(f"Price Drop Alert: {product_name[:15]}...", fontsize=14, pad=15)
    plt.ylabel("Price ($)")
    plt.grid(True, linestyle='--', alpha=0.6)
    
    # 날짜 포맷
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    plt.xticks(rotation=45)

    # 마지막 가격 표시
    last_date = item_df.iloc[-1]['date']
    last_price = item_df.iloc[-1]['price']
    plt.annotate(f'${last_price:,.0f}', xy=(last_date, last_price), xytext=(0, 10), 
                 textcoords='offset points', ha='center', color='red', fontweight='bold')

    filename = f"temp_graph_{random.randint(1000,9999)}.png"
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()
    return filename

# --- 3. 텔레그램 전송 함수 ---
async def send_telegram_alert(item, alert_type, old_price=0, graph_path=None):
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
        
        msg = (
            f"{emoji} **[{item['brand']}] {title}**\n\n"
            f"📦 {item['name']}\n"
            f"{price_msg}\n\n"
            f"🔗 [구매 링크]({item['link']})\n"
            f"📊 [가격 변동 대시보드]({DASHBOARD_URL})"
        )
        
        # 1순위: 가격 인하 그래프가 있으면 그래프 전송
        if graph_path and os.path.exists(graph_path):
            await bot.send_photo(chat_id=CHAT_ID, photo=open(graph_path, 'rb'), caption=msg, parse_mode='Markdown')
            os.remove(graph_path) # 전송 후 삭제
            
        # 2순위: 신상인 경우 썸네일 이미지 전송
        elif item.get('image') and item['image'].startswith('http'):
            await bot.send_photo(chat_id=CHAT_ID, photo=item['image'], caption=msg, parse_mode='Markdown')
            
        # 3순위: 텍스트만 전송
        else:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            
        print(f"🔔 알림 전송 완료: {item['name']}")
        
    except Exception as e:
        print(f"❌ 텔레그램 실패: {e}")

# --- 4. 크롤링 관련 함수 ---
async def scroll_to_bottom(page):
    print("   ⬇️ 스크롤 시작 (최대 15회 제한)...")
    for _ in range(15):
        previous_height = await page.evaluate("document.body.scrollHeight")
        await page.keyboard.press("End")
        await asyncio.sleep(2)
        
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == previous_height:
            print("   ✅ 페이지 끝 도달")
            break
    print("   ⏹️ 스크롤 종료")

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
                
                # ★ 핵심 수정: CSV 에러 방지를 위해 콤마를 제거
                title = title.replace(",", " ").replace('"', '').strip()

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

# --- 5. 메인 로직 ---
async def main():
    print("--- 🚀 조마샵 봇 시작 ---")
    
    # 1. 기존 데이터 로드 (CSV 에러 방지 옵션 적용)
    if os.path.exists(CSV_FILE):
        try:
            # on_bad_lines='skip': 깨진 줄은 무시
            history_df = pd.read_csv(CSV_FILE, on_bad_lines='skip')
            history_df['date'] = pd.to_datetime(history_df['date'])
            
            # 최신 가격 상태 추출
            last_status = history_df.sort_values('date').groupby('sku').last()
            price_map = last_status['price'].to_dict()
            known_skus = set(history_df['sku'].unique())
            print(f"📂 기존 데이터: {len(known_skus)}개 상품 로드됨")
        except Exception as e:
            print(f"⚠️ CSV 로드 에러 (초기화): {e}")
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

                # --- 알림 로직 ---
                # 1. 신규 상품 (New): 그래프 없음, 이미지 전송
                if sku not in known_skus:
                    if len(known_skus) > 0:
                        await send_telegram_alert(item, "NEW")
                        known_skus.add(sku)
                
                # 2. 가격 인하 (Drop): 그래프 생성 및 전송
                elif sku in price_map:
                    old_price = price_map[sku]
                    if old_price > 0 and price > 0 and price < old_price:
                        # 그래프 생성 (과거 데이터 + 현재 데이터)
                        temp_history = pd.concat([history_df, pd.DataFrame([item])], ignore_index=True)
                        graph_file = create_static_graph(temp_history, sku, item['name'])
                        
                        await send_telegram_alert(item, "DROP", old_price, graph_path=graph_file)
                        price_map[sku] = price 

            await asyncio.sleep(random.uniform(2, 5))

        await browser.close()

    # 2. 데이터 저장 (CSV 안전 저장 옵션 적용)
    if new_data_list:
        new_df = pd.DataFrame(new_data_list)
        save_cols = ['date', 'brand', 'name', 'price', 'sku', 'link'] 
        
        # quoting=csv.QUOTE_NONNUMERIC: 모든 문자열에 따옴표를 붙여 콤마 오류 원천 차단
        if os.path.exists(CSV_FILE):
            new_df[save_cols].to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
        else:
            new_df[save_cols].to_csv(CSV_FILE, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            
        print(f"\n💾 데이터 저장 완료.")
        
        # 전체 데이터로 대시보드(HTML) 재생성
        try:
            full_df = pd.read_csv(CSV_FILE, on_bad_lines='skip')
            create_dashboard_html(full_df)
        except Exception as e:
            print(f"❌ 대시보드 로드 실패: {e}")

    else:
        print("\n⚠️ 수집된 데이터가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main())
