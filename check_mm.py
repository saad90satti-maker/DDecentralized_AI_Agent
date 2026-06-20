import json, os

base = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data"
meta_id = "nkbihfbeogaeaoehlefnkodbefgpgknn"

for prof in os.listdir(base):
    prof_path = os.path.join(base, prof)
    if not os.path.isdir(prof_path) or (not prof.startswith("Profile") and prof != "Default"):
        continue
    prefs_path = os.path.join(prof_path, "Preferences")
    if os.path.exists(prefs_path):
        with open(prefs_path, encoding="utf-8") as f:
            prefs = json.load(f)
        exts = prefs.get("extensions", {}).get("settings", {})
        if meta_id in exts:
            info = exts[meta_id]
            print(f"INSTALLED in {prof}")
            print(f"  Version: {info.get('manifest',{}).get('version','?')}")
            print(f"  State: {info.get('state')}")
            exit(0)
        else:
            items = os.listdir(os.path.join(prof_path, "Extensions", meta_id)) if os.path.exists(os.path.join(prof_path, "Extensions", meta_id)) else []
            if items:
                print(f"  {prof}: folder exists but NOT in Preferences: {items}")
            else:
                print(f"  {prof}: no MetaMask folder")

print("MetaMask NOT installed in any profile")
