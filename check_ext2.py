import json, os

prefs_path = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto\Preferences"
with open(prefs_path, encoding="utf-8") as f:
    prefs = json.load(f)

exts = prefs.get("extensions", {}).get("settings", {})
print(f"Extensions: {len(exts)}")
for eid, s in exts.items():
    print(f"  {eid}: {s.get('manifest',{}).get('name','?')} v{s.get('manifest',{}).get('version','?')}")
    print(f"    path: {s.get('path','N/A')}")

# Also check the Extensions folder for ANY installed extensions
ext_folder = os.path.join(r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto", "Extensions")
if os.path.exists(ext_folder):
    ids = os.listdir(ext_folder)
    print(f"\nExtensions folder: {len(ids)} installs")
    for eid in ids:
        vers = os.listdir(os.path.join(ext_folder, eid))
        print(f"  {eid}: {vers}")
