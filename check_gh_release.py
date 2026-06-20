import requests, json

r = requests.get("https://api.github.com/repos/MetaMask/metamask-extension/releases/latest", timeout=15)
data = r.json()
print(f"Tag: {data.get('tag_name', 'N/A')}")
print(f"Name: {data.get('name', 'N/A')}")
assets = data.get("assets", [])
for a in assets:
    print(f"  Asset: {a['name']} ({a['size']} bytes)")
    print(f"    URL: {a['browser_download_url'][:150]}")
if not assets:
    print("No binary assets found")
    print(f"Zipball URL: {data.get('zipball_url', 'N/A')}")
