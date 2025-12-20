import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import os
from datetime import datetime
import telegram
import random
import re

# GitHub 설정(Secrets)에서 아이디와 비번을 몰래 가져오는 코드
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['CHAT_ID']

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

CSV_FILE = "price_history.csv"

async def send_telegram_message(message):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

async def get_price_via_playwright(page, url):
    try:
        await page.goto(url, timeout=60000)
        try:
            await page.wait_for_selector(".now-price", timeout=20000)
        except:
            pass 

        content = await page.content()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, 'html.parser')

        price_tag = soup.find('div', class_='now-price')
        if not price_tag: price_tag = soup.find('span', class_='now-price')
        if not price_tag: price_tag = soup.find('span', class_='final-price')
        if not price_tag: price_tag = soup.find('span', itemprop="price")

        if price_tag:
            raw_text = price_tag.get_text(strip=True)
            price_text = re.sub(r'[^0-9.]', '', raw_text)
            return float(price_text)
        else:
            return None
    except Exception as e:
        print(f"에러: {e}")
        return None

async def main():
    print("--- GitHub Actions 스크래퍼 시작 ---")
    today = datetime.now().strftime('%Y-%m-%d')

    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
    else:
        df = pd.DataFrame(columns=['date', 'name', 'price', 'url'])

    new_rows = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for item in TARGETS:
            name = item['name']
            url = item['url']
            print(f"검색: {name}")

            current_price = await get_price_via_playwright(page, url)

            if current_price is None:
                continue

            item_history = df[df['name'] == name]
            msg = ""
            if not item_history.empty:
                min_price = item_history['price'].min()
                if current_price < min_price:
                    msg = f"🚨 [역대가 갱신!] {name}\n현재: {current_price:,.0f}\n(이전 최저: {min_price:,.0f})\n{url}"
            else:
                msg = f"✅ [추적 시작] {name}\n현재: {current_price:,.0f}\n{url}"

            if msg:
                await send_telegram_message(msg)

            new_rows.append({'date': today, 'name': name, 'price': current_price, 'url': url})
            await asyncio.sleep(random.uniform(5, 10))

        await browser.close()

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        df.to_csv(CSV_FILE, index=False)

if __name__ == "__main__":
    asyncio.run(main())
