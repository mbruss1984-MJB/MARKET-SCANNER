import unittest
from types import SimpleNamespace
from datetime import datetime, timezone
from scoring import Bar, analyze
from pipeline import select_candidates
from tracking import SignalTracker

class UpgradeTests(unittest.TestCase):
    def bars(self):
        base = [Bar(10,10.02,9.98,10,1000) for _ in range(6)]
        recent = [Bar(10,10.03,10,10.02,1500), Bar(10.02,10.04,10.01,10.03,2000), Bar(10.03,10.05,10.02,10.04,2500)]
        return base + recent, base + [Bar(10,10.06,10,10.04,1500)]
    def test_early_buildup_without_four_times(self):
        a,b=self.bars(); result=analyze(a,b)
        self.assertEqual(result['state'],'PRE_IGNITION')
        self.assertFalse(result['executable'])
        self.assertIsNone(result['probability'])
        self.assertLess(result['setup_invalidation'],result['setup_trigger'])
    def test_zero_baseline_and_tiny_volume(self):
        a,b=self.bars()
        a=[Bar(x.open,x.high,x.low,x.close,0) for x in a]
        self.assertNotEqual(analyze(a,b)['state'],'PRE_IGNITION')
        a,b=self.bars(); a=[Bar(x.open,x.high,x.low,x.close,x.volume/1000) for x in a]
        self.assertNotEqual(analyze(a,b)['state'],'PRE_IGNITION')
    def test_quote_buildup_and_reset(self):
        h={}; q=lambda v: SimpleNamespace(symbol='TEST.US',last_done=10,volume=v)
        self.assertEqual(select_candidates([q(1000)],h,lambda _:True,now=0),[])
        self.assertEqual(select_candidates([q(2000)],h,lambda _:True,now=60),[])
        self.assertTrue(select_candidates([q(4000)],h,lambda _:True,now=120)[0][2]['buildup_candidate'])
        self.assertEqual(select_candidates([q(100)],h,lambda _:True,now=180),[])
    def test_deduplicate_and_invalidate(self):
        t=SignalTracker(':memory:'); a,b=self.bars(); r=analyze(a,b)
        t.observe('TEST.US',r,10.04,'2026-10-12T19:00:00+00:00')
        t.observe('TEST.US',r,10.04,'2026-10-12T19:00:00+00:00')
        self.assertEqual(len(t.recent()),1)
        self.assertEqual(len(t.observations()),1)
        self.assertEqual(t.recent()[0]['observation_count'],1)
        t.observe('TEST.US',{'state':'NO_SIGNAL'},10,'2026-10-12T19:01:00+00:00')
        self.assertEqual(t.recent()[0]['lifecycle'],'INVALIDATED')

if __name__=='__main__': unittest.main()
