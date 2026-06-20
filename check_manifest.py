import os, json

ext_path = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto\Extensions\nkbihfbeogaeaoehlefnkodbefgpgknn"

print("Root contents:")
for item in os.listdir(ext_path)[:25]:
    print(f"  {item}")

manifest_path = os.path.join(ext_path, "manifest.json")
if os.path.exists(manifest_path):
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)
    print(f"\nName: {m.get('name', '?')}")
    print(f"Version: {m.get('version', '?')}")
    print(f"Manifest V: {m.get('manifest_version', '?')}")
    print(f"Key present: {'key' in m}")
    
    bg = m.get("background", {})
    print(f"Background: {json.dumps(bg)[:200]}")
    
    war = m.get("web_accessible_resources", [])
    print(f"WAR: {len(war)} entries")
    
    action = m.get("action", {})
    print(f"Action: {json.dumps(action)[:200]}")
    
    # Check for manifest key needed for unpacked
    ext_id_parts = m.get("key", "")
    print(f"Key (first 50): {ext_id_parts[:50] if ext_id_parts else 'NONE'}")
else:
    print("manifest.json not found!")
    # Check subdirectories
    for root, dirs, files in os.walk(ext_path):
        for f in files:
            if f == "manifest.json":
                print(f"Found manifest at: {os.path.join(root, f)}")
