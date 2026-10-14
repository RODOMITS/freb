import unittest,json
from datetime import datetime,timezone,timedelta
from tests import test_v150 as fixtures
from backend.service import Service,ident
from backend.fair import commitment

class WeeklyGiveawayTests(unittest.TestCase):
    setUp=fixtures.Release150Tests.setUp
    tearDown=fixtures.Release150Tests.tearDown
    call=fixtures.Release150Tests.call

    def funding(self,amount=50):
        with self.s.store.tx() as db:self.s.register_funding(db,200,ident(),int(amount*100))

    def test_daily_round_migration_preserves_seed_tickets_and_deadline(self):
        day=self.s.bonus_calendar(self.now)['day'];seed='existing-daily-seed'
        with self.s.store.tx() as db:
            db.execute('DROP TABLE giveaway_rounds')
            db.execute('CREATE TABLE giveaway_rounds(day TEXT PRIMARY KEY,seed TEXT NOT NULL,commitment TEXT NOT NULL)')
            db.execute('INSERT INTO giveaway_rounds VALUES(?,?,?)',(day,seed,commitment(seed)))
            db.execute('INSERT INTO funding_bonuses(id,user_id,amount,created,giveaway_day) VALUES(?,?,?,?,?)',('old-ticket',200,5000,self.now,day))
        self.s=Service('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        before=self.s.state(200);g=before['bonuses']['giveaway']
        self.assertEqual(g['day'],day);self.assertEqual(g['myTickets'],1)
        self.assertEqual(g['serverHash'],commitment(seed));self.assertEqual(g['period'],'daily')
        cutoff=g['drawAt']/1000;initial=len(before['inventory'])
        self.now=cutoff-1
        self.assertEqual(len(self.s.state(200)['inventory']),initial)
        self.now=cutoff
        after=self.s.state(200)
        self.assertEqual(len(after['inventory']),initial+1)
        self.assertEqual(after['bonuses']['giveaway']['last']['serverSeed'],seed)
        self.assertEqual(after['bonuses']['giveaway']['period'],'weekly')
        self.assertEqual(after['bonuses']['giveaway']['drawAt'],(cutoff+604800)*1000)
        self.assertEqual(len(self.s.state(200)['inventory']),initial+1)
        with self.s.store.tx() as db:
            self.assertEqual(db.execute("SELECT giveaway_day FROM funding_bonuses WHERE id='old-ticket'").fetchone()[0],day)
            self.assertEqual(db.execute("SELECT count(*) FROM outbox WHERE id=?",('giveaway-'+day,)).fetchone()[0],1)

    def begin_weekly(self):
        self.funding();self.call(200,'giveaway-enter')
        cutoff=self.s.state(200)['bonuses']['giveaway']['drawAt']/1000
        self.now=cutoff
        self.s.state(200)
        self.funding();self.call(200,'giveaway-enter')
        return self.s.state(200)['bonuses']['giveaway']

    def test_weekly_tickets_survive_midnight_and_round_lasts_seven_days(self):
        before=self.begin_weekly()
        self.now+=2*86400
        after=self.s.state(200)['bonuses']['giveaway']
        self.assertEqual(after['day'],before['day'])
        self.assertEqual(after['drawAt'],before['drawAt'])
        self.assertEqual(after['serverHash'],before['serverHash'])
        self.assertEqual(after['myTickets'],1)

    def test_weekly_draw_not_early_and_awarded_once(self):
        g=self.begin_weekly();initial=len(self.s.state(200)['inventory'])
        self.now=g['drawAt']/1000-1
        self.assertEqual(len(self.s.state(200)['inventory']),initial)
        self.now+=1
        after=self.s.state(200)
        self.assertEqual(len(after['inventory']),initial+1)
        self.assertEqual(after['bonuses']['giveaway']['myTickets'],0)
        self.assertEqual(after['bonuses']['giveaway']['last']['roundId'],g['day'])
        self.assertEqual(commitment(after['bonuses']['giveaway']['last']['serverSeed']),g['serverHash'])
        self.assertEqual(len(self.s.state(200)['inventory']),initial+1)

    def test_restart_does_not_reset_weekly_schedule(self):
        before=self.begin_weekly();self.now+=86400
        self.s=Service('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        after=self.s.state(200)['bonuses']['giveaway']
        self.assertEqual(after['day'],before['day']);self.assertEqual(after['drawAt'],before['drawAt'])
        self.assertEqual(after['myTickets'],1);self.assertEqual(after['serverHash'],before['serverHash'])

    def test_downtime_settles_old_week_once(self):
        g=self.begin_weekly();initial=len(self.s.state(200)['inventory'])
        self.now=g['drawAt']/1000+8*86400
        state=self.s.state(200)
        self.assertEqual(len(state['inventory']),initial+1)
        self.assertTrue(state['bonuses']['giveaway']['drawAt']>self.now*1000)
        self.assertEqual(len(self.s.state(200)['inventory']),initial+1)

    def test_new_entries_before_cutover_stay_in_current_daily(self):
        self.funding();one=self.call(200,'giveaway-enter')['state']['bonuses']['giveaway']
        self.funding();two=self.call(200,'giveaway-enter')['state']['bonuses']['giveaway']
        self.assertEqual(one['day'],two['day']);self.assertEqual(two['myTickets'],2)
        self.assertEqual(one['serverHash'],two['serverHash'])

if __name__=='__main__':unittest.main()
