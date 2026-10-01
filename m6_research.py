"""Preregistered rolling M6 experiments; data gaps fail acceptance, never silently pass."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from statistics import mean

from contract_specs import scenario_config
from funding_history import load_snapshot as load_funding, execution_funding, load_marks
from history import DAY, date_timestamp, load_snapshot
from indicators import calculate
from portfolio_simulation import PortfolioConfig, simulate
from structure_history import replay
from trade_simulation import Config, proposals

VERSION = "m6-rolling-preregistered-v1"
PRECISION_SOURCE = "https://www.gate.com/zh/announcements/article/50325"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def folds(start, end, train_days, test_days, embargo_days):
    if any(type(v) is not int or v < 1 for v in (train_days,test_days,embargo_days)):
        raise ValueError("Positive integer fold sizes required")
    if start % DAY or end % DAY or start >= end:
        raise ValueError("Invalid fold range")
    result=[]
    test_start=start+(train_days+embargo_days)*DAY
    while test_start < end:
        test_end=min(end,test_start+test_days*DAY)
        if test_end-test_start > embargo_days*DAY:
            result.append(dict(train_start=test_start-(train_days+embargo_days)*DAY,
                               train_end=test_start-embargo_days*DAY,
                               test_start=test_start,test_end=test_end))
        test_start=test_end
    return result


def restrict(rows, candidates, structures, start, end, censor_days):
    """Full-history causal feature warmup; no open orders cross a partition."""
    indices=[i for i,r in enumerate(rows) if start <= r["timestamp"] < end]
    if not indices:
        raise ValueError("Empty partition")
    offset=indices[0]
    cut=[dict(c,index=c["index"]-offset) for c in candidates
         if start <= c["signal_time"] < end-censor_days*DAY and c["index"] >= offset]
    return [rows[i] for i in indices],cut,[structures[i] for i in indices]


def variants(base):
    output=[("base",base)]
    for key,values in (("entry_atr",(0,1)),("stop_atr",(1,2)),("target_r",(1,3)),
                       ("expiry_days",(3,14)),("fee_rate",(base.fee_rate*2,)),
                       ("slippage",(base.slippage*2,)),("funding_daily",(base.funding_daily*2,))):
        output.extend((key+"="+str(v),replace(base,**{key:v})) for v in values)
    return output


def cluster_count(trades, days=44):
    last=None
    count=0
    for t in sorted(trades,key=lambda t:t["signal_time"]):
        if last is None or t["signal_time"]-last >= days*DAY:
            count+=1
            last=t["signal_time"]
    return count


def aggregate(runs, names):
    trades=[t for r in runs for t in r["trades"]]
    admitted=sum(r["summary"]["admitted"] for r in runs)
    filled=sum(r["summary"]["outcomes"].get("FILLED",0) for r in runs)
    outcomes={}
    for r in runs:
        for k,n in r["summary"]["outcomes"].items():
            outcomes[k]=outcomes.get(k,0)+n
    asset_results={s:dict(trades=sum(t["symbol"]==s for t in trades),
                           net_pnl=sum(t["net_pnl"] for t in trades if t["symbol"]==s)) for s in names}
    return dict(trades=len(trades), independent_time_blocks=cluster_count(trades), admitted=admitted,
                fill_rate=filled/admitted if admitted else None,
                unfilled_rate=1-filled/admitted if admitted else None,
                expiry_rate=outcomes.get("EXPIRED",0)/admitted if admitted else None,
                mean_net_r=mean(t["net_r"] for t in trades) if trades else None,
                mean_net_pnl=mean(t["net_pnl"] for t in trades) if trades else None,
                mean_holding_days=mean(t["holding_days"] for t in trades) if trades else None,
                net_pnl=sum(t["net_pnl"] for t in trades),
                max_fold_drawdown=max((r["summary"]["max_drawdown"] for r in runs),default=0),
                positive_fold_fraction=mean(r["summary"]["net_pnl"]>0 for r in runs) if runs else None,
                outcomes=outcomes,assets=asset_results,
                capital_protocol="independent equal capital per fold; no stitched portfolio equity")


def acceptance(dynamic, legacy, neighbors, limits, coverage):
    checks=dict(complete_historical_funding=coverage["historical_funding"],
                verified_historical_specs=coverage["historical_specs"],
                enough_trades=dynamic["trades"] >= limits["min_trades"],
                enough_independent_blocks=dynamic["independent_time_blocks"] >= limits["min_independent_blocks"],
                positive_expectancy=dynamic["mean_net_r"] is not None and dynamic["mean_net_r"]>limits["min_mean_net_r"],
                drawdown=dynamic["max_fold_drawdown"] <= limits["max_drawdown"],
                profitable_folds=dynamic["positive_fold_fraction"] is not None and
                                 dynamic["positive_fold_fraction"]>limits["min_positive_fold_fraction"],
                multiple_assets=sum(a["trades"]>=limits["min_trades_per_asset"] for a in dynamic["assets"].values())>=2,
                improves_legacy=dynamic["mean_net_r"] is not None and legacy["mean_net_r"] is not None and
                                dynamic["mean_net_r"]>legacy["mean_net_r"],
                neighbors=bool(neighbors) and sum(n["mean_net_r"] is not None and n["mean_net_r"]>0
                           for n in neighbors)/len(neighbors)>=limits["min_positive_neighbor_fraction"])
    return dict(status="PASS_RESEARCH_ONLY" if all(checks.values()) else "NOT_VALIDATED",
                checks=checks,failed=[k for k,v in checks.items() if not v])


def periods_for(root, names, base, start, end):
    output={}
    for s in names:
        cfg=scenario_config(root/"specs",s,base,assume_current_specs=True,
                            decimal_step="0.1" if s=="ETH" else None,
                            precision_source=PRECISION_SOURCE if s=="ETH" else None)
        transition=date_timestamp("2026-03-24")+2*3600
        items=[]
        if s=="ETH" and start<transition:
            items.append(dict(start=start,end=min(end,transition),
                              config=replace(cfg,quantity_step=1,min_quantity=1),source=PRECISION_SOURCE,
                              verified_fields=["min_quantity","quantity_step"]))
        if s!="ETH" or end>transition:
            items.append(dict(start=max(start,transition) if s=="ETH" else start,end=end,config=cfg,
                              source=PRECISION_SOURCE if s=="ETH" else "current API snapshot extrapolation",
                              verified_fields=["min_quantity","quantity_step"] if s=="ETH" else []))
        output[s]=items
    return output


def run(root, protocol, output):
    root=Path(root)
    names=protocol["assets"]
    rows,structures,indicators,quality={},{},{},{}
    code_hashes={p.name:sha(p) for p in Path(__file__).parent.glob("*.py")}
    for s in names:
        rows[s],quality[s]=load_snapshot(root/(s+"-daily"))
        indicators[s]=calculate(rows[s])
        # Reference replay is quadratic; cache by input and all source hashes.
        key=hashlib.sha256(json.dumps(dict(input=quality[s]["sha256"],code=code_hashes),sort_keys=True).encode()).hexdigest()
        cache=root/(s+"-structure-"+key[:16]+".json")
        if cache.exists():
            structures[s]=json.loads(cache.read_bytes())
        else:
            print(s,"replaying confirmed structures",flush=True)
            structures[s]=replay(rows[s])
            cache.write_text(json.dumps(structures[s],allow_nan=False),encoding="utf-8")
        print(s,"structures ready",sum(b["status"]=="OK" for b in structures[s]),flush=True)
    start=max(r[0]["timestamp"] for r in rows.values())
    end=min(r[-1]["timestamp"]+DAY for r in rows.values())
    all_folds=folds(start,end,protocol["train_days"],protocol["test_days"],protocol["embargo_days"])
    base=Config(**protocol["execution"])
    groups=protocol["groups"]
    reports={s:load_funding(root/(s+"-funding-full")) for s in names}
    funding={s:execution_funding(reports[s],load_marks(root/(s+"-marks-full.json"))["bars"],daily_bounds=True) for s in names}
    candidates={rule:{s:proposals(rows[s],rule,indicators=indicators[s],structures=structures[s]) for s in names}
                for rule in ("legacy_proxy","percentile_structure")}
    # Same data availability for both rules, including all feature warmups.
    for rule in candidates:
        for s in names:
            candidates[rule][s]=[c for c in candidates[rule][s] if all(indicators[s][c["index"]][k] is not None
                              for k in ("ret_30d","return_percentile","signed_move","stretch_atr"))]
    experiments=[]
    for variant,cfg in variants(base):
        censor=cfg.expiry_days+cfg.holding_days
        if protocol["embargo_days"] < censor:
            raise ValueError("Preregistered embargo must cover every variant's maximum lifetime")
        periods=periods_for(root,names,cfg,start,end)
        pc=PortfolioConfig(cfg,protocol["max_total_risk"],protocol["max_same_direction"])
        settlement = ({s:{t:[dict(e,rate=e["rate"]*2) for e in events] for t,events in days.items()}
                       for s,days in funding.items()} if variant.startswith("funding_daily=") else funding)
        for cost_mode in ("historical_funding","proxy"):
            for rule in candidates:
                for fold_id,f in enumerate(all_folds):
                    for partition in ("train","test"):
                        left,right=f[partition+"_start"],f[partition+"_end"]
                        pr,cs,ss={},{},{}
                        for s in names:
                            pr[s],cs[s],ss[s]=restrict(rows[s],candidates[rule][s],structures[s],left,right,censor)
                        result=simulate(pr,cs,pc,groups,ss,execution_periods=periods,
                                        funding=settlement if cost_mode=="historical_funding" else None)
                        experiments.append(dict(variant=variant,rule=rule,fold=fold_id,partition=partition,
                                                cost_mode=cost_mode,start=left,end=right,result=result))
        print("rolling variant",variant,"done",flush=True)
    aggregates=[]
    for variant,_ in variants(base):
        for cost_mode in ("historical_funding","proxy"):
            for rule in candidates:
                runs=[e["result"] for e in experiments if e["variant"]==variant and e["rule"]==rule
                      and e["partition"]=="test" and e["cost_mode"]==cost_mode]
                aggregates.append(dict(variant=variant,rule=rule,cost_mode=cost_mode,summary=aggregate(runs,names)))
    # Actual recent funding is a separate descriptive check, with complete warmup
    # from the long history. It cannot substitute costs in earlier rolling folds.
    actual=[]
    actual_start=date_timestamp("2026-04-06")
    actual_end=end
    for variant,cfg in variants(base):
        settlement = ({s:{t:[dict(e,rate=e["rate"]*2) for e in events] for t,events in days.items()}
                       for s,days in funding.items()} if variant.startswith("funding_daily=") else funding)
        for rule in candidates:
            pr,cs,ss={},{},{}
            for s in names:
                pr[s],cs[s],ss[s]=restrict(rows[s],candidates[rule][s],structures[s],actual_start,actual_end,
                                         cfg.expiry_days+cfg.holding_days)
            pc=PortfolioConfig(cfg,protocol["max_total_risk"],protocol["max_same_direction"])
            result=simulate(pr,cs,pc,groups,ss,funding=settlement,
                            execution_periods=periods_for(root,names,cfg,actual_start,actual_end))
            actual.append(dict(variant=variant,rule=rule,start=actual_start,end=actual_end,result=result))
    dynamic=next(a["summary"] for a in aggregates if a["variant"]=="base" and a["rule"]=="percentile_structure" and a["cost_mode"]=="historical_funding")
    legacy=next(a["summary"] for a in aggregates if a["variant"]=="base" and a["rule"]=="legacy_proxy" and a["cost_mode"]=="historical_funding")
    neighbors=[a["summary"] for a in aggregates if a["variant"]!="base" and a["rule"]=="percentile_structure" and a["cost_mode"]=="historical_funding"]
    coverage=dict(historical_funding=all(r["start"]<=start and r["status"]=="COMPLETE_ASSUMED_GRID" for r in reports.values()),
                  historical_specs=False)
    # Isolated per-asset accounts are diagnostics, never pooled into portfolio PnL.
    isolated=[]
    periods=periods_for(root,names,base,start,end)
    pc=PortfolioConfig(base,protocol["max_total_risk"],protocol["max_same_direction"])
    for rule in candidates:
        for fold_id,f in enumerate(all_folds):
            for s in names:
                pr,cs,ss=restrict(rows[s],candidates[rule][s],structures[s],f["test_start"],f["test_end"],
                                  base.expiry_days+base.holding_days)
                result=simulate({s:pr},{s:cs},pc,{s:groups[s]},{s:ss},
                                funding={s:funding[s]},execution_periods={s:periods[s]})
                isolated.append(dict(symbol=s,rule=rule,fold=fold_id,result=result))
    report=dict(version=VERSION,protocol=protocol,code_sha256=code_hashes,input_quality=quality,
                funding_quality=reports,folds=all_folds,experiments=experiments,aggregates=aggregates,
                recent_historical_funding=actual,isolated_asset_tests=isolated,
                acceptance=acceptance(dynamic,legacy,neighbors,protocol["acceptance"],coverage),
                limitations=["Long-history primary folds use real funding rates; proxy folds are separately labeled.",
                             "Current tick/multiplier/max size are extrapolated research assumptions; historical validity unverified.",
                             "ETH precision change is evidenced at 2026-03-24 02:00 UTC; intraday transition day executes old precision conservatively.",
                             "Public fees and configured slippage are scenarios, not historical account fills.",
                             "Daily OHLC fill and funding timing are uncertain; debit-only on ambiguous ownership days.",
                             "Long history mark hourly candles are unavailable beyond 10000 recent hours. Daily mark highs for debits and lows for credits bound costs conservatively, not exact settlement marks.",
                             "BTC/ETH is a present-day selected pool; delisted assets and historical universe absent.",
                             "Legacy baseline uses local 30-day return and identical entry model; differs from TradingView Perf.1M and 1% legacy entry.",
                             "Fixed base parameters, no best-test selection; train/test capital resets each fold."])
    report["evidence_sha256"]={str(p.relative_to(root)):sha(p) for p in root.rglob("*.json")}
    Path(output).write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(dict(dynamic=dynamic,legacy=legacy,acceptance=report["acceptance"]),indent=2))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot")
    p.add_argument("protocol")
    p.add_argument("--output",required=True)
    a=p.parse_args()
    if Path(a.output).exists():
        raise FileExistsError(a.output)
    protocol_path=Path(a.protocol)
    protocol=json.loads(protocol_path.read_bytes())
    protocol["preregistered_file_sha256"]=sha(protocol_path)
    run(a.snapshot,protocol,a.output)


if __name__ == "__main__":
    main()
