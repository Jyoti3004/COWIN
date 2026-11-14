"""Failover / chaos test for the CoWIN multi-AZ deployment (stdlib only).

Sends a steady stream of requests to the load balancer URL and records, per
request: timestamp, HTTP status, serving zone, latency.  While it runs, kill
one zone (docker compose stop zone-a / stop the EC2 instance / kill the
process).  The script then reports downtime and the failover time.

Usage:
  python failover_test.py --url http://localhost:8000/health --duration 60 --rate 10
  (kill Zone A around second 20; restart it around second 40 if you like)

Output: results/failover_log.csv + summary printed to console.
"""
import argparse
import csv
import os
import time
import urllib.request
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--duration", type=int, default=60, help="seconds")
    ap.add_argument("--rate", type=float, default=10, help="requests/second")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results", "failover_log.csv"))
    a = ap.parse_args()

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    rows, t0 = [], time.time()
    interval = 1.0 / a.rate
    print(f"Testing {a.url} for {a.duration}s at {a.rate} req/s ... kill a zone now!\n")

    last_zone = None
    while time.time() - t0 < a.duration:
        t_req = time.time()
        status, zone, err = 0, "-", ""
        try:
            with urllib.request.urlopen(a.url, timeout=3) as r:
                status = r.status
                zone = r.headers.get("X-Served-By-Zone") or json.loads(r.read()).get("zone", "?")
        except urllib.error.HTTPError as e:
            status, err = e.code, "http_error"
        except Exception as e:
            status, err = 0, type(e).__name__
        lat_ms = (time.time() - t_req) * 1000
        rel = t_req - t0
        rows.append((round(rel, 2), status, zone, round(lat_ms, 1), err))
        if zone != last_zone:
            print(f"[t={rel:6.1f}s] status={status} zone={zone} {err}")
            last_zone = zone
        time.sleep(max(0, interval - (time.time() - t_req)))

    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_seconds", "status", "zone", "latency_ms", "error"])
        w.writerows(rows)

    total = len(rows)
    ok = [r for r in rows if r[1] == 200]
    failed = [r for r in rows if r[1] != 200]
    zones = {}
    for r in ok:
        zones[r[2]] = zones.get(r[2], 0) + 1

    print("\n========== SUMMARY ==========")
    print(f"Total requests : {total}")
    print(f"Successful     : {len(ok)}  ({100*len(ok)/total:.2f}% availability)")
    print(f"Failed         : {len(failed)}")
    print(f"Served by zone : {zones}")
    if failed:
        print(f"Failure window : t={failed[0][0]}s -> t={failed[-1][0]}s "
              f"(~{failed[-1][0]-failed[0][0]:.1f}s of errors)")
    else:
        print("Failure window : none - zero failed requests (seamless failover)")
    if ok:
        lats = sorted(r[3] for r in ok)
        print(f"Latency ms     : p50={lats[len(lats)//2]}  p95={lats[int(len(lats)*0.95)-1]}  max={lats[-1]}")
    print(f"Log saved to   : {a.out}")


if __name__ == "__main__":
    main()
