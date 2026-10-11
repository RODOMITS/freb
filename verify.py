"""Offline verifier: python -m backend.verify --seed ... --client ... --nonce 0 --game rocket"""
import argparse
import json
from pathlib import Path
from .economy import crash_point, landing, roll_case, slots
from .fair import FairRandom, commitment


def verify(seed, client, nonce, game, case_id='plant', chance=.5, bomb_count=3):
    rng=FairRandom(seed,client,nonce)
    catalog=json.loads(Path(__file__).with_name('catalog.json').read_text(encoding='utf-8'))
    items={i['id']:i for i in catalog['items']}
    if game=='rocket':
        result={'crash':crash_point(rng.draw())}
    elif game=='upgrade':
        result=landing(chance,rng)
    elif game=='slots':
        result=slots(1,list(items),rng)
    elif game=='mines':
        pool=list(range(25))
        result={'bombs':[rng.pick(pool) for _ in range(bomb_count)]}
    else:
        cases={c['id']:c for c in catalog['cases']}
        if case_id in ('daily','subscribe'):
            case={'free':True,'drops':[dict(itemId=i,baseChance=p) for i,p in [('67',.6),('lagrand',.25),('bananito',.1),('ketupat',.04),('garama',.01)]]}
        else:
            case=cases[case_id]
        result={'itemId':roll_case(case,items,rng)}
    return dict(serverHash=commitment(seed),result=result)


def verify_document(proof):
    seed=proof['serverSeed']
    if commitment(seed)!=proof['serverHash']:
        return dict(valid=False,detail='Server hash mismatch')
    if proof['game']=='case' and proof.get('table'):
        unit=FairRandom(seed,proof['clientSeed'],proof['nonce']).draw()
        cumulative=0
        outcome=proof['table'][-1]['itemId']
        for row in proof['table']:
            cumulative+=row['chance']
            if unit<cumulative:
                outcome=row['itemId']
                break
    else:
        result=verify(seed,proof['clientSeed'],proof['nonce'],proof['game'],proof.get('caseId','plant'),proof.get('chance',.5),proof.get('bombCount',3))['result']
        outcome=result if proof['game']=='upgrade' else result['symbols'] if proof['game']=='slots' else result['bombs'] if proof['game']=='mines' else result['crash'] if proof['game']=='rocket' else result['itemId']
    expected=proof.get('outcome')
    if proof['game']=='upgrade' and expected:
        valid=outcome['win']==expected['win'] and abs(outcome['x']-expected['x'])<1e-8 and abs(outcome['y']-expected['y'])<1e-8
    else:
        valid=outcome==expected
    return dict(valid=valid,result=outcome)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--proof',help='JSON copied from the Mini App')
    p.add_argument('--seed')
    p.add_argument('--client')
    p.add_argument('--nonce',type=int,default=0)
    p.add_argument('--game',choices=['case','upgrade','slots','mines','rocket'])
    p.add_argument('--case',default='plant')
    p.add_argument('--chance',type=float,default=.5)
    p.add_argument('--bombs',type=int,default=3)
    a=p.parse_args()
    if a.proof:
        print(json.dumps(verify_document(json.loads(Path(a.proof).read_text(encoding='utf-8'))),indent=2))
    elif a.seed and a.client and a.game:
        print(json.dumps(verify(a.seed,a.client,a.nonce,a.game,a.case,a.chance,a.bombs),indent=2))
    else:
        p.error('Provide --proof or --seed, --client and --game')
