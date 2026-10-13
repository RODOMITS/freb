import json
import tempfile
import unittest
from pathlib import Path
from backend.service import Service,ident
from backend.store import load_user,save_user
from backend.economy import distribution,slots
from backend.fair import FairRandom,commitment
from backend.verify import verify_document

ROOT=Path(__file__).resolve().parents[1]
LEGACY=['67','lagrand','bananito','esok','ketupat','tictac','lavadorito','garama','eviledon','cash','pizza','burguro','capitano','cerberus','pegasus','guest666','cookie','fortunu','ketupatbro','foxini','venuspino','dragon']

class CatalogTests(unittest.TestCase):
    def test_compositions_prices_files_and_return(self):
        c=json.loads((ROOT/'backend/catalog.json').read_text(encoding='utf-8'))
        items={i['id']:i for i in c['items']}
        self.assertEqual(len(items),45);self.assertEqual(len(c['cases']),15)
        used=set()
        for item in items.values():self.assertTrue((ROOT/'web'/item['image']).is_file(),item['image'])
        for case in c['cases']:
            prices=[items[d['itemId']]['value'] for d in case['drops']]
            self.assertEqual(prices,sorted(prices))
            self.assertTrue(2<=sum(v<case['price'] for v in prices)<=4)
            self.assertLessEqual(case['price'],2000)
            self.assertGreaterEqual(prices[-1],case['price']*3)
            self.assertEqual(sum(v==max(prices) for v in prices),1)
            actual=distribution(case,items)
            self.assertAlmostEqual(sum(d['chance'] for d in actual),1)
            self.assertAlmostEqual(sum(d['chance'] for d in actual if items[d['itemId']]['value']>=case['price']),{'feast':0.06947677842545236,'burrow':0.031579063640731056}.get(case['id'],.5))
            self.assertGreaterEqual(min(prices)/case['price'],.3)
            self.assertAlmostEqual(sum(items[d['itemId']]['value']*d['chance'] for d in actual),{'sahur':18.4,'feast':308,'burrow':272}.get(case['id'],.8*case['price']))
            used.update(d['itemId'] for d in actual)
        self.assertTrue((set(items)-set(LEGACY))<=used)

    def test_expensive_cases_without_game_caps(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'data') as tmp:
            s=Service(Path(tmp)/'db.sqlite',starting_balance=10000)
            s.login(dict(id=1,first_name='Test'))
            result=s.mutate(1,'case',dict(caseId='dragon'),ident())
            self.assertEqual(result['state']['balance'],8001)
            s.limits.check(1999,7387)
            s.limits.check(50000,5000000)
            self.assertEqual(s.limits.mines_steps(7387,3),22)

    def test_historical_slot_catalog_is_stable(self):
        seed='old-seed';client='player'
        for rtp in (.85,.90):
            for pool in (LEGACY,[i['id'] for i in json.loads((ROOT/'backend/catalog.json').read_text(encoding='utf-8'))['items']]):
                proof=dict(serverSeed=seed,serverHash=commitment(seed),clientSeed=client,nonce=0,game='slots',outcome=slots(1,pool,FairRandom(seed,client,0),rtp)['symbols'])
                if rtp!=.85:proof['rtp']=rtp
                if pool!=LEGACY:proof['itemIds']=pool
                self.assertTrue(verify_document(proof)['valid'])

if __name__=='__main__':unittest.main()
