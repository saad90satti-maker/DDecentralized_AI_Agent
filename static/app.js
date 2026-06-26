/* ===== GHOST ENGINE — COMMAND CENTER v3.1 ===== */
/* High-frequency polling with adaptive rate, connection resilience, port check */

// ---- Connection State ----
const CONN = {
  status: 'connected',  // 'connected' | 'refused' | 'error' | 'checking'
  retryCount: 0,
  maxRetryInterval: 30000,  // 30s cap
  baseInterval: 2000,       // 2s base
  lastOnline: Date.now(),
  listeners: [],
  subscribe(fn) { this.listeners.push(fn); },
  _notify() { this.listeners.forEach(fn => fn(this.status)); },
  setStatus(s) {
    if (s === this.status) return;
    this.status = s;
    if (s === 'connected') { this.retryCount = 0; this.lastOnline = Date.now(); }
    this._notify();
  }
};

// ---- Navigation ----
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', e => {
    e.preventDefault();
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    item.classList.add('active');
    const view = document.getElementById('view-' + item.dataset.view);
    if (view) view.classList.add('active');
    document.getElementById('page-title').textContent = item.textContent.trim();
    const subtitles = { overview: 'System Overview', terminal: 'Real-time Command Interface', tasks: 'Task Queue Management', network: 'Swarm & Network Status', deploy: 'Cloud Deployment Controls' };
    document.getElementById('page-subtitle').textContent = subtitles[item.dataset.view] || '';
  });
});

// ---- API helpers with retry + abort ----
const api = {
  _controller: null,
  _pending: new Map(),

  async _fetch(path, options = {}) {
    const key = options.method || 'GET' + path;
    // Abort previous in-flight request for same key
    if (this._pending.has(key)) {
      this._pending.get(key).abort();
    }
    const controller = new AbortController();
    this._pending.set(key, controller);

    try {
      const fetchOpts = { signal: controller.signal, ...options };
      if (!fetchOpts.headers) fetchOpts.headers = {};
      if (options.body) {
        fetchOpts.headers['Content-Type'] = 'application/json';
      }
      const r = await fetch(path, fetchOpts);
      if (!r.ok) {
        if (r.status >= 500) throw new Error(`Server error (${r.status})`);
        if (r.status === 0 || r.status === 502 || r.status === 503) throw new Error('Connection refused');
      }
      CONN.setStatus('connected');
      return r.json();
    } catch (err) {
      if (err.name === 'AbortError') return null; // silently ignore aborted
      const msg = err.message.toLowerCase();
      if (msg.includes('refused') || msg.includes('networkerror') || msg.includes('failed to fetch') || msg.includes('network')) {
        CONN.setStatus('refused');
      } else if (msg.includes('server error') || msg.includes('5')) {
        CONN.setStatus('error');
      }
      throw err;
    } finally {
      this._pending.delete(key);
    }
  },

  async get(path) {
    return this._fetch(path);
  },

  async post(path, body) {
    return this._fetch(path, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }
};

// ---- Connection Status UI ----
function updateConnectionUI(status) {
  const dot = document.getElementById('connection-dot');
  const label = document.getElementById('connection-status');
  if (!dot || !label) return;
  dot.className = 'status-dot';
  if (status === 'connected') {
    dot.classList.add('online');
    label.textContent = 'CONNECTED';
    label.style.color = '#00f5d4';
  } else if (status === 'refused') {
    dot.classList.add('error');
    label.textContent = 'CONNECTION REFUSED';
    label.style.color = '#ef4444';
  } else {
    dot.classList.add('offline');
    label.textContent = 'CONNECTION ERROR';
    label.style.color = '#f59e0b';
  }
}

CONN.subscribe(updateConnectionUI);
updateConnectionUI(CONN.status);

// ---- Terminal ----
const terminalBody = document.getElementById('terminal-body');
const terminalInput = document.getElementById('terminal-input');

function appendTerminal(text, cls = '') {
  const line = document.createElement('div');
  line.className = 'term-line ' + cls;
  line.innerHTML = text;
  terminalBody.appendChild(line);
  terminalBody.scrollTop = terminalBody.scrollHeight;
}

terminalInput.addEventListener('keydown', async e => {
  if (e.key === 'Enter') {
    const cmd = terminalInput.value.trim();
    if (!cmd) return;
    appendTerminal(`<span class="term-prompt">ghost@engine:~$</span> <span class="term-cmd">${escapeHtml(cmd)}</span>`);
    terminalInput.value = '';
    try {
      const data = await api.post('/api/execute', { command: cmd, parallel: false });
      const out = data.stdout || data.stderr || data.message || JSON.stringify(data, null, 2);
      appendTerminal(escapeHtml(out), data.status === 'success' ? 'success' : 'error');
      scheduleOverview();
    } catch (err) {
      appendTerminal('Connection error: ' + err.message, 'error');
    }
  }
});

function clearTerminal() { terminalBody.innerHTML = ''; }
function copyTerminal() {
  const text = Array.from(terminalBody.querySelectorAll('.term-line')).map(l => l.textContent).join('\n');
  navigator.clipboard.writeText(text);
}

// ---- Smart Polling Engine ----
const POLL = {
  _timers: { overview: null, tasks: null, network: null },
  _backoffs: { overview: 0, tasks: 0, network: 0 },

  _getInterval(base, backoff) {
    if (CONN.status === 'refused') {
      CONN.retryCount++;
      const retryMs = Math.min(CONN.baseInterval * Math.pow(2, CONN.retryCount), CONN.maxRetryInterval);
      return Math.max(retryMs, 1000);
    }
    if (backoff > 0) return Math.min(backoff * 2, 15000);
    return base;
  },

  _loop(key, fn, base) {
    const interval = this._getInterval(base, this._backoffs[key]);
    if (document.hidden) {
      this._timers[key] = setTimeout(() => {
        fn();
        this._loop(key, fn, base * 4);
      }, interval * 4);
    } else {
      this._timers[key] = setTimeout(async () => {
        try { await fn(); this._backoffs[key] = 0; }
        catch (e) { this._backoffs[key] = Math.max(this._backoffs[key] || 500, 500); }
        this._loop(key, fn, base);
      }, interval);
    }
  },

  start() {
    this._loop('overview', refreshOverview, 4000);
    this._loop('tasks', refreshTasks, 5000);
    this._loop('network', refreshNetwork, 10000);
  }
};

function scheduleOverview() {
  if (POLL._timers.overview) clearTimeout(POLL._timers.overview);
  POLL._backoffs.overview = 0;
  POLL._loop('overview', refreshOverview, 4000);
}

// ---- Overview ----
async function refreshOverview() {
  const status = await api.get('/api/status');
  if (!status) return;
  renderServices(status.services);
  renderMetrics(status);
  renderActivity(status.recent_outputs);
}

function renderServices(services) {
  const grid = document.getElementById('service-grid');
  if (!services) { grid.innerHTML = '<div class="activity-empty">No data</div>'; return; }
  grid.innerHTML = Object.entries(services).map(([name, st]) => {
    const s = String(st || 'unknown').toLowerCase();
    const dotCls = s === 'ok' || s === 'connected' || s === 'true' || s.startsWith('ok/') ? 'online'
      : s === 'error' || s === 'false' || s.startsWith('error/') ? 'error' : 'offline';
    const label = dotCls === 'online' ? 'ONLINE'
      : dotCls === 'error' ? 'ERROR' : s.toUpperCase();
    return `<div class="service-item"><span class="service-dot ${dotCls}"></span><span class="service-name">${name}</span><span class="service-status">${label}</span></div>`;
  }).join('');
}

function renderMetrics(status) {
  const services = status.services || {};
  const online = Object.values(services).filter(s => {
    const st = String(s).toLowerCase();
    return st === 'ok' || st === 'connected' || st === 'true' || st.startsWith('ok/');
  }).length;
  const total = Object.keys(services).length;
  const pending = (status.pending_tasks || []).length;
  const outputs = status.recent_outputs || [];
  const success = outputs.length ? Math.round(outputs.filter(o => o.result && o.result.status === 'success').length / outputs.length * 100) : 0;

  document.getElementById('metric-services').textContent = `${online}/${total}`;
  document.getElementById('metric-services-bar').style.width = total ? `${online/total*100}%` : '0%';
  document.getElementById('metric-pending').textContent = pending;
  document.getElementById('metric-pending-bar').style.width = `${Math.min(pending * 10, 100)}%`;
  document.getElementById('metric-peers').textContent = status.swarm_peers || 0;
  document.getElementById('metric-peers-bar').style.width = `${Math.min((status.swarm_peers || 0) * 20, 100)}%`;
  document.getElementById('metric-success').textContent = outputs.length ? `${success}%` : '--%';
  document.getElementById('metric-success-bar').style.width = `${success}%`;
  document.getElementById('task-count').textContent = pending + (status.active_workers || 0);
  document.getElementById('workers').textContent = status.active_workers || 0;
}

function renderActivity(outputs) {
  const feed = document.getElementById('activity-feed');
  if (!outputs || !outputs.length) {
    feed.innerHTML = '<div class="activity-empty">No recent activity</div>';
    return;
  }
  feed.innerHTML = outputs.slice(-20).reverse().map(o => {
    const ts = o.timestamp ? o.timestamp.slice(11, 19) : '--:--:--';
    const msg = o.command || o.message || JSON.stringify(o);
    return `<div class="activity-item"><span class="activity-time">${ts}</span><span class="activity-msg">${escapeHtml(msg)}</span></div>`;
  }).join('');
  document.getElementById('activity-count').textContent = outputs.length + ' events';
}

// ---- Task Queue ----
document.getElementById('task-form').addEventListener('submit', async e => {
  e.preventDefault();
  const cmd = document.getElementById('task-command').value;
  document.getElementById('task-command').value = '';
  try {
    const data = await api.post('/api/task', { command: cmd });
    document.getElementById('taskResult').textContent = JSON.stringify(data, null, 2);
    scheduleOverview();
  } catch (err) {
    document.getElementById('taskResult').textContent = 'Error: ' + err.message;
  }
});

document.getElementById('command-form').addEventListener('submit', async e => {
  e.preventDefault();
  const cmd = document.getElementById('command').value;
  document.getElementById('command').value = '';
  try {
    const data = await api.post('/api/execute', { command: cmd, parallel: false });
    document.getElementById('commandResult').textContent = JSON.stringify(data, null, 2);
    scheduleOverview();
  } catch (err) {
    document.getElementById('commandResult').textContent = 'Error: ' + err.message;
  }
});

async function refreshTasks() {
  const status = await api.get('/api/status');
  if (!status) return;
  const tasks = status.pending_tasks || [];
  const tbody = document.getElementById('task-tbody');
  if (!tasks.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">No pending tasks</td></tr>'; return; }
  tbody.innerHTML = tasks.map(t => {
    const age = t.timestamp ? Math.floor((Date.now() - new Date(t.timestamp).getTime()) / 1000) + 's' : '--';
    return `<tr><td>${escapeHtml(t.id || '?')}</td><td>${escapeHtml(t.command || '')}</td><td>${escapeHtml(t.status || 'pending')}</td><td>${age}</td></tr>`;
  }).join('');
}

// ---- Execution ----
async function prepareDeployment() {
  try {
    const data = await api.post('/api/deploy', {});
    document.getElementById('deployResult').textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    document.getElementById('deployResult').textContent = 'Error: ' + err.message;
  }
}

async function triggerIgnition() {
  try {
    const data = await api.post('/api/ignition/trigger', {});
    document.getElementById('ignitionResult').textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    document.getElementById('ignitionResult').textContent = 'Error: ' + err.message;
  }
}

async function runInfiltration() {
  try {
    const data = await api.post('/api/propagate/infiltrate', {});
    document.getElementById('infiltrateResult').textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    document.getElementById('infiltrateResult').textContent = 'Error: ' + err.message;
  }
}

// ---- Port Check (Deployment Tab) ----
async function checkPort() {
  const port = parseInt(document.getElementById('port-check-input').value, 10) || 8000;
  const resultEl = document.getElementById('port-check-result');
  resultEl.textContent = 'Checking...';
  resultEl.className = 'output-block';
  try {
    const data = await api.get(`/api/check-port?port=${port}`);
    resultEl.textContent = `Port ${data.port}: ${data.in_use ? '⚠ IN USE' : '✓ FREE'}`;
    resultEl.className = 'output-block ' + (data.in_use ? 'error' : 'success');
  } catch (err) {
    resultEl.textContent = 'Check failed: ' + err.message;
    resultEl.className = 'output-block error';
  }
}

// ---- Network View ----
async function refreshNetwork() {
  const [swarm, prop, peers] = await Promise.all([
    api.get('/api/swarm/status').catch(() => ({ error: 'unavailable' })),
    api.get('/api/propagate/status').catch(() => ({ error: 'unavailable' })),
    api.get('/api/swarm/peers').catch(() => ({ error: 'unavailable' }))
  ]);
  document.getElementById('swarm-status').textContent = JSON.stringify(swarm, null, 2);
  document.getElementById('propagate-status').textContent = JSON.stringify(prop, null, 2);
  document.getElementById('peers-list').textContent = JSON.stringify(peers, null, 2);
}

// ---- Charts ----
let throughputChart = null;
let latencyChart = null;

function initCharts() {
  const c1 = document.getElementById('chart-throughput');
  const c2 = document.getElementById('chart-latency');
  if (!c1 || !c2) return;
  const ctx1 = c1.getContext('2d');
  const ctx2 = c2.getContext('2d');

  throughputChart = new Chart(ctx1, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Tasks/min',
        data: [],
        borderColor: '#00f5d4',
        backgroundColor: 'rgba(0,245,212,0.05)',
        fill: true,
        tension: 0.4,
        pointRadius: 2,
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.03)' }, ticks: { color: '#555570', font: { size: 10 } } }
      }
    }
  });

  latencyChart = new Chart(ctx2, {
    type: 'bar',
    data: {
      labels: [],
      datasets: [{
        label: 'Latency (ms)',
        data: [],
        backgroundColor: 'rgba(34,211,238,0.3)',
        borderColor: '#22d3ee',
        borderWidth: 1,
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,0.03)' }, ticks: { color: '#555570', font: { size: 9 } } },
        y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.03)' }, ticks: { color: '#555570', font: { size: 10 } } }
      }
    }
  });
}

// ---- Utility ----
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ---- Init ----
initCharts();
POLL.start();
refreshOverview();
refreshTasks();
refreshNetwork();
