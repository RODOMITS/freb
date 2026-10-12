import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(raw: str, bot_token: str, now=None, max_age=300):
    if not bot_token or len(raw) > 16384:
        raise ValueError('Telegram authentication unavailable')
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    fields = dict(pairs)
    if len(pairs) != len(fields):
        raise ValueError('Duplicate authentication fields')
    supplied = fields.pop('hash', '')
    check = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ValueError('Invalid Telegram signature')
    age = (time.time() if now is None else now) - int(fields.get('auth_date', '0'))
    if age < -30 or age > max_age:
        raise ValueError('Telegram authentication expired; reopen Mini App')
    user = json.loads(fields.get('user', '{}'))
    if type(user.get('id')) is not int or user['id'] <= 0 or user.get('is_bot'):
        raise ValueError('Invalid Telegram user')
    return user
