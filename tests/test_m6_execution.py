from dataclasses import replace
import json
import tempfile
import unittest

from contract_specs import collect, scenario_config, request_contract
from execution_history import validate_periods, at_time
from funding_history import normalize, execution_funding
from history import DAY
from portfolio_simulation import simulate, PortfolioConfig
from trade_simulation import Config, order_prices, round_step, simulate as single
from test_trade_simulation import data,candidate,cfg
from test_contract_specs import raw


class ExecutionTests(unittest.TestCase):
    def test_tick_direction_max_quantity_and_decimal_floor(self):
        c=candidate()
        c.update(raw_weak_price=100.05,atr=3.3)
        config=cfg(entry_atr=.5,stop_atr=1,target_r=2,price_tick=.1,max_quantity=2.5,
                   quantity_step=.1,min_quantity=.1)
        self.assertEqual(order_prices(c,config),(98.4,95.1,105.0))
        result=single(data([(100,105,95,100)]*3),[c],config)
        self.assertEqual(result["trades"][0]["quantity"],2.5)
        self.assertEqual(round_step(.3,.1),.3)
        with self.assertRaises(ValueError):
            replace(config,max_quantity=.01)

    def test_distinct_asset_multipliers_and_steps_reconcile_cash(self):
        rows={s:[dict(r,symbol=s) for r in data([(100,105,95,100)]*3)] for s in ("BTC","ETH")}
        config=cfg()
        execs=dict(BTC=replace(config,multiplier=.0001,quantity_step=1,min_quantity=1),
                   ETH=replace(config,multiplier=.01,quantity_step=.1,min_quantity=.1,max_quantity=100))
        result=simulate(rows,{s:[candidate()] for s in rows},PortfolioConfig(config,.05,2),
                        {s:s for s in rows},execution_by_asset=execs)
        trades={t["symbol"]:t for t in result["trades"]}
        self.assertEqual(trades["BTC"]["quantity"],100000)
        self.assertEqual(trades["ETH"]["quantity"],100)
        self.assertAlmostEqual(result["summary"]["final_equity"],10000+sum(t["net_pnl"] for t in result["trades"]))

    def test_explicit_decimal_evidence_and_full_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=dict(raw("ETH"),enable_decimal=True,order_size_min="0.1")
            collect(["ETH"],tmp+"/s",fetch=lambda s:json.dumps(r).encode())
            with self.assertRaises(ValueError):
                scenario_config(tmp+"/s","ETH",cfg(),assume_current_specs=True,decimal_step="0.1")
            c=scenario_config(tmp+"/s","ETH",cfg(),assume_current_specs=True,
                              decimal_step="0.1",precision_source="official precision announcement")
            self.assertEqual((c.quantity_step,c.min_quantity,c.price_tick,c.max_quantity),(.1,.1,.1,100000))

    def test_dated_specs_boundaries_gaps_and_multiplier_changes(self):
        config=cfg()
        periods=[dict(start=0,end=DAY,config=config,source="fixture",verified_fields=[]),
                 dict(start=DAY,end=3*DAY,config=replace(config,quantity_step=.1,min_quantity=.1),
                      source="fixture",verified_fields=["quantity_step"])]
        validate_periods(periods,0,3*DAY)
        self.assertEqual(at_time(periods,DAY).quantity_step,.1)
        for second in (dict(periods[1],start=DAY+1),dict(periods[1],config=replace(config,multiplier=2))):
            with self.assertRaises(ValueError):
                validate_periods([periods[0],second],0,3*DAY)

    def test_dated_step_applied_at_fill_not_signal(self):
        rows={"BTC":data([(100,105,95,100)]*3)}
        config=cfg(max_quantity=2.5)
        periods={"BTC":[dict(start=0,end=DAY,config=config,source="fixture",verified_fields=[]),
                        dict(start=DAY,end=3*DAY,config=replace(config,quantity_step=.1,min_quantity=.1),
                             source="fixture",verified_fields=[])]}
        result=simulate(rows,{"BTC":[candidate()]},PortfolioConfig(config,.05,2),{"BTC":"crypto"},
                        execution_periods=periods)
        self.assertEqual(result["trades"][0]["quantity"],2.5)

    def test_actual_funding_single_portfolio_parity_and_no_missing_zero(self):
        bars=data([(100,105,95,100)]*3)
        raw_rates=[dict(t=t,r="0.001") for t in range(0,3*DAY,28800)]
        records,_=normalize(raw_rates,0,3*DAY,28800)
        funding=execution_funding(dict(status="COMPLETE_ASSUMED_GRID",records=records),
                                  [dict(t=t,o="100") for t in range(0,3*DAY,28800)])
        config=cfg(funding_daily=.9)
        a=single(bars,[candidate()],config,funding=funding)
        b=simulate({"BTC":bars},{"BTC":[candidate()]},PortfolioConfig(config,.05,2),
                   {"BTC":"crypto"},funding={"BTC":funding})
        self.assertAlmostEqual(a["summary"]["final_equity"],b["summary"]["final_equity"])
        self.assertEqual(a["trades"][0]["funding"],5)
        self.assertAlmostEqual(b["summary"]["final_equity"],10000+sum(t["net_pnl"] for t in b["trades"]))
        with self.assertRaises(ValueError):
            single(bars,[candidate()],config,funding={})


if __name__=="__main__":
    unittest.main()
