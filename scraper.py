import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import os
from datetime import datetime, timedelta
import telegram
import random
import re
import matplotlib.pyplot as plt

# --- 1. 사용자 설정 (반드시 수정해주세요!) ---

DASHBOARD_URL = "https://dangernine.github.io/danjotr/"

# --- 2. 환경 변수 및 파일 설정 ---
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
CSV_FILE = "price_history.csv"

# [UI] 한글 폰트 설정 (GitHub Actions 서버용: NanumGothic)
plt.rcParams['font.family'] = 'NanumGothic'
plt.rcParams['axes.unicode_minus'] = False # 마이너스 기호 깨짐 방지

# --- 3. 추적할 상품 리스트 ---
TARGETS = [
    {
        "name": "톰포드 오드우드",
        "url": "https://www.jomashop.com/tom-ford-unisex-oud-wood-edp-spray-3-4-oz-fragrances-888066024099.html"
    },
    {
        "name": "프말 제라늄",
        "url": "https://www.jomashop.com/frederic-malle-mens-geranium-pour-monsieur-edp-spray-3-4-oz-fragrances-3700135003828.html"
    }
]

# --- 4. 텔레그램 전송 함수 (사진 포함) ---
async def send_telegram_photo(message, photo_path=None):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        if photo_path and os.path.exists(photo_path):
            # 사진과 텍스트를 같이 전송
            await bot.send_photo(chat_id=CHAT_ID, photo=open(photo_path, 'rb'), caption=message)
        else:
            # 사진이 없으면 텍스트만 전송
            await bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

# --- 5. 그래프 생성 함수 ---
def create_price_graph(df, product_name):
    # 해당 제품 데이터만 필터링
    item_df = df[df['name'] == product_name].copy()
    item_df['date'] = pd.to_datetime(item_df['date'])
    item_df = item_df.sort_values('date')

    # 최근 3개월 데이터만 사용 (너무 길면 그래프가 안 예쁨)
    three_months_ago = datetime.now() - timedelta(days=90)
    item_df = item_df[item_df['date'] >= three_months_ago]

    if item_df.empty:
        return None

    # 그래프 그리기
    plt.figure(figsize=(10, 5))
    plt.plot(item_df['date'], item_df['price'], marker='o', linestyle='-', color='#1f77b4', label='Price')
    
    # 디자인
    plt.title(f"{product_name} Price Trend (3 Months)", fontsize=15, pad=20)
    plt.xlabel("Date")
    plt.ylabel("Price ($)")
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    
    # 마지막 가격에 빨간 글씨로 가격 표시
    last_date = item_df.iloc[-1]['date']
    last_price = item_df.iloc[-1]['price']
    plt.annotate(f'${last_price:,.0f}', xy=(last_date, last_price), xytext=(0, 10), 
                 textcoords='offset points', ha='center', fontsize=12, fontweight='bold', color='red')

    # 이미지 파일로 저장
    filename = "price_graph.png"
    plt.tight_layout()
    plt.savefig(filename)
    plt.close() # 메모리 해제
    return filename

# --- 6. 조마샵 가격 크롤링 함수 (Playwright) ---
async def get_price_via_playwright(page, url):
    try:
        # 60초 대기 (조마샵 로딩 고려)
        await page.goto(url, timeout=60000)
        
        # 가격 태그가 뜰 때까지 최대 20초 대기 (못 찾아도 패스)
        try:
            await page.wait_for_selector(".now-price", timeout=20000)
        except:
            pass 
        
        content = await page.content()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, 'html.parser')

        # 가격 태그 찾기 (여러 패턴 시도)
        price_tag = soup.find('div', class_='now-price')
        if not price_tag: price_tag = soup.find('span', class_='now-price')
        if not price_tag: price_tag = soup.find('span', class_='final-price')
        if not price_tag: price_tag = soup.find('span', itemprop="price")

        if price_tag:
            raw_text = price_tag.get_text(strip=True)
            # 숫자와 점(.)만 남기고 모두 제거
            price_text = re.sub(r'[^0-9.]', '', raw_text)
            return float(price_text)
        else:
            return None
    except Exception as e:
        print(f"크롤링 에러: {e}")
        return None

# --- 7. 메인 로직 ---
async def main():
    print("--- 스마트 프라이스 트래커 시작 ---")
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 기존 데이터 로드
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
    else:
        df = pd.DataFrame(columns=['date', 'name', 'price', 'url'])

    new_rows = []

    # Playwright 브라우저 시작
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # 봇 탐지 회피용 User-Agent
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for item in TARGETS:
            name = item['name']
            url = item['url']
            print(f"검색 중: {name}")
            
            current_price = await get_price_via_playwright(page, url)
            
            if current_price is None:
                print(f"❌ 실패: {name}")
                continue

            # --- 스마트 알림 로직 시작 ---
            item_history = df[df['name'] == name].copy()
            msg = ""
            alert_level = 0 # 0:조용함, 1:변동, 2:한달최저, 3:역대가

            if not item_history.empty:
                # 날짜 형식 변환
                item_history['date'] = pd.to_datetime(item_history['date'])
                
                # 1. 역대가 계산
                all_time_min = item_history['price'].min()
                
                # 2. 한 달 내 최저가 계산
                one_month_ago = datetime.now() - timedelta(days=30)
                month_df = item_history[item_history['date'] >= one_month_ago]
                month_min = month_df['price'].min() if not month_df.empty else current_price
                
                # 3. 직전 가격 (어제 가격)
                last_record = item_history.iloc[-1]['price']

                # 비교 로직
                if current_price < all_time_min:
                    alert_level = 3
                    msg = f"🚨🚨 [역대가 갱신!] {name}\n\n📉 현재: ${current_price:,.0f}\n(기존 역대가: ${all_time_min:,.0f})\n\n지금이 기회입니다! 🔥"
                
                elif current_price < month_min:
                    alert_level = 2
                    msg = f"⭐ [한 달 내 최저가] {name}\n\n📉 현재: ${current_price:,.0f}\n(한 달 최저: ${month_min:,.0f})\n\n관심 있게 지켜보세요."
                
                elif current_price != last_record:
                    alert_level = 1
                    diff = current_price - last_record
                    icon = "🔻" if diff < 0 else "🔺"
                    msg = f"{icon} [가격 변동] {name}\n현재: ${current_price:,.0f} ({diff:+,.0f})"
                
            else:
                # 기록이 아예 없는 신규 항목인 경우
                alert_level = 1
                msg = f"✅ [추적 시작] {name}\n현재: ${current_price:,.0f}"

            # --- 알림 전송 (조건 충족 시) ---
            if alert_level > 0:
                # 그래프 생성을 위해 현재 데이터를 임시로 합침
                temp_row = pd.DataFrame([{'date': today, 'name': name, 'price': current_price}])
                temp_df = pd.concat([df, temp_row], ignore_index=True)
                
                # 그래프 생성
                photo_file = create_price_graph(temp_df, name)
                
                # 메시지 완성 (대시보드 링크 추가)
                final_msg = msg + f"\n\n🔗 제품: {url}\n📊 대시보드: {DASHBOARD_URL}"
                
                # 사진과 함께 전송
                await send_telegram_photo(final_msg, photo_file)
            
            # --- 데이터 저장 준비 ---
            new_rows.append({'date': today, 'name': name, 'price': current_price, 'url': url})
            
            # 봇 차단 방지 딜레이 (5~10초)
            await asyncio.sleep(random.uniform(5, 10))

        await browser.close()

    # 최종 CSV 파일 저장
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        df.to_csv(CSV_FILE, index=False)
        print("데이터 저장 완료.")

if __name__ == "__main__":
    asyncio.run(main())
