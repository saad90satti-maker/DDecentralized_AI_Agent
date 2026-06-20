import requests, os, re, json

url = "https://chrome.google.com/webstore/detail/metamask/nkbihfbeogaeaoehlefnkodbefgpgknn"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

r = requests.get(url, headers=headers, timeout=15)
print(f"Page loaded: {len(r.text)} bytes")

matches = re.findall(r'https?://[^"\' ]+\.crx[^"\' ]*', r.text)
print(f"CRX links found: {len(matches)}")
for m in matches[:5]:
    print(f"  {m[:200]}")
