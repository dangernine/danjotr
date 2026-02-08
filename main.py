import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import os
from datetime import datetime, timedelta
import telegram
import random
import re
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- 1. 사용자 설정 ---
TARGET_BRANDS = [
    {
        "name": "킬리안 (Kilian)",
        "url": "https://www.jomashop.com/kilian-fragrances.html"
    },
    {
        "name": "니샤네 (Nishane)",
        "url": "https://www.jomashop.com/nishane-fragrances.html"
    },
    {
        "name": "디올 (Dior)",
        "url": "https://www.jomashop.com/fragrances.html?manufacturer=Dior"
    },
    {
        "name": "지방시 (Givenchy)",
        "url": "https://www.jomashop.com/givenchy-fragrances.html"
    },
    {
        "name": "프레데릭 말 (Frederic Malle)",
        "url": "https://www.jomashop.com/frederic-malle-fragrances.html"
    },
    {
        "name": "아쿠아 디 파르마",
        "url": "https://www.jomashop.com/collections/fragrances/Acqua-Di-Parma-Fragrances-And-Perfumes~bWFudWZhY3R1cmVyfkFjcXVhJTIwRGklMjBQYXJtYQ"
    },
    {
        "name": "톰포드 (Tom Ford)",
        "url": "https://www.jomashop.com/tom-ford-fragrances.html"
    }
]

# --- 2. 환경 변수 및 설정 ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '') 
CHAT_ID = os.environ.get('CHAT_ID', '')
CSV_FILE = "price_history.csv" # 데이터가 계속 누적되는 파일

# [UI] 한글 폰트 설정 (서버 환경에 따라 폰트가 없을 수 있으므로 영문 기본값 사용 권장 or 설치 필요)
# 리눅스 서버(Github Actions) 등에서는 한글 폰트가 없어 깨질 수 있습니다. 
# 안전하게 영문으로 표기하거나, 폰트 설치가 필요합니다. 여기선 기본 설정을 따릅니다.
plt.rcParams['axes.unicode_minus'] = False 

# --- 3. 그래프 생성 함수 ---
def create_price_graph(df, sku, product_name):
    # 해당 SKU의 데이터만 필터링
    item_df = df[df['sku'] == sku].copy()
    
    # 데이터가 2개 미만이면 그래프 의미가 없으므로 None 반환 (신규 상품 등)
    if len(item_df) < 2:
        return None

    item_df['date'] = pd.to_datetime(item_df['date'])
    item_df = item_df.sort_values('date')

    # 최근 3개월 데이터만 보기
    three_months_ago = datetime.now() - timedelta(days=90)
    item_df = item_df[item_df['date'] >= three_months_ago]

    if item_df.empty:
        return None

    # 그래프 그리기
    plt.figure(figsize=(10, 5))
    plt.plot(item_df['date'], item_df['price'], marker='o', linestyle='-', color='#1f77b4', linewidth=2)
    
    # 디자인
    plt.title(f"Price History: {product_name[:20]}...", fontsize=14, pad=15)
    plt.ylabel("Price ($)")
    plt.grid(True, linestyle='--', alpha=0.6)
    
    # X축 날짜 포맷팅
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(item_df)//5)))
    plt.xticks(rotation=45)

    # 마지막 가격 표시
    last_date = item_df.iloc[-1]['date']
    last_price = item_df.iloc[-1]['price']
    plt.annotate(f'${last_price:,.0f}', xy=(last_date, last_price), xytext=(0, 10), 
                 textcoords='offset points', ha='center', color='red', fontweight='bold')

    # 저장
    filename = f"graph_{sku}.png"
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()
    return filename

# --- 4. 텔레그램 전송 함수 ---
async def send_telegram_alert(item, alert_type, photo_path=None, old_price=0):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        
        # 메시지 구성
        if alert_type == "NEW":
            emoji = "🚨✨"
            title = "NEW ARRIVAL"
            desc = f"New item detected!"
        elif alert_type == "DROP":
            emoji = "🔻🔥"
            title = "PRICE DROP"
            diff = old_price - item['price']
            desc = f"Price dropped by ${diff:,.0f}!"
        
        msg = (
            f"{emoji} **[{item['brand']}] {title}**\n"
            f"{desc}\n\n"
            f"📦 {item['name']}\n"
            f"💰 **Now: ${item['price']:,.0f}**"
        )
        if alert_type == "DROP":
             msg += f" (Was: ${old_price:,.0f})"
        
        msg += f"\n\n🔗 [Link to Product]({item['link']})"

        # 1순위: 그래프 사진 전송
        if photo_path and os.path.exists(photo_path):
            await bot.send_photo(chat_id=CHAT_ID, photo=open(photo_path, 'rb'), caption=msg, parse_mode='Markdown')
            # 전송 후 그래프 파일 삭제 (청소)
            os.remove(photo_path)
            
        # 2순위: 그래프 없으면(신규상품) 상품 썸네일 전송
        elif item.get('image') and item['image'].startswith('http'):
            await bot.send_photo(chat_id=CHAT_ID, photo=item['image'], caption=msg, parse_mode='Markdown')
            
        # 3순위: 텍스트만 전송
        else:
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            
        print(f"🔔 알림 전송 완료: {item['name']}")
        
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")

# --- 5. 크롤링 및 스크롤 함수 ---
async def scroll_to_bottom(page):
    print("   ⬇️ 상품 로딩 중 (Scroll)...")
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
            await page.wait_for_selector("li.productItem", timeout=15000)
        except:
            print(f"   ⚠️ {name}: 상품 없음")
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

                title = await link_el.get_attribute("title")
                if not title: title = await link_el.inner_text()

                img_el = card.locator("img.productImg").first
                img_src = await img_el.get_attribute("src")

                price = 0.0
                price_el = card.locator(".now-price")
                if await price_el.count() > 0:
                    price_text = await price_el.inner_text()
                    price = float(re.sub(r'[^0-9.]', '', price_text))

                items.append({
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'brand': name,
                    'name': title,
                    'price': price,
                    'sku': sku,
                    'url': full_link,
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
    print("--- 🚀 스마트 그래프 트래커 시작 ---")
    
    # 1. 히스토리 데이터 로드
    if os.path.exists(CSV_FILE):
        try:
            history_df = pd.read_csv(CSV_FILE)
            # 최근 데이터만 추출하여 빠른 비교용 딕셔너리 생성 (Last Price Map)
            # 날짜순 정렬 후 SKU별 마지막 가격 가져오기
            history_df['date'] = pd.to_datetime(history_df['date'])
            last_status = history_df.sort_values('date').groupby('sku').last()
            
            # SKU : Price 딕셔너리
            price_map = last_status['price'].to_dict()
            known_skus = set(history_df['sku'].unique())
            
            print(f"📂 기록된 상품 수: {len(known_skus)}개")
        except Exception as e:
            print(f"⚠️ CSV 로드 에러 (새로 시작): {e}")
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
        context = await browser.new_context(
             user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
             viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        for brand in TARGET_BRANDS:
            current_items = await scrape_brand_page(page, brand)
            
            for item in current_items:
                sku = item['sku']
                price = item['price']
                
                # 수집된 데이터는 무조건 리스트에 추가 (히스토리 누적을 위해)
                new_data_list.append(item)

                # --- 알림 로직 ---
                
                # 1. 신상 (History에 SKU가 아예 없음)
                if sku not in known_skus:
                    if len(known_skus) > 0: # 첫 실행이 아닐 때만
                        # 신상은 그래프 그릴 데이터가 없으므로 이미지(썸네일) 전송
                        await send_telegram_alert(item, "NEW")
                        known_skus.add(sku) # 중복 알림 방지
                
                # 2. 가격 변동 (기존 가격보다 쌈)
                elif sku in price_map:
                    old_price = price_map[sku]
                    if old_price > 0 and price > 0 and price < old_price:
                        # 가격 인하는 그래프 생성 시도
                        # 현재 데이터를 포함한 임시 DF 생성
                        temp_history = pd.concat([history_df, pd.DataFrame([item])], ignore_index=True)
                        graph_file = create_price_graph(temp_history, sku, item['name'])
                        
                        await send_telegram_alert(item, "DROP", photo_path=graph_file, old_price=old_price)
                        price_map[sku] = price # 중복 알림 방지 업데이트

            await asyncio.sleep(random.uniform(2, 5))

        await browser.close()

    # 데이터 저장 (누적)
    if new_data_list:
        new_df = pd.DataFrame(new_data_list)
        # 필요한 컬럼만 저장 (이미지는 파일 용량을 위해 CSV에 저장 안 하거나, 필요하면 포함)
        save_cols = ['date', 'brand', 'name', 'price', 'sku', 'url']
        
        # 기존 파일이 있으면 헤더 없이 추가(append), 없으면 새로 생성
        if os.path.exists(CSV_FILE):
            new_df[save_cols].to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
        else:
            new_df[save_cols].to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
            
        print(f"\n💾 {len(new_df)}개 데이터 저장 완료. (History 누적됨)")
    else:
        print("\n⚠️ 수집된 데이터가 없습니다.")

if __name__ == "__main__":
    asyncio.run(main())
