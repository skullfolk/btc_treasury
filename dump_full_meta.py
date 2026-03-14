import requests, json

headers = {"User-Agent": "Mozilla/5.0"}
r1 = requests.get("https://data.strategytracker.com/latest.json", headers=headers)
vstr = r1.json()["version"] # Use the correct key

r2 = requests.get(f"https://data.strategytracker.com/all.v{vstr}.json", headers=headers)
data = r2.json()

d = data["companies"]["3350.T"]["processedMetrics"]
with open("meta_full.json", "w") as f:
    json.dump(d, f, indent=2)

print("Dumped full keys.")
