import json
import unittest
from pathlib import Path
from backend.economy import distribution, roll_case

CATALOG=Path(__file__).resolve().parents[1]/'backend'/'catalog.json'

class CaseBalanceTests(unittest.TestCase):
    def setUp(self):
        self.catalog=json.loads(CATALOG.read_text(encoding='utf-8'))
        self.items={i['id']:i for i in self.catalog['items']}

    def test_probabilities_and_expected_rewards(self):
        for case in self.catalog['cases']:
            with self.subTest(case=case['id']):
                drops=distribution(case,self.items)
                self.assertAlmostEqual(sum(d['chance'] for d in drops),1)
                self.assertEqual(len({d['itemId'] for d in drops}),len(drops))
                self.assertTrue(all(0<d['chance']<1 for d in drops))
                if case['id']=='allornothing':
                    self.assertEqual(case['price'],400)
                    self.assertEqual({d['itemId']:d['chance'] for d in drops},{'garama':.7,'dragon':.3})
                    continue
                if case.get('free'):continue
                losses=[d for d in drops if self.items[d['itemId']]['value']<case['price']]
                wins=[d for d in drops if self.items[d['itemId']]['value']>=case['price']]
                self.assertEqual(len(losses),2)
                self.assertAlmostEqual(losses[0]['chance'],losses[1]['chance'])
                self.assertGreaterEqual(losses[0]['chance'],.3-1e-12)
                self.assertTrue(all(self.items[d['itemId']]['value']>=case['price'] for d in wins))
                self.assertLessEqual(sum(d['chance'] for d in wins),.4+1e-12)
                expected=sum(self.items[d['itemId']]['value']*d['chance'] for d in drops)
                self.assertLessEqual(expected,case['price']*.8+1e-9)
                if len(wins)>=3:
                    self.assertAlmostEqual(wins[-2]['chance'],wins[-1]['chance']*5)
                    self.assertLessEqual(wins[-2]['chance'],.05+1e-12)
                    self.assertLessEqual(wins[-1]['chance'],.01+1e-12)
                else:
                    self.assertEqual(case['id'],'cash')
                    self.assertAlmostEqual(wins[0]['chance'],.39)
                    self.assertAlmostEqual(wins[1]['chance'],.01)

    def test_actual_roll_uses_each_probability_interval(self):
        class Fixed:
            def __init__(self,value):self.value=value
            def draw(self):return self.value
        for case in self.catalog['cases']:
            lower=0
            for drop in distribution(case,self.items):
                with self.subTest(case=case['id'],item=drop['itemId']):
                    upper=lower+drop['chance']
                    for draw in (lower+drop['chance']*.01,lower+drop['chance']*.5,lower+drop['chance']*.99):
                        self.assertEqual(roll_case(case,self.items,Fixed(draw)),drop['itemId'])
                    lower=upper

if __name__=='__main__':unittest.main()
