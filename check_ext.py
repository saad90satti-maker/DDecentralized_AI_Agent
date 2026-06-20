import json, os

prefs_path = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto\Preferences"
with open(prefs_path, encoding="utf-8") as f:
    prefs = json.load(f)

exts = prefs.get("extensions", {}).get("settings", {})
print(f"Extensions found: {len(exts)}")
for eid, settings in exts.items():
    name = settings.get("manifest", {}).get("name", "?")
    print(f"  ID: {eid}")
    print(f"  Name: {name}")
    print(f"  Path: {settings.get('path', 'N/A')}")
    print()
