const API_BASE = '/api/v1';
const REFRESH_MS = 5000;
let activeSummaryFilter = null;
let allMachines = [];

// Statuses that mean "something needs a human to look at this" -- these get
// the blinking row highlight and trigger a toast the moment they first
// appear, so a non-technical person watching the screen doesn't have to
// read small status text to notice a problem.
const BAD_CHROME_STATUSES = new Set(['Logged Out', 'CAPTCHA', 'Frozen', 'Chrome Closed']);

function token() {
  return localStorage.getItem('scope2_token');
}

function authHeaders() {
  return { 'Authorization': `Bearer ${token()}` };
}

async function apiGet(path, params = {}) {
  const url = new URL(API_BASE + path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => { if (v) url.searchParams.set(k, v); });
  const res = await fetch(url, { headers: authHeaders() });
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('unauthorized');
  }
  return res.json();
}

function fmtTime(d) {
  return d.toLocaleTimeString();
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

/* ---------------- Summary ---------------- */

function renderSummary(summary) {
  const groups = [
    {
      label: 'Systems',
      cards: [
        ['Total Systems', summary.total_systems],
        ['Online', summary.systems_online, summary.systems_online > 0 ? 'accent-good' : ''],
        ['Offline', summary.systems_offline, summary.systems_offline > 0 ? 'accent-bad' : ''],
      ],
    },
    {
      label: 'Chrome Instances',
      cards: [
        ['Total', summary.total_chrome_instances],
        ['Working', summary.healthy_browsers, 'accent-good'],
        ['Logged Out', summary.logged_out_browsers, summary.logged_out_browsers > 0 ? 'accent-bad' : ''],
        ['Not Working', summary.unknown_browsers, summary.unknown_browsers > 0 ? 'accent-warn' : ''],
        ['Not Working_C', summary.captcha_count, summary.captcha_count > 0 ? 'accent-warn' : ''],
        ['Not Working_F', summary.frozen_browsers, summary.frozen_browsers > 0 ? 'accent-warn' : ''],
        ['Closed', summary.closed_browsers, summary.closed_browsers > 0 ? 'accent-bad' : ''],
      ],
    },
  ];

  const el = document.getElementById('summaryCards');
  if (!el) return;

  el.innerHTML = groups.map(group => `
    <div>
      <div class="summary-group-label">${group.label}</div>
      <div class="summary-row">
        ${group.cards.map(([label, value, accent]) => `
          <div class="summary-card ${accent || ''} ${activeSummaryFilter === label ? 'active-summary' : ''}"
               data-filter="${escapeHtml(label)}"
               onclick="filterBySummary('${escapeHtml(label)}')"
          >
            <div class="value">${value ?? 0}</div>
            <div class="label">${escapeHtml(label)}</div>
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');
}

/* ---------------- Filter Summary Functions ---------------- */

function highlightSummaryCard(type) {
  document.querySelectorAll('.summary-card').forEach(card => {
    card.classList.remove('active-summary');
  });

  if (!type) return;

  document.querySelectorAll('.summary-card').forEach(card => {
    if (card.dataset.filter === type) {
      card.classList.add('active-summary');
    }
  });
}

function filterBySummary(type) {
  // Toggle off filter if clicking the active card again or if type is null
  if (!type || activeSummaryFilter === type) {
    activeSummaryFilter = null;
    highlightSummaryCard(null);
    renderMachines(allMachines);
    return;
  }

  activeSummaryFilter = type;

  let filtered = [];

  switch (type) {
    case 'Total Systems':
    case 'Total':
      filtered = allMachines;
      break;

    case 'Online':
      filtered = allMachines.filter(m =>
        m.status === 'ONLINE' || m.status === 'Online'
      );
      break;

    case 'Offline':
      filtered = allMachines.filter(m =>
        m.status === 'OFFLINE' || m.status === 'Offline'
      );
      break;

    case 'Working':
      filtered = allMachines.filter(m =>
        (m.chrome_instances || []).some(c =>
          c.status === 'Healthy' || c.status === 'Working'
        )
      );
      break;

    case 'Logged Out':
      filtered = allMachines.filter(m =>
        (m.chrome_instances || []).some(c => c.status === 'Logged Out')
      );
      break;

    case 'Not Working':
      filtered = allMachines.filter(m =>
        (m.chrome_instances || []).some(c =>
          c.status === 'Unknown' || c.status === 'Not Working'
        )
      );
      break;

    case 'Not Working_C':
      filtered = allMachines.filter(m =>
        (m.chrome_instances || []).some(c =>
          c.status === 'CAPTCHA' || c.status === 'Not Working_C'
        )
      );
      break;

    case 'Not Working_F':
      filtered = allMachines.filter(m =>
        (m.chrome_instances || []).some(c =>
          c.status === 'Frozen' || c.status === 'Not Working_F'
        )
      );
      break;

    case 'Closed':
      filtered = allMachines.filter(m =>
        (m.chrome_instances || []).some(c =>
          c.status === 'Chrome Closed' || c.status === 'Closed'
        )
      );
      break;

    default:
      filtered = allMachines;
  }

  highlightSummaryCard(type);

  // Show a targeted message when zero machines match the active card
  if (filtered.length === 0 && allMachines.length > 0) {
    const el = document.getElementById('machinesGrid');
    if (el) {
      el.innerHTML = `<p style="color:var(--text-dim); padding: 12px;">No systems found matching the <strong>${escapeHtml(type)}</strong> status filter.</p>`;
    }
  } else {
    renderMachines(filtered);
  }
}

/* ---------------- Refresh ---------------- */

async function refresh() {
  const search = document.getElementById('searchBox')?.value || '';
  const status = document.getElementById('statusFilter')?.value || '';
  const sortBy = document.getElementById('sortBy')?.value || '';

  const [summary, machinesResp] = await Promise.all([
    apiGet('/dashboard/summary'),
    apiGet('/machines', { search, status, sort_by: sortBy }),
  ]);

  allMachines = machinesResp.machines || [];

  renderSummary(summary);

  // Safely re-apply active filter without inducing recursive execution
  if (activeSummaryFilter) {
    const currentFilter = activeSummaryFilter;
    activeSummaryFilter = null; // reset flag to allow filterBySummary to process
    filterBySummary(currentFilter);
  } else {
    renderMachines(allMachines);
  }

  checkForNewIncidents(allMachines);

  if (currentView === 'alerts') {
    const alertsResp = await apiGet('/alerts', { resolved: 'false' });
    renderAlerts(alertsResp.alerts, 'alertsPanel', 'No active alerts.');
  }

  if (currentView === 'history') {
    const historyResp = await apiGet('/alerts', { resolved: 'true', limit: 100 });
    renderAlerts(historyResp.alerts, 'historyPanel', 'No resolved incidents yet.');
  }

  if (currentView === 'accounts') {
    const accountsResp = await apiGet('/accounts/summary');
    renderAccounts(accountsResp);
  }

  if (currentView === 'settings') {
    renderSettings();
  }

  const refreshEl = document.getElementById('lastRefresh');
  if (refreshEl) refreshEl.textContent = fmtTime(new Date());
}

/* ---------------- Machines ---------------- */

function machineBadgeClass(status) {
  if (status === 'Online' || status === 'ONLINE') return 'badge-online';
  if (status === 'Warning') return 'badge-warning';
  return 'badge-offline';
}

// Maps each Chrome status to a persistent row color, per the traffic-light
// convention: green = running fine, yellow = stuck/needs a look but not
// dead, red = disconnected/failed and needs action now.
const CHROME_ROW_COLOR = {
  'Healthy': 'row-green',
  'Frozen': 'row-yellow',
  'CAPTCHA': 'row-yellow',
  'Logged Out': 'row-red',
  'Chrome Closed': 'row-red',
  'Offline': 'row-red',
  'Unknown': 'row-neutral',
  'Not Working_C' :'row-red',
  'Not Working_F' :'row-red',
  'Not Working' :'row-red',
  'Working': 'row-green',
};

function renderMachines(machines) {
  const el = document.getElementById('machinesGrid');
  if (!el) return;

  if (!machines.length) {
    el.innerHTML = `<p style="color:var(--text-dim)">No machines registered yet — start an agent to see it appear here.</p>`;
    return;
  }
  el.innerHTML = machines.map(m => `
    <div class="machine-card ${m.status === 'Offline' || m.status === 'OFFLINE' ? 'blink-alert' : ''}">
      <div class="machine-card-head">
        <span class="machine-name"
      style="cursor: pointer"
      onclick="openRemoteDesktop(event, '${escapeHtml(m.machine_name ?? '')}')"
      title="Click to launch RDP session for ${escapeHtml(m.machine_name ?? '')}">
  ${escapeHtml(m.machine_name ?? '')}
</span>
        <span class="machine-badge ${machineBadgeClass(m.status)}">${escapeHtml(m.status)}</span>
      </div>
      <div class="machine-metrics">
        <span>CPU ${m.cpu_percent?.toFixed?.(0) ?? '—'}%</span>
        <span>RAM ${m.ram_percent?.toFixed?.(0) ?? '—'}%</span>
        <span>Disk ${m.disk_percent?.toFixed?.(0) ?? '—'}%</span>
        <span>${escapeHtml(m.ip_address ?? '')}</span>
      </div>
      ${(m.chrome_instances || []).length ? `
        <table class="chrome-table">
          <colgroup>
            <col class="col-instance"><col class="col-status"><col class="col-account">
          </colgroup>
          <tbody>
            ${(m.chrome_instances || []).map(c => `
              <tr class="${CHROME_ROW_COLOR[c.status] || 'row-neutral'}">
                <td class="chrome-label">Chrome ${c.instance_index}</td>
                <td class="chrome-status">${escapeHtml(c.status)}</td>
                <td class="chrome-account ${c.prime_account_name ? '' : 'unknown'}">
                  ${c.prime_account_name ? '👤 ' + escapeHtml(c.prime_account_name) : 'account not detected'}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      ` : ''}
    </div>
  `).join('');
}

/* ---------------- Alerts / History ---------------- */

function renderAlerts(alerts, targetId, emptyMessage) {
  const el = document.getElementById(targetId);
  if (!el) return;

  if (!alerts.length) {
    el.innerHTML = `<p style="color:var(--text-dim)">${escapeHtml(emptyMessage)}</p>`;
    return;
  }
  el.innerHTML = alerts.map(a => `
    <div class="alert-row">
      <span>${escapeHtml(a.machine_name)} — ${escapeHtml(a.message)}</span>
      <span class="alert-time">
        ${new Date(a.created_at * 1000).toLocaleString()}
        ${a.resolved ? ' · resolved ' + new Date(a.resolved_at * 1000).toLocaleString() : ''}
      </span>
    </div>
  `).join('');
}

/* ---------------- Accounts ---------------- */

function renderAccounts(data) {
  const el = document.getElementById('accountsPanel');
  if (!el) return;

  const { accounts, total_accounts, total_assigned_instances, unassigned_instances, highest_used_count } = data;

  if (!accounts || !accounts.length) {
    el.innerHTML = `<p style="color:var(--text-dim)">No Prime accounts detected yet — account names appear once agents pick up the "Hello, &lt;name&gt;" greeting from a signed-in Chrome window.</p>`;
    return;
  }

  const summaryLine = `
    <div class="summary-row">
      <div class="summary-card"><div class="value">${total_accounts}</div><div class="label">Distinct Accounts</div></div>
      <div class="summary-card"><div class="value">${total_assigned_instances}</div><div class="label">Instances w/ Known Account</div></div>
      <div class="summary-card"><div class="value">${unassigned_instances}</div><div class="label">Account Not Yet Detected</div></div>
    </div>
  `;

  const rows = accounts.map(a => `
    <tr>
      <td class="account-name-cell">
        ${escapeHtml(a.account_name)}
        ${a.is_highest_used ? '<span class="usage-tag tag-highest">Most Used</span>' : ''}
        ${a.is_lowest_used ? '<span class="usage-tag tag-lowest">Least Used</span>' : ''}
      </td>
      <td>
        ${a.instance_count} instance${a.instance_count === 1 ? '' : 's'}
        <div class="usage-bar-track">
          <div class="usage-bar-fill" style="width:${highest_used_count ? (a.instance_count / highest_used_count) * 100 : 0}%"></div>
        </div>
      </td>
      <td class="usage-list">
        ${a.usages.map(u => `${escapeHtml(u.machine_name)}#${u.instance_index} (${escapeHtml(u.status)})`).join(', ')}
      </td>
    </tr>
  `).join('');

  el.innerHTML = `
    ${summaryLine}
    <table class="accounts-table">
      <thead>
        <tr><th>Account</th><th>Usage</th><th>Where it's signed in</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

/* ---------------- Settings ---------------- */

function renderSettings() {
  const el = document.getElementById('settingsPanel');
  if (!el) return;
  el.innerHTML = `
    <h3>About this dashboard</h3>
    <p>Scope-2 Monitor watches your Amazon scraping fleet and reports status only —
       it never changes anything on your machines.</p>
    <div class="settings-row"><span>Auto-refresh interval</span><span>${REFRESH_MS / 1000}s</span></div>
    <div class="settings-row"><span>Row highlight</span><span>Blinks red while a Chrome instance needs attention</span></div>
    <div class="settings-row"><span>Notifications</span><span>Pop up top-right the moment a new issue appears</span></div>
  `;
}

/* ---------------- Toast notifications on new incidents ---------------- */

let previousChromeStatuses = new Map();
let previousMachineStatuses = new Map();

function showToast(title, timeLabel) {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `
    <div class="toast-title">${escapeHtml(title)}</div>
    <div class="toast-time">${escapeHtml(timeLabel)}</div>
  `;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 7000);
}

function checkForNewIncidents(machines) {
  const now = new Date().toLocaleTimeString();

  machines.forEach(m => {
    const prevMachineStatus = previousMachineStatuses.get(m.machine_name);
    if (prevMachineStatus !== undefined && prevMachineStatus !== 'Offline' && prevMachineStatus !== 'OFFLINE' && (m.status === 'Offline' || m.status === 'OFFLINE')) {
      showToast(`⚠ ${m.machine_name} went offline`, now);
    }
    previousMachineStatuses.set(m.machine_name, m.status);

    (m.chrome_instances || []).forEach(c => {
      const key = `${m.machine_name}#${c.instance_index}`;
      const prevStatus = previousChromeStatuses.get(key);
      if (prevStatus !== undefined && prevStatus !== c.status && BAD_CHROME_STATUSES.has(c.status)) {
        showToast(`⚠ ${m.machine_name} Chrome #${c.instance_index}: ${c.status}`, now);
      }
      previousChromeStatuses.set(key, c.status);
    });
  });
}

/* ---------------- Available Accounts widget ---------------- */

const STATUS_BADGE_LABEL = {
  working: 'Working Perfectly',
  in_use: 'In Use',
  expired: 'Account Expired',
};

let availableAccountsLoading = false;
let availableAccountsTimer = null;

function renderAvailableAccountsShell(innerHtml) {
  const el = document.getElementById('availableAccountsPanel');
  if (!el) return;
  el.innerHTML = `
    <div class="avail-accounts-head">
      <div class="avail-accounts-title-group">
        <span class="avail-accounts-title">Available Accounts</span>
        <span class="avail-accounts-count" id="availAccountsCount">—</span>
      </div>
      <button class="avail-refresh-btn" id="availRefreshBtn" ${availableAccountsLoading ? 'disabled' : ''}>
        ${availableAccountsLoading ? '<span class="avail-spinner"></span> Refreshing…' : '⟳ Refresh'}
      </button>
    </div>
    ${innerHtml}
  `;
  const btn = document.getElementById('availRefreshBtn');
  if (btn) btn.addEventListener('click', () => fetchAndRenderAvailableAccounts(true));
}

function renderAvailableAccountsTable(data) {
  const countEl = () => document.getElementById('availAccountsCount');

  if (!data.success) {
    renderAvailableAccountsShell(`
      <div class="avail-accounts-error">
        Couldn't load available accounts: ${escapeHtml(data.error || 'unknown error')}
        <button id="availRetryBtn">Try again</button>
      </div>
    `);
    document.getElementById('availRetryBtn')?.addEventListener('click', () => fetchAndRenderAvailableAccounts(true));
    return;
  }

  if (!data.accounts || !data.accounts.length) {
    renderAvailableAccountsShell(`<div class="avail-accounts-empty">No accounts currently available.</div>`);
    if (countEl()) countEl().textContent = '0 accounts';
    return;
  }

  const rows = data.accounts.map((a, i) => `
    <tr>
      <td data-label="Account">
        <span class="avail-account-name">${escapeHtml(a.account_name)}</span>
      </td>
      <td data-label="Phone"><span class="avail-phone">${escapeHtml(a.phone_no || '—')}</span></td>
      <td data-label="Password">
        <span class="avail-password" id="pw-${i}">••••••••</span>
        <button class="avail-password-toggle" data-index="${i}" data-value="${escapeHtml(a.password || '')}">show</button>
      </td>
      <td data-label="Remarks"><span class="avail-remarks">${escapeHtml(a.remarks || '—')}</span></td>
      <td data-label="Status">
        <span class="status-badge ${escapeHtml(a.status)}">${STATUS_BADGE_LABEL[a.status] || escapeHtml(a.status)}</span>
      </td>
    </tr>
  `).join('');

  renderAvailableAccountsShell(`
    <table class="avail-accounts-table">
      <colgroup>
        <col class="col-name"><col class="col-phone"><col class="col-password"><col class="col-remarks"><col class="col-badge">
      </colgroup>
      <thead>
        <tr><th>Account</th><th>Phone</th><th>Password</th><th>Remarks</th><th>Status</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `);

  document.querySelectorAll('.avail-password-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = btn.dataset.index;
      const span = document.getElementById(`pw-${idx}`);
      const revealed = btn.textContent === 'hide';
      span.textContent = revealed ? '••••••••' : (btn.dataset.value || '');
      btn.textContent = revealed ? 'show' : 'hide';
    });
  });

  if (countEl()) countEl().textContent = `${data.total_available} account${data.total_available === 1 ? '' : 's'}`;
}

async function fetchAndRenderAvailableAccounts(forceRefresh = false) {
  availableAccountsLoading = true;
  renderAvailableAccountsShell(`<div class="avail-loading-row"><span class="avail-spinner"></span> Loading accounts…</div>`);
  try {
    const data = await apiGet('/accounts', forceRefresh ? { refresh: 'true' } : {});
    availableAccountsLoading = false;
    renderAvailableAccountsTable(data);
  } catch (err) {
    availableAccountsLoading = false;
    renderAvailableAccountsTable({ success: false, error: 'network error' });
  }
}

function startAvailableAccountsAutoRefresh() {
  if (availableAccountsTimer) return;
  fetchAndRenderAvailableAccounts(false);
  availableAccountsTimer = setInterval(() => fetchAndRenderAvailableAccounts(false), 60000);
}

function stopAvailableAccountsAutoRefresh() {
  if (availableAccountsTimer) {
    clearInterval(availableAccountsTimer);
    availableAccountsTimer = null;
  }
}

/* ----------------Clickable IP---------------- */

function openRemoteDesktop(event, machineName) {
  if (event) event.stopPropagation();

  if (!machineName || machineName.trim() === '') {
    console.warn("No machine name available for RDP connection.");
    return;
  }

  // Trim whitespace
  const target = machineName.trim();

  // Launches native Windows RDP using the machine hostname
  window.open(`rdp://${target}`, '_self');
}

/* ---------------- View switching ---------------- */

let currentView = 'home';

const VIEW_SECTIONS = {
  home: ['machinesGrid'],
  machines: ['machinesGrid'],
  accounts: ['accountsPanel', 'availableAccountsPanel'],
  alerts: ['alertsPanel'],
  history: ['historyPanel'],
  settings: ['settingsPanel'],
};

const ALL_SECTIONS = ['machinesGrid', 'accountsPanel', 'availableAccountsPanel', 'alertsPanel', 'historyPanel', 'settingsPanel'];

function showViewSections() {
  const visible = VIEW_SECTIONS[currentView] || ['machinesGrid'];
  ALL_SECTIONS.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.hidden = !visible.includes(id);
  });
}

function setupNav() {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentView = btn.dataset.view;
      showViewSections();
      refresh();
      if (currentView === 'accounts') {
        startAvailableAccountsAutoRefresh();
      } else {
        stopAvailableAccountsAutoRefresh();
      }
    });
  });
}

function setupControls() {
  ['searchBox', 'statusFilter', 'sortBy'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', refresh);
      el.addEventListener('change', refresh);
    }
  });

  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      localStorage.removeItem('scope2_token');
      window.location.href = '/login';
    });
  }
}

(function init() {
  if (!token()) {
    window.location.href = '/login';
    return;
  }
  setupNav();
  setupControls();
  showViewSections();
  refresh();
  setInterval(refresh, REFRESH_MS);
})();