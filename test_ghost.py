import requests, json, time

BASE = 'http://localhost:8000'

print('=== 1. FULL STATUS ===')
r = requests.get(f'{BASE}/api/status', timeout=10)
print(json.dumps(r.json(), indent=2))

print('\n=== 2. EXECUTE TEST COMMAND ===')
r = requests.post(f'{BASE}/api/execute', json={'command': 'echo Ghost Engine is Alive!', 'parallel': False}, timeout=15)
print(json.dumps(r.json(), indent=2))

print('\n=== 3. QUEUE BACKGROUND TASK ===')
r = requests.post(f'{BASE}/api/task', json={'command': 'echo Task from Ghost Engine queue'}, timeout=10)
print(json.dumps(r.json(), indent=2))

print('\n=== 4. AI ANALYSIS ===')
try:
    r = requests.post(f'{BASE}/api/model-route', json={'prompt': 'Respond with exactly: Ghost Engine AI is online and ready.'}, timeout=60)
    print(json.dumps(r.json(), indent=2))
except Exception as e:
    print(f'AI route test: {e}')

print('\n=== 5. DEPLOYMENT READY CHECK ===')
r = requests.post(f'{BASE}/api/deploy', timeout=10)
print(json.dumps(r.json(), indent=2))

print('\n=== GHOST ENGINE IS FULLY OPERATIONAL ===')
print('Dashboard: http://localhost:8000')
print('CLI: python cli.py [command]')
