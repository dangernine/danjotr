import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import os
from datetime import datetime, timedelta
import telegram
import random
import re
import plotly.express as px
import matplotlib.pyplot as plt
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

# [UI] 텔레그램 전송용 그래프 폰트 설정
plt.rcParams['axes.unicode_minus'] = False

# --- 1. 웹 대시보드(HTML) 생성 함수 ---
def create_dashboard_html(df):
    try:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(by='date')

        # 데이터프레임에 있는 컬럼만 골라서 hover_data에 넣기
        available_cols = df.columns.tolist()
        hover_cols = ["price"]
        if "brand" in available_cols:
            hover_cols.append("brand")

        fig = px.line(
            df, 
            x="date", 
            y="price", 
            color="name", 
            title="Jomashop Price History (All Brands)",
            markers=True,
            hover_data=hover_cols,
            template="plotly_white"
        )
        fig.update_layout(xaxis_title="Date", yaxis_title="Price ($)", legend_title="Product Name", hovermode="x unified")
        fig.write_html(HTML_FILE)
        print("📊 대시보드(index.html) 업데이트 완료")
    except Exception as e:
        print(f"❌ 대시보드 생성 실패: {e}")

# --- 2. 텔레그램용 그래프 생성 함수 ---
def create_static_graph(df, sku, product_name):
    # 'sku' 컬럼 호환성 처리
    if 'sku' not in df.columns:
        col_id = 'link' if 'link' in df.columns else 'url'
        if col_id not in df.columns: return None
        item_df = df[df[col_id] == sku].copy()
    else:
        item_df = df[df['sku'] == sku].copy()

    if len(item_df) < 2: return None

    item_df['date'] = pd.to_datetime(item_df['date'])
    item_df = item_df.sort_values('date')
    three_months_ago = datetime.now() - timedelta(days=90)
    item_df = item_df[item_df['date'] >= three_months_ago]

    if item_df.empty: return None

    plt.figure(figsize=(10, 5))
    plt.plot(item_df['date'], item_df['price'], marker='o', linestyle='-', color='#d62728', linewidth=2)
    plt.title(f"Price Drop: {product_name[:15]}...", fontsize=14, pad=15)
    plt.ylabel("Price ($)")
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    plt.xticks(rotation=45)

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
    if not TELEGRAM_TOKEN or not CHAT_ID: return

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
            price_msg = f"📉 **${old_price:,.0f} ➡️ ${item['price']:,.0f}**\n(Save ${diff:,.0f}!)"
        
        msg = f"{emoji} **[{item['brand']}] {title}**\n\n📦 {item['name']}\n{price_msg}\n\n🔗 [구매 링크]({item['link']})\n📊 [대시보드 보기]({DASHBOARD_URL})"
        
        if graph_path and os.path.exists(graph_path):
            await bot.send_photo(chat_id=CHAT_ID, photo=open(graph_path, 'rb'), caption=msg, parse_mode='Markdown')
            os.remove(graph_path)
        elif item.get('image') and item['image'].startswith('http'):
            await bot.send_photo(chat_id=CHAT_ID, photo=item['image'], caption=msg, parse_mode='Markdown')
        else:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            
        print(f"🔔 알림 전송 완료: {item['name']}")
    except Exception as e:
        print(f"❌ 텔레그램 실패: {e}")

# --- 4. 스크롤 함수 ---
async def scroll_to_bottom(page):
    for _ in range(5): 
        await page.keyboard.press("End")
        await asyncio.sleep(1)

# --- 5. 브랜드 페이지 크롤링 (팝업 제거 기능 추가됨) ---
async def scrape_brand_page(page, brand_info):
    name = brand_info['name']
    url = brand_info['url']
    print(f"\n🔎 [{name}] 스캔 시작...")
    
    all_items = []
    
    try:
        await page.goto(url, timeout=60000)
        
        page_num = 1
        while True:
            print(f"   📄 Page {page_num} 스캔 중...")
            try:
                await page.wait_for_selector("li.productItem", timeout=10000)
            except:
                print("      ⚠️ 상품 없음 (종료)")
                break
            
            # [팝업 제거 시도] 페이지 로딩 후 팝업이 있으면 삭제
            try:
                await page.evaluate("""
                    var popups = document.querySelectorAll('[id^="ltkpopup"]');
                    popups.forEach(p => p.remove());
                """)
            except:
                pass

            await scroll_to_bottom(page)
            
            product_cards = await page.locator("li.productItem").all()
            for card in product_cards:
                try:
                    block = card.locator(".productItemBlock")
                    sku = await block.get_attribute("data-sku")
                    
                    link_el = card.locator("a.productName-link")
                    link_href = await link_el.get_attribute("href")
                    full_link = f"https://www.jomashop.com{link_href}"
                    
                    if not sku: sku = full_link 
                    title = await link_el.get_attribute("title") or await link_el.inner_text()
                    title = title.replace(",", " ").replace('"', '').strip()

                    img_el = card.locator("img.productImg").first
                    img_src = await img_el.get_attribute("src")

                    price = 0.0
                    price_el = card.locator(".now-price")
                    if await price_el.count() > 0:
                        price_text = await price_el.inner_text()
                        price = float(re.sub(r'[^0-9.]', '', price_text))

                    all_items.append({
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
            
            # [다음 페이지 이동] 
            next_btn = page.locator("li.pagination-next a")
            if await next_btn.count() > 0 and await next_btn.is_visible():
                print("      👉 다음 페이지로 이동...")
                
                # [핵심 수정] 팝업이 가려도 강제로 클릭하게 함 (force=True)
                try:
                    await next_btn.click(force=True)
                except Exception as e:
                    print(f"      ⚠️ 다음 페이지 클릭 실패: {e}")
                    break
                
                await page.wait_for_timeout(3000)
                page_num += 1
            else:
                print("      ✅ 마지막 페이지 도달")
                break 

        print(f"   🎉 총 {len(all_items)}개 상품 발견")
        return all_items

    except Exception as e:
        print(f"   ❌ 에러 발생: {e}")
        return []

# --- 6. 메인 실행 ---
async def main():
    print("--- 🚀 조마샵 봇 시작 ---")
    
    if os.path.exists(CSV_FILE):
        try:
            history_df = pd.read_csv(CSV_FILE, on_bad_lines='skip')
            history_df['date'] = pd.to_datetime(history_df['date'])
            
            # 구형 데이터 호환성 체크
            if 'sku' not in history_df.columns:
                print("⚠️ 구형 CSV 포맷 감지: 호환 모드로 로드")
                if 'link' in history_df.columns: history_df['sku'] = history_df['link']
                elif 'url' in history_df.columns: history_df['sku'] = history_df['url']
            
            last_status = history_df.sort_values('date').groupby('sku').last()
            price_map = last_status['price'].to_dict()
            known_skus = set(history_df['sku'].unique())
            print(f"📂 기존 데이터: {len(known_skus)}개 로드됨")
        except Exception as e:
            print(f"⚠️ CSV 초기화 (이유: {e})")
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

                if sku not in known_skus:
                    if len(known_skus) > 0:
                        await send_telegram_alert(item, "NEW")
                        known_skus.add(sku)
                elif sku in price_map:
                    old_price = price_map[sku]
                    if old_price > 0 and price > 0 and price < old_price:
                        temp_history = pd.concat([history_df, pd.DataFrame([item])], ignore_index=True)
                        graph_file = create_static_graph(temp_history, sku, item['name'])
                        await send_telegram_alert(item, "DROP", old_price, graph_path=graph_file)
                        price_map[sku] = price 

            await asyncio.sleep(random.uniform(2, 5))

        await browser.close()

    if new_data_list:
        new_df = pd.DataFrame(new_data_list)
        save_cols = ['date', 'brand', 'name', 'price', 'sku', 'link'] 
        
        if os.path.exists(CSV_FILE):
            new_df[save_cols].to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
        else:
            new_df[save_cols].to_csv(CSV_FILE, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
            
        print(f"\n💾 데이터 저장 완료.")
        
        try:
            full_df = pd.read_csv(CSV_FILE, on_bad_lines='skip')
            create_dashboard_html(full_df)
        except Exception as e:
            print(f"❌ 대시보드 로드 실패: {e}")
    else:
        print("\n⚠️ 수집된 데이터가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main())
