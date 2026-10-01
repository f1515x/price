import unittest
from m6_research import folds, restrict, cluster_count, acceptance
from history import DAY


class RollingTests(unittest.TestCase):
    def test_rolling_folds_embargo_and_disjoint_tests(self):
        result=folds(0,2400*DAY,730,365,44)
        self.assertEqual(len(result),5)
        for f in result:
            self.assertEqual(f["test_start"]-f["train_end"],44*DAY)
            self.assertEqual(f["train_end"]-f["train_start"],730*DAY)
        for a,b in zip(result,result[1:]):
            self.assertEqual(a["test_end"],b["test_start"])

    def test_signal_known_only_at_execution_and_tail_censored(self):
        rows=[dict(timestamp=i*DAY) for i in range(10)]
        candidates=[dict(index=i,signal_time=(i+1)*DAY) for i in range(10)]
        bars,cs,ss=restrict(rows,candidates,list(range(10)),2*DAY,10*DAY,3)
        self.assertEqual(ss,list(range(2,10)))
        self.assertTrue(all(c["signal_time"]<7*DAY for c in cs))
        self.assertTrue(all(c["signal_time"]==bars[c["index"]]["timestamp"]+DAY for c in cs))

    def test_correlated_trades_do_not_inflate_independent_blocks(self):
        self.assertEqual(cluster_count([dict(signal_time=t*DAY) for t in (0,0,1,43,44,45,88)]),3)

    def test_profitable_results_cannot_overrule_missing_real_costs(self):
        dynamic=dict(trades=100,independent_time_blocks=40,mean_net_r=.2,max_fold_drawdown=.1,
                     positive_fold_fraction=.8,assets={"BTC":dict(trades=50),"ETH":dict(trades=50)})
        limits=dict(min_trades=30,min_independent_blocks=30,min_mean_net_r=0,max_drawdown=.15,
                    min_positive_fold_fraction=.5,min_trades_per_asset=10,min_positive_neighbor_fraction=.5)
        result=acceptance(dynamic,dict(mean_net_r=.1),[dict(mean_net_r=.1)],limits,
                          dict(historical_funding=False,historical_specs=False))
        self.assertEqual(result["status"],"NOT_VALIDATED")
        self.assertEqual(result["failed"],["complete_historical_funding","verified_historical_specs"])


if __name__=="__main__":
    unittest.main()
