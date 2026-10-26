import calendar
import hashlib
import html
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT = os.environ.get('TELEGRAM_CHAT_ID', '@wsn247').strip()
STATE = Path('seen.json')
MAX_POSTS = int(os.getenv('MAX_POSTS_PER_RUN', '35'))

# Mixed-language feeds. Headlines are not machine-translated; Russian feeds are prioritized.
FEEDS = {
    'Спорт — Google Новости (RU)': 'https://news.google.com/rss/headlines/section/topic/SPORTS?hl=ru&gl=RU&ceid=RU:ru',
    'Футбол — Google Новости': 'https://news.google.com/rss/search?q=%D1%84%D1%83%D1%82%D0%B1%D0%BE%D0%BB&hl=ru&gl=RU&ceid=RU:ru',
    'Бокс и MMA — Google Новости': 'https://news.google.com/rss/search?q=%D0%B1%D0%BE%D0%BA%D1%81%20OR%20UFC%20OR%20MMA&hl=ru&gl=RU&ceid=RU:ru',
    'Баскетбол — Google Новости': 'https://news.google.com/rss/search?q=NBA%20OR%20%D0%B1%D0%B0%D1%81%D0%BA%D0%B5%D1%82%D0%B1%D0%BE%D0%BB&hl=ru&gl=RU&ceid=RU:ru',
    'Теннис — Google Новости': 'https://news.google.com/rss/search?q=ATP%20OR%20WTA%20OR%20%D1%82%D0%B5%D0%BD%D0%BD%D0%B8%D1%81&hl=ru&gl=RU&ceid=RU:ru',
    'Хоккей — Google Новости': 'https://news.google.com/rss/search?q=NHL%20OR%20%D1%85%D0%BE%D0%BA%D0%BA%D0%B5%D0%B9&hl=ru&gl=RU&ceid=RU:ru',
    'Автоспорт — Google Новости': 'https://news.google.com/rss/search?q=Formula%201%20OR%20%D0%A4%D0%BE%D1%80%D0%BC%D1%83%D0%BB%D0%B0%201&hl=ru&gl=RU&ceid=RU:ru',
    'Другие виды спорта — Google Новости': 'https://news.google.com/rss/search?q=%D0%B2%D0%BE%D0%BB%D0%B5%D0%B9%D0%B1%D0%BE%D0%BB%20OR%20%D0%B1%D0%BE%D1%80%D1%8C%D0%B1%D0%B0%20OR%20%D0%BB%D0%B5%D0%B3%D0%BA%D0%B0%D1%8F%20%D0%B0%D1%82%D0%BB%D0%B5%D1%82%D0%B8%D0%BA%D0%B0&hl=ru&gl=RU&ceid=RU:ru',
    'BBC Sport': 'https://feeds.bbci.co.uk/sport/rss.xml',
    'ESPN': 'https://www.espn.com/espn/rss/news',
}


def load_seen():
    try:
        data = json.loads(STATE.read_text('utf-8'))
        return dict(data.get('items', {}))
    except (FileNotFoundError, ValueError, TypeError):
        return {}


def item_id(item):
    # De-duplicate repeated syndication of the exact same title; links may differ.
    title = ' '.join(item['title'].casefold().split())
    return hashlib.sha256(title.encode('utf-8')).hexdigest()


def fetch():
    records = []
    for source, url in FEEDS.items():
        try:
            response = requests.get(url, headers={'User-Agent': 'WSN247 RSS reader/1.0'}, timeout=18)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if not parsed.entries:
                print(f'No entries: {source}')
            for entry in parsed.entries[:55]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '').strip()
                if not title or not link:
                    continue
                struct = entry.get('published_parsed') or entry.get('updated_parsed')
                published = int(calendar.timegm(struct)) if struct else int(time.time())
                records.append({'title': title, 'link': link, 'source': source, 'published': published})
        except Exception as exc:
            print(f'Feed failed: {source}: {exc}')
    unique = {}
    for row in records:
        key = item_id(row)
        if key not in unique or row['published'] < unique[key]['published']:
            unique[key] = row
    return sorted(unique.items(), key=lambda row: row[1]['published'])


def send(article):
    title = html.escape(article['title'][:600])
    label = html.escape(article['source'])
    link = html.escape(article['link'], quote=True)
    message = f'🏆 <b>{title}</b>\n\n🗞 {label}\n🔗 <a href="{link}">Источник</a>\n\n@wsn247'
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    for attempt in range(4):
        try:
            response = requests.post(url, json={
            'chat_id': CHAT, 'text': message, 'parse_mode': 'HTML',
            'disable_web_page_preview': False,
            }, timeout=25)
        except requests.RequestException:
            raise RuntimeError('Telegram connection failed; delivery status unknown') from None
        if response.status_code == 429:
            delay = response.json().get('parameters', {}).get('retry_after', 15)
            time.sleep(min(int(delay) + 1, 90))
            continue
        if response.status_code != 200:
            raise RuntimeError(f'Telegram returned HTTP {response.status_code}; check bot permissions and secret')
        data = response.json()
        if not data.get('ok'):
            raise RuntimeError(f'Telegram API: {data}')
        return
    raise RuntimeError('Telegram rate limit exceeded')


def main():
    if not TOKEN:
        sys.exit('Missing TELEGRAM_BOT_TOKEN in GitHub Actions secrets')
    articles = fetch()
    if not articles:
        sys.exit('No RSS items fetched; leaving previous state unchanged')
    seen = load_seen()
    now = int(time.time())
    if not STATE.exists():
        # Mark the currently known entries as read so the first run does not flood the channel.
        seen = {key: now for key, _ in articles}
        print(f'Initialized {len(seen)} articles; new posts will appear on later runs.')
    else:
        # Only accept fairly recent stories, to avoid old/undated feed backlog.
        queued = [(key, item) for key, item in articles if key not in seen and item['published'] >= now - 86400]
        for key, item in queued[:MAX_POSTS]:
            send(item)
            seen[key] = now
            STATE.write_text(json.dumps({'items': seen}, ensure_ascii=False, indent=2), encoding='utf-8')
            print('Posted:', item['title'][:100])
            time.sleep(1.2)
        print(f'Posted {min(len(queued), MAX_POSTS)} new items; {max(0, len(queued)-MAX_POSTS)} pending')
    seen = {key: ts for key, ts in seen.items() if ts >= now - 10 * 86400}
    STATE.write_text(json.dumps({'items': seen}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
