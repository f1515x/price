import json
from pathlib import Path
import tempfile
import unittest

from funding_history import (collect, load_snapshot, normalize, execution_funding,
                             validate_execution_funding, funding_charge, load_marks, digest)
from history import DAY


class FundingTests(unittest.TestCase):
    def raw(self, start=0, end=DAY):
        return [dict(t=t,r="0.001") for t in range(start,end,28800)]

    def test_roundtrip_delay_and_immutable_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"funding"
            raw=[dict(t=r["t"]+1,r=r["r"]) for r in self.raw()]
            result=collect("BTC",0,DAY,path,fetch=lambda p:json.dumps(raw).encode(),clock=lambda:100)
            self.assertEqual(load_snapshot(path),result)
            self.assertEqual(result["records"][0]["reported_timestamp"],1)
            self.assertEqual(result["records"][0]["timestamp"],0)
            with self.assertRaises(FileExistsError):
                collect("BTC",0,DAY,path)

    def test_retention_error_preserved_and_not_simulatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            error=dict(label="INVALID_PARAM_VALUE",message="from time exceeds 180-day limit")
            result=collect("BTC",0,DAY,tmp+"/s",fetch=lambda p:json.dumps(error).encode())
            self.assertEqual(result["status"],"INCOMPLETE_DO_NOT_SIMULATE")
            self.assertEqual(len(result["missing"]),3)
            self.assertEqual(load_snapshot(tmp+"/s"),result)
            with self.assertRaises(ValueError):
                execution_funding(result,[])

    def test_pages_do_not_mix_limit_with_unbounded_history(self):
        seen=[]
        with tempfile.TemporaryDirectory() as tmp:
            def fetch(p):
                seen.append(p)
                return json.dumps(self.raw(p["from"],p["to"]+1)).encode()
            result=collect("BTC",0,101*DAY,tmp+"/s",fetch=fetch)
            self.assertEqual(len(seen),2)
            self.assertEqual(result["status"],"COMPLETE_ASSUMED_GRID")
            self.assertEqual(seen[0]["to"]+1,seen[1]["from"])

    def test_invalid_rates_conflicts_and_missing_settlement(self):
        for value in ("NaN","inf",True,None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize([dict(t=0,r=value)],0,DAY,28800)
        with self.assertRaises(ValueError):
            normalize([dict(t=0,r=0),dict(t=0,r=1)],0,DAY,28800)
        with self.assertRaises(ValueError):
            normalize([dict(t=61,r=0)],0,DAY,28800)
        _,missing=normalize(self.raw()[:-1],0,DAY,28800)
        self.assertEqual(missing,[57600])
        with self.assertRaises(ValueError):
            validate_execution_funding({"BTC":[dict(timestamp=0)]},
                                       {"BTC":{0:[dict(timestamp=0,rate=0,mark_price=100)]}})

    def test_mark_open_and_conservative_signed_accounting(self):
        records,_=normalize(self.raw(),0,DAY,28800)
        report=dict(status="COMPLETE_ASSUMED_GRID",records=records)
        bars=[dict(t=t,o="100",c="200") for t in range(0,DAY,28800)]
        events=execution_funding(report,bars)[0]
        self.assertEqual(funding_charge(events,1,10,ambiguous=False,new_position=False,stamp=0),3)
        self.assertEqual(funding_charge(events,-1,10,ambiguous=False,new_position=False,stamp=0),-3)
        self.assertEqual(funding_charge(events,-1,10,ambiguous=True,new_position=True,stamp=0),0)
        self.assertEqual(funding_charge(events,1,10,ambiguous=True,new_position=True,stamp=0),2)
        with self.assertRaises(ValueError):
            execution_funding(report,bars[:-1])

    def test_snapshot_tampering_rejected(self):
        for mutation in ("raw","records","params","pages"):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/"s"
                result=collect("BTC",0,DAY,path,fetch=lambda p:json.dumps(self.raw()).encode())
                if mutation=="raw":
                    (path/"page-0000.json").write_text("[]")
                else:
                    if mutation=="records":
                        result["records"][0]["rate"]=100
                    elif mutation=="params":
                        result["pages"][0]["params"]["from"]=DAY
                    else:
                        result["pages"]=[]
                    (path/"funding.json").write_text(json.dumps(result))
                with self.assertRaises(ValueError):
                    load_snapshot(path)

    def test_to_only_retention_alternative_filters_global_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen=[]
            def fetch(params):
                seen.append(params)
                right=params["to"]+1
                return json.dumps([dict(t=t,r="0") for t in range(max(0,right-30*DAY),right,28800)]).encode()
            result=collect("BTC",0,31*DAY,tmp+"/s",fetch=fetch,to_only=True)
            self.assertTrue(all("from" not in p for p in seen))
            self.assertEqual(len(result["records"]),93)
            self.assertEqual(load_snapshot(tmp+"/s"),result)

    def test_daily_mark_cost_bound_and_mark_tamper(self):
        records,_=normalize(self.raw(),0,DAY,28800)
        report=dict(status="COMPLETE_ASSUMED_GRID",records=records)
        bars=[dict(t=0,o="100",h="120",l="80")]
        events=execution_funding(report,bars,daily_bounds=True)[0]
        self.assertAlmostEqual(funding_charge(events,1,10,ambiguous=False,new_position=False,stamp=0),3.6)
        self.assertAlmostEqual(funding_charge(events,-1,10,ambiguous=False,new_position=False,stamp=0),-2.4)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"marks.json"
            body=json.dumps(bars)
            data=dict(symbol="BTC",start=0,end_exclusive=DAY,interval="1d",bars=bars,
                      pages=[dict(params=dict(contract="mark_BTC_USDT",interval="1d",**{"from":0,"to":DAY-1}),
                                  raw_body=body,raw_sha256=digest(body.encode()))])
            path.write_text(json.dumps(data))
            self.assertEqual(load_marks(path),data)
            data["bars"][0]["o"]="101"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_marks(path)


if __name__=="__main__":
    unittest.main()
