import requests, json

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
r1 = requests.get("https://data.strategytracker.com/latest.json", headers=headers)
vstr = r1.json()["latestDataVersion"]

r2 = requests.get(f"https://data.strategytracker.com/all.v{vstr}.json", headers=headers)
data = r2.json()

d = data["companies"]["3350.T"]["processedMetrics"]
res = {
    "stockPrice": d.get("stockPrice"),
    "latestBtcBalance": d.get("latestBtcBalance"),
    "marketCapBasic": d.get("marketCapBasic"),
    "latestDebt": d.get("latestDebt"),
    "latestCashBalance": d.get("latestCashBalance"),
    "originalCurrency": d.get("originalCurrency", "N/A"),
    "companyName": d.get("companyName")
}

with open("meta_dump.json", "w") as f:
    json.dump(res, f, indent=2)

print("Dumped to meta_dump.json successfully.")
