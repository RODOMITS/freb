import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .economy import cents, mines_multiplier


@dataclass(frozen=True)
class Limits:
    max_case_price: int = 2000
    max_stake: int = 1000
    max_payout: int = 10000
    max_open_risk: int = 100000
    rocket_round_stake: int = 1000
    daily_bonus_budget: int = 1000
    withdraw_request_max: int = 10000
    withdraw_user_daily: int = 10000
    stars_hold_hours: int = 504

    @classmethod
    def load(cls, path):
        if not Path(path).exists():
            return cls()
        values=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if set(values)-set(cls.__dataclass_fields__):
            raise ValueError('Unknown limits setting')
        for key,value in values.items():
            if type(value) is not int or not 0<=value<=100000000:
                raise ValueError(f'Invalid limit: {key}')
        result=cls(**values)
        return result

    def public(self):
        return {key:value for key,value in asdict(self).items() if key in ('withdraw_request_max','withdraw_user_daily','stars_hold_hours')}

    def check(self, stake, payout):
        return None

    def check_case(self, price, payout):
        return None

    def mines_steps(self, stake, bombs):
        return 25-bombs
