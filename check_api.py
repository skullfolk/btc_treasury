import requests, json

headers = {"User-Agent": "Mozilla/5.0"}
r1 = requests.get("https://data.strategytracker.com/latest.json", headers=headers)
print(r1.json())
