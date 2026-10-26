import os
from pathlib import Path
import requests

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT = '@wsn247'
TITLE = 'WSN 24/7 | Мировой спорт'
DESCRIPTION = ('Мировой спорт в одной ленте 🏆\n'
    'Футбол • Бокс и MMA • Баскетбол • Теннис • Хоккей • Формула-1\n'
    'Свежие заголовки и ссылки на источники. Автоматические обновления.\n'
    'Следи за игрой вместе с WSN 24/7.')
WELCOME = ('🏆 <b>WSN 24/7 — мировой спорт в одной ленте</b>\n\n'
    '⚽ Футбол\n🥊 Бокс и MMA\n🏀 Баскетбол\n🎾 Теннис\n🏒 Хоккей\n🏎 Формула-1 и другие виды спорта\n\n'
    'Здесь — свежие спортивные заголовки и ссылки на первоисточники. '
    'Проверяем ленты каждые 10 минут; время публикации зависит от источников и расписания запусков.\n\n'
    '🗞 В каждом сообщении есть ссылка «Источник», где можно прочитать материал полностью. '
    'Некоторые заголовки публикуются на английском языке.\n\n'
    '📌 Новости публикует автоматический бот. Сообщения источников могут обновляться.\n\n'
    '<b>Подписывайся и следи за игрой вместе с нами!</b>\n@wsn247')

def api(method, data=None, files=None):
    try:
        response = requests.post(f'https://api.telegram.org/bot{TOKEN}/{method}', data=data or {}, files=files, timeout=40)
    except requests.RequestException:
        raise SystemExit(f'{method}: connection failed; delivery status unknown') from None
    try:
        payload = response.json()
    except ValueError:
        raise SystemExit(f'{method}: HTTP {response.status_code}') from None
    if not payload.get('ok'):
        description = str(payload.get('description', 'Unknown error')).replace(TOKEN, '[redacted]')
        raise SystemExit(f'{method}: HTTP {response.status_code}: {description}')
    return payload.get('result')

def main():
    if not TOKEN:
        raise SystemExit('Missing TELEGRAM_BOT_TOKEN')
    me = api('getMe')
    membership = api('getChatMember', {'chat_id': CHAT, 'user_id': me['id']})
    if membership.get('status') not in ('administrator', 'creator'):
        raise SystemExit('Bot must be a channel administrator')
    if membership.get('status') != 'creator' and not membership.get('can_change_info'):
        raise SystemExit('Enable bot administrator permission: Change channel info')
    api('setChatTitle', {'chat_id': CHAT, 'title': TITLE})
    print('Channel title updated')
    api('setChatDescription', {'chat_id': CHAT, 'description': DESCRIPTION})
    print('Channel description updated')
    with Path('telegram-logo.png').open('rb') as photo:
        api('setChatPhoto', {'chat_id': CHAT}, files={'photo': ('telegram-logo.png', photo, 'image/png')})
    print('Channel logo updated')
    chat = api('getChat', {'chat_id': CHAT})
    pinned = chat.get('pinned_message', {})
    if 'WSN 24/7 — мировой спорт в одной ленте' in pinned.get('text', ''):
        print('Welcome post is already pinned')
        return
    if membership.get('status') != 'creator' and not membership.get('can_edit_messages'):
        raise SystemExit('Enable bot administrator permission: Edit messages, needed to pin a channel post')
    message = api('sendMessage', {'chat_id': CHAT, 'text': WELCOME, 'parse_mode': 'HTML', 'disable_web_page_preview': 'true', 'disable_notification': 'true'})
    api('pinChatMessage', {'chat_id': CHAT, 'message_id': message['message_id'], 'disable_notification': 'true'})
    print(f'Welcome post published and pinned: https://t.me/wsn247/{message["message_id"]}')

if __name__ == '__main__':
    main()
