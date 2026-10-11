import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .economy import cents, mines_multiplier


@dataclass(frozen=True)
class Limits:
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
        if not result.max_stake or not result.max_payout or result.max_open_risk<result.max_payout:
            raise ValueError('Invalid payout/risk limits')
        return result

    def public(self):
        return asdict(self)

    def check(self, stake, payout):
        if stake>self.max_stake:
            raise ValueError(f'Максимальная ставка: {self.max_stake} BStars')
        if payout>self.max_payout:
            raise ValueError(f'Максимальная выплата: {self.max_payout} BStars. Уменьши ставку.')

    def mines_steps(self, stake, bombs):
        steps=[k for k in range(1,26-bombs) if cents(stake*mines_multiplier(bombs,k))<=cents(self.max_payout)]
        if not steps:
            raise ValueError('Ставка превышает лимит выплаты мин')
        return steps[-1]
