import json
from urllib.request import urlopen, Request

url = "https://data.strategytracker.com/all.v20260302T060346Z.json"
req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
data = json.loads(urlopen(req).read())

for k, v in data["companies"].items():
    pm = v["processedMetrics"]
    cname = pm.get("companyName")
    btc = pm.get("latestBtcBalance")
    shares = pm.get("latestDilutedShares")
    if "META" in cname.upper() or "3350" in k:
        print(f"{k}: {cname} - BTC: {btc} Shares: {shares}")
        
    if "35102" in str(btc) or btc == 35102:
        print(f"FOUND 35102 BTC in: {k}: {cname} - BTC: {btc} Shares: {shares}")
