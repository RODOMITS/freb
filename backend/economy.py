import math

RTP = .80


def distribution(case, items):
    drops = case['drops']
    total = sum(d['baseChance'] for d in drops)
    if abs(total - 1) > 1e-9:
        raise ValueError('Case weights must total 1')
    if case.get('free'):
        return [dict(d, chance=d['baseChance']) for d in drops]
    ev = sum(items[d['itemId']]['value'] * d['baseChance'] for d in drops)
    cheapest = min(drops, key=lambda d: items[d['itemId']]['value'])
    minimum = items[cheapest['itemId']]['value']
    target = case['price'] * RTP
    if not minimum <= target <= ev:
        raise ValueError('Недопустимая конфигурация кейса')
    scale = (target - minimum) / (ev - minimum) if ev != minimum else 1
    return [dict(d, chance=d['baseChance']*scale + (1-scale if d is cheapest else 0)) for d in drops]


def roll_case(case, items, rng):
    unit, cumulative = rng.draw(), 0
    for drop in distribution(case, items):
        cumulative += drop['chance']
        if unit < cumulative:
            return drop['itemId']
    return case['drops'][-1]['itemId']


def landing(chance, rng):
    low, high = -1., 1.
    for _ in range(40):
        y = (low + high)/2
        area = (math.acos(y) - y * math.sqrt(1-y*y))/math.pi
        if area > chance:
            low = y
        else:
            high = y
    level = 120 + (low+high)/2*104
    radius, angle = math.sqrt(rng.draw())*104, rng.draw()*math.tau
    x, y = 120 + math.sin(angle)*radius, 120 - math.cos(angle)*radius
    return dict(x=x, y=y, angle=angle/math.tau*360, win=y >= level,level=level)


def slots(value, ids, rng, rtp=RTP):
    unit, pool = rng.draw(), list(ids)
    a, b, c = rng.pick(pool), rng.pick(pool), rng.pick(pool)
    symbols = [a,a,a] if unit < .03 else [a,a,b] if unit < .03+(rtp-.15)/2 else [a,b,c]
    shuffled = [rng.pick(symbols) for _ in range(3)]
    multiplier = 5 if len(set(shuffled)) == 1 else 2 if len(set(shuffled)) == 2 else 0
    return dict(symbols=shuffled, multiplier=multiplier, betValue=value, payout=value*multiplier)


def mines_multiplier(bombs, opened, rtp=RTP):
    if not opened:
        return 0
    survival = math.prod((25-bombs-i)/(25-i) for i in range(opened))
    return rtp/survival


def crash_point(unit, rtp=RTP):
    return min(100., 1. if unit < 1-rtp else rtp/(1-unit))


def cents(value):
    return math.floor(value*100 + .5)
