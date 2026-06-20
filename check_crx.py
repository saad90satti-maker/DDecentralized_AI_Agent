import requests

urls = [
    "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=108.0.5359.0&x=id%3Dnkbihfbeogaeaoehlefnkodbefgpgknn%26installsource%3Dondemand%26uc",
    "https://clients2.google.com/service/update2/crx?response=redirect&acceptformat=crx2,crx3&prodversion=108.0.5359.0&x=id%3Dnkbihfbeogaeaoehlefnkodbefgpgknn%26installsource%3Dondemand%26uc",
]
for url in urls:
    r = requests.get(url, timeout=15, allow_redirects=True)
    ct = r.headers.get("content-type", "")[:40]
    print(f"Status: {r.status_code}, Size: {len(r.content)}, Content-Type: {ct}")
