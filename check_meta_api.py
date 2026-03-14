import requests
from bs4 import BeautifulSoup
import re

url = "https://analytics.metaplanet.jp/?lang=en"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(url, headers=headers)
soup = BeautifulSoup(resp.text, 'html.parser')

print("=== Scripts ===")
for s in soup.find_all('script'):
    src = s.get('src')
    if src:
        print(f"SRC: {src}")
    elif s.string:
        if 'json' in s.string.lower() or 'api' in s.string.lower():
            print(f"CONTENT: {s.string[:200]}...")

print("\n=== Links ===")
for a in soup.find_all('link'):
    print(a.get('href'))
