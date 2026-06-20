import requests, zipfile, io, os, json, shutil

# Download MetaMask Chrome build
url = "https://github.com/MetaMask/metamask-extension/releases/download/v13.35.1/metamask-chrome-13.35.1.zip"
print("Downloading MetaMask Chrome build (27MB)...", flush=True)
r = requests.get(url, timeout=120)
print(f"Downloaded: {len(r.content)} bytes", flush=True)

ext_base = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto\Extensions"
ext_dir = os.path.join(ext_base, "nkbihfbeogaeaoehlefnkodbefgpgknn")

if os.path.exists(ext_dir):
    shutil.rmtree(ext_dir)
os.makedirs(ext_dir, exist_ok=True)

z = zipfile.ZipFile(io.BytesIO(r.content))

# The zip contains a "metamask-chrome-13.35.1" folder at root
# Extract files, looking for manifest.json
for name in z.namelist():
    # Strip the root folder
    parts = name.split("/", 1)
    if len(parts) > 1:
        new_name = parts[1]
    else:
        new_name = parts[0]
    
    if new_name:
        target = os.path.join(ext_dir, new_name)
        if name.endswith("/"):
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(z.read(name))

# Verify manifest
manifest_path = os.path.join(ext_dir, "manifest.json")
if os.path.exists(manifest_path):
    with open(manifest_path) as f:
        manifest = json.load(f)
    print(f"Extension: {manifest.get('name', 'N/A')} v{manifest.get('version', 'N/A')}", flush=True)
    print(f"Manifest version: {manifest.get('manifest_version')}", flush=True)
    print(f"Files extracted: {len(os.listdir(ext_dir))} items in root", flush=True)
    
    # Count total files
    total = sum(len(files) for _, _, files in os.walk(ext_dir))
    print(f"Total files: {total}", flush=True)
else:
    print("manifest.json not found!", flush=True)
    # Debug: list root
    print(f"Root contents: {os.listdir(ext_dir)[:20]}", flush=True)
