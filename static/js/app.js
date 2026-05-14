/**
 * app.js — Racpad Support Tool Frontend v5
 * Vanilla JS SPA — Flask backend via fetch() API
 */

/* ─────────────────── Utilities ─────────────────── */
const UI = {
  show(id)  { const el = document.getElementById(id); if (el) el.style.display = ''; },
  hide(id)  { const el = document.getElementById(id); if (el) el.style.display = 'none'; },
  text(id, t){ const el = document.getElementById(id); if (el) el.textContent = t; },
  html(id, h){ const el = document.getElementById(id); if (el) el.innerHTML = h; },
  val(id)   { const el = document.getElementById(id); return el ? el.value.trim() : ''; },
  set(id, v){ const el = document.getElementById(id); if (el) el.value = v; },

  toggleCard(bodyId) {
    const body = document.getElementById(bodyId);
    if (body) body.classList.toggle('collapsed');
  },

  toggleSidebar() {
    document.getElementById('sidebar')?.classList.toggle('open');
  },

  alert(containerId, msg, type = 'info') {
    const el = document.getElementById(containerId);
    if (el) el.innerHTML = `<div class="alert alert-${type}">${msg}</div>`;
  },

  clearAlert(id) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  },
};

function toast(msg, type = '') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast${type ? ' toast-' + type : ''}`;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3500);
}

async function api(method, url, body = null) {
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== null) opts.body = JSON.stringify(body);
    const res  = await fetch(url, opts);
    const data = await res.json().catch(() => ({ error: 'Server error' }));
    return { ok: res.ok, data };
  } catch (err) {
    console.error('[API Error]', method, url, err);
    return { ok: false, data: { error: err.message || 'Network error' } };
  }
}

function fmt(val) { return val == null || val === '' ? '—' : val; }

/* ─────────────────── State ─────────────────── */
let _state = { pricingResult: null, po622Result: null };

/* ─────────────────── App ─────────────────── */
const App = {

  // ── Init ──
  async init() {
    console.log('[App] Initializing...');
    App._initTheme();
    try {
      const { ok, data } = await api('GET', '/api/status');
      console.log('[App] /api/status response:', ok, data);
      if (!ok) {
        toast('Cannot reach server: ' + (data.error || 'unknown'), 'error');
        // Show setup as fallback
        UI.show('setupSection');
        return;
      }
      data.email_configured && data.db_configured
        ? App._showMain(data)
        : App._showSetup(data);
    } catch (err) {
      console.error('[App] init failed:', err);
      toast('App initialization error', 'error');
      UI.show('setupSection');
    }
  },

  // ── Theme ──
  _initTheme() {
    const saved = localStorage.getItem('racpad_theme') || 'light';
    App._applyTheme(saved);
  },

  toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem('racpad_theme', next);
    App._applyTheme(next);
  },

  _applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const isDark = theme === 'dark';
    document.getElementById('themeIcon').textContent  = isDark ? '☀️' : '🌙';
    document.getElementById('themeLabel').textContent = isDark ? 'Light Mode' : 'Dark Mode';
    document.getElementById('themeBadge').textContent = isDark ? 'DARK' : 'LIGHT';
  },

  // ── Main/Setup ──
  _showMain(status) {
    UI.hide('setupSection');
    UI.show('sidebarNav');
    UI.show('sidebarSettings');
    UI.show('sidebarFooter');
    App._updateCreds(status);
    App.navigate('pricing');
  },

  _showSetup(status) {
    UI.hide('sidebarNav'); UI.hide('sidebarSettings'); UI.hide('sidebarFooter');
    UI.hide('pricingSection'); UI.hide('po622Section');
    UI.show('setupSection');
    App._updateProgress(status);
    App._prefill(status);
  },

  _updateCreds(status) {
    let h = '';
    if (status.email_user) h += `<div class="cred-item">✅ Email<br><code>${status.email_user}</code></div>`;
    if (status.rac_info) h += `<div class="cred-item">✅ RAC DB<br><code>${status.rac_info}</code></div>`;
    if (status.prc_info) h += `<div class="cred-item">✅ Pricing DB<br><code>${status.prc_info}</code></div>`;
    UI.html('sidebarCredStatus', h);
  },

  _updateProgress(status) {
    const done = (status.email_configured ? 1 : 0) + (status.db_configured ? 1 : 0);
    const fill = document.getElementById('setupProgressFill');
    if (fill) fill.style.width = `${done * 50}%`;
    UI.text('setupProgressLabel', `Setup progress: ${done}/2 steps complete`);
    if (status.email_configured) {
      document.getElementById('emailSetupBody')?.classList.add('collapsed');
      UI.alert('emailSetupStatus', '✅ Email credentials saved.', 'success');
    }
    if (status.db_configured) {
      document.getElementById('dbSetupBody')?.classList.add('collapsed');
      UI.alert('dbSetupStatus', '✅ DB credentials saved.', 'success');
    }
  },

  async _prefill(status) {
    UI.set('smtpHost', status.smtp_host || 'smtp.office365.com');
    UI.set('smtpPort', status.smtp_port || '587');
    if (status.pricing_recipients?.join('').trim()) {
      UI.set('pricingRecipients', status.pricing_recipients.filter(r=>r.trim()).join(', '));
    }
    if (status.email_user) UI.set('smtpUser', status.email_user);
    const { ok, data } = await api('GET', '/api/credentials/db');
    if (ok && data && data.rac_host !== undefined) {
      UI.set('racHost', data.rac_host||''); UI.set('racPort', data.rac_port||'5432');
      UI.set('racDbname', data.rac_dbname||'racdb'); UI.set('racUser', data.rac_user||'');
      UI.set('prcHost', data.prc_host||''); UI.set('prcPort', data.prc_port||'5432');
      UI.set('prcDbname', data.prc_dbname||'prcdb'); UI.set('prcUser', data.prc_user||'');
      const k = document.getElementById('useKerberos');
      if (k) { k.checked = data.use_kerberos !== false; App.toggleKerberos(); }
    }
  },

  // ── Navigation ──
  navigate(page, btnEl = null) {
    UI.hide('pricingSection'); UI.hide('po622Section'); UI.hide('setupSection');
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    if (page === 'pricing') UI.show('pricingSection');
    else if (page === 'po622') UI.show('po622Section');
    const btn = btnEl || document.querySelector(`.nav-item[data-page="${page}"]`);
    if (btn) btn.classList.add('active');
  },

  toggleKerberos() {
    const checked = document.getElementById('useKerberos')?.checked;
    ['racPass', 'prcPass'].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = !!checked; });
  },

  // ── Save Email ──
  async saveEmailCreds(e) {
    e.preventDefault(); UI.clearAlert('emailSetupStatus');
    const btn = e.target.querySelector('button[type=submit]');
    const orig = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span> Saving…'; btn.disabled = true;
    const { ok, data } = await api('POST', '/api/setup/email', {
      smtp_user: UI.val('smtpUser'), smtp_password: UI.val('smtpPass'),
      smtp_host: UI.val('smtpHost'), smtp_port: UI.val('smtpPort'),
      pricing_recipients: UI.val('pricingRecipients'),
    });
    btn.innerHTML = orig; btn.disabled = false;
    if (ok) { UI.alert('emailSetupStatus', `✅ ${data.message}`, 'success'); toast(data.message, 'success'); await App._checkDone(); }
    else UI.alert('emailSetupStatus', `❌ ${data.error}`, 'error');
  },

  // ── Save DB ──
  async saveDbCreds(e) {
    e.preventDefault(); UI.clearAlert('dbSetupStatus');
    const btn = e.target.querySelector('button[type=submit]');
    const orig = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span> Saving…'; btn.disabled = true;
    const { ok, data } = await api('POST', '/api/setup/db', {
      rac_host: UI.val('racHost'), rac_port: UI.val('racPort'), rac_dbname: UI.val('racDbname'),
      rac_user: UI.val('racUser'), rac_password: UI.val('racPass'),
      prc_host: UI.val('prcHost'), prc_port: UI.val('prcPort'), prc_dbname: UI.val('prcDbname'),
      prc_user: UI.val('prcUser'), prc_password: UI.val('prcPass'),
      use_kerberos: document.getElementById('useKerberos')?.checked ?? true,
    });
    btn.innerHTML = orig; btn.disabled = false;
    if (ok) { UI.alert('dbSetupStatus', `✅ ${data.message}`, 'success'); toast(data.message, 'success'); await App._checkDone(); }
    else UI.alert('dbSetupStatus', `❌ ${data.error}`, 'error');
  },

  async _checkDone() {
    const { ok, data } = await api('GET', '/api/status');
    if (ok && data.email_configured && data.db_configured) {
      toast('✅ Setup complete!', 'success');
      setTimeout(() => App._showMain(data), 800);
    } else if (ok) App._updateProgress(data);
  },

  // ── Logout ──
  async logout() {
    if (!confirm('Clear all saved credentials?')) return;
    await api('DELETE', '/api/credentials');
    toast('Credentials cleared.', 'success');
    setTimeout(() => location.reload(), 700);
  },

  // ── Pricing Fetch ──
  async fetchPricing(e) {
    e.preventDefault(); UI.clearAlert('pricingStatus'); UI.hide('pricingResults');
    const btn = document.getElementById('fetchBtn');
    btn.innerHTML = '<span class="spinner"></span> Fetching…'; btn.disabled = true;
    const { ok, data } = await api('POST', '/api/pricing/fetch', { po_number: UI.val('poNumber'), store_number: UI.val('storeNumber') });
    btn.innerHTML = '🔍 Fetch Pricing Details'; btn.disabled = false;
    if (!ok) { UI.alert('pricingStatus', `⚠️ ${data.error}`, 'warning'); return; }
    _state.pricingResult = data;
    App._renderPricing(data);
  },

  _renderPricing(r) {
    const items = r.items || [], unpriced = items.filter(i => !i.has_pricing), priced = items.filter(i => i.has_pricing);
    UI.text('pricingResultTitle', `Results — PO ${r.po_number} | Store ${r.store_number}`);
    UI.html('pricingTableBody', items.map(item => {
      const d = item.details || {};
      return `<tr>
        <td><code>${item.item}</code></td><td>${item.model_number||'—'}</td>
        <td class="${item.has_pricing?'badge-yes':'badge-no'}">${item.has_pricing?'✅ Yes':'❌ No'}</td>
        <td>${fmt(d.zone_number)}</td><td>${fmt(d.pricing_type)}</td>
        <td>${d.weekly_rate!=null?'$'+Number(d.weekly_rate).toFixed(2):'—'}</td>
        <td>${d.monthly_rate!=null?'$'+Number(d.monthly_rate).toFixed(2):'—'}</td>
        <td>${d.cash_price!=null?'$'+Number(d.cash_price).toFixed(2):'—'}</td>
      </tr>`;
    }).join(''));
    UI.html('pricingMetrics', [
      {l:'Total Items', v:items.length}, {l:'✅ With Pricing', v:priced.length}, {l:'❌ Missing', v:unpriced.length},
    ].map(m=>`<div class="metric-card"><div class="metric-label">${m.l}</div><div class="metric-value">${m.v}</div></div>`).join(''));
    if (unpriced.length === 0) { UI.hide('unpricedSection'); UI.show('allPricedMsg'); }
    else {
      UI.hide('allPricedMsg');
      UI.html('unpricedWarning', `⚠️ ${unpriced.length} item(s) are missing pricing.`);
      UI.html('previewList', unpriced.map(i=>`<li><strong>RMS:</strong> <code>${i.item}</code> | <strong>Model:</strong> <code>${i.model_number||'N/A'}</code></li>`).join(''));
      UI.show('unpricedSection');
    }
    UI.show('pricingResults');
  },

  // ── Pricing Send ──
  async sendPricingAlert() {
    if (!_state.pricingResult) { toast('Run fetch first.', 'error'); return; }
    const btn = document.getElementById('sendAlertBtn');
    btn.innerHTML = '<span class="spinner"></span> Sending…'; btn.disabled = true;
    const { ok, data } = await api('POST', '/api/pricing/send-alert', { result: _state.pricingResult });
    btn.innerHTML = '📧 Send Pricing Alert Email(s)'; btn.disabled = false;
    if (ok) { UI.alert('pricingStatus', `✅ ${data.message}`, 'success'); toast(data.message, 'success'); }
    else { UI.alert('pricingStatus', `❌ ${data.error}`, 'error'); toast('Send failed.', 'error'); }
  },

  // ── PO622 ──
  async runPO622(e) {
    e.preventDefault(); UI.clearAlert('po622Status'); UI.hide('po622Results');
    const btn = document.getElementById('diagBtn');
    btn.innerHTML = '<span class="spinner"></span> Running…'; btn.disabled = true;
    const { ok, data } = await api('POST', '/api/po622/diagnose', { po_number: UI.val('po622PoNumber'), store_number: UI.val('po622StoreNumber') });
    btn.innerHTML = '🩺 Run Diagnostic'; btn.disabled = false;
    if (!ok) { UI.alert('po622Status', `❌ ${data.error}`, 'error'); return; }
    _state.po622Result = data;
    App._renderPO622(data);
  },

  _renderPO622(r) {
    const ov = (r.overview||[])[0] || {};
    const PT = {DS:'Drop Ship',RG:'Regular',SP:'Special Order',TR:'Transfer',RT:'Return',XD:'Cross-Dock',CO:'Consignment'};
    const PS = {OP:'Open',RCV:'Receiving',CLS:'Closed',CAN:'Cancelled',PND:'Pending',APP:'Approved',REJ:'Rejected',SHP:'Shipped',HLD:'On Hold'};
    const tc = (ov.po_type||'').toUpperCase(), sc = (ov.po_status||'').toUpperCase();

    UI.html('po622Metrics', [
      {l:'PO Number',v:ov.purchase_order_number||r.po_number},
      {l:'Type',v:tc||'—',s:PT[tc]||''}, {l:'Status',v:sc||'—',s:PS[sc]||''},
      {l:'Store',v:ov.store_number||r.store_number},
    ].map(m=>`<div class="metric-card"><div class="metric-label">${m.l}</div><div class="metric-value">${m.v}</div>${m.s?`<div class="metric-sub">${m.s}</div>`:''}</div>`).join(''));

    UI.html('po622Meta', [['Order Date',ov.order_date],['Est. Delivery',ov.estimated_delivery_date],['Close Date',ov.close_date],['Created By',ov.created_by]]
      .map(([l,v])=>`<span><strong>${l}:</strong> ${v||'—'}</span>`).join(''));

    // Root causes
    const CI = {ALREADY_FULLY_RECEIVED:'🔴',STUCK_REVERSAL:'🟠',DUPLICATE_SERIAL_NUMBER:'🔴',CONCURRENT_RECEIVE:'🟡',NO_ISSUE_FOUND:'🟢'};
    UI.html('rootCauseCards', (r.root_cause||[]).map(c=>`
      <div class="cause-card cause-${c.type}">
        <div class="cause-card-title">${CI[c.type]||'•'} ${c.type.replace(/_/g,' ')}</div>
        ${c.item?`<div class="cause-card-item">RMS Item: <code>${c.item}</code></div>`:''}
        <div class="cause-card-detail">${c.detail||''}</div>
        ${c.action?`<span class="cause-card-action">💡 ${c.action}</span>`:''}
      </div>`).join(''));

    // Line items
    const li = r.line_items||[];
    UI.html('po622LineBody', li.map(item => {
      const rem = item.remaining_to_receive;
      const bg = (rem!=null&&rem<=0) ? 'style="background:var(--error-bg)"' : '';
      const ic = (rem!=null&&rem<=0) ? '❌' : '✅';
      return `<tr ${bg}><td>${item.purchase_order_line_number??''}</td><td><code>${item.rms_item_number??''}</code></td><td><strong>${item.model_number||'—'}</strong></td><td>${item.item_description||''}</td><td>${item.quantity_ordered??''}</td><td>${item.fully_received_count??''}</td><td>${item.partial_received_count??''}</td><td>${item.reversed_count??''}</td><td>${item.stuck_reversal_count??''}</td><td>${ic} ${rem??''}</td></tr>`;
    }).join(''));

    // Dup serials
    const dups = r.duplicate_serials||[];
    if (dups.length) { UI.html('dupSerialsBody', dups.map(d=>`<tr><td><code>${d.manufacturer_serial_number}</code></td><td><code>${d.rms_item_number}</code></td><td>${d.model_number||'—'}</td><td>${d.times_used}</td><td>${JSON.stringify(d.received_ids)}</td></tr>`).join('')); UI.show('dupSerialsSection'); }
    else UI.hide('dupSerialsSection');

    // Timeline
    const EI = {PO_CREATED:'📦',FULL_RECEIVE:'✅',PARTIAL_RECEIVE:'⚠️',REVERSAL_COMPLETE:'🔄',REVERSAL_STUCK:'🔴'};
    const tl = r.timeline||[];
    if (tl.length) {
      UI.html('timelineList', tl.map(evt => {
        const t=evt.event_type||'', cls=t.includes('STUCK')?'evt-red':t.includes('FULL_RECEIVE')?'evt-green':'evt-gray';
        const model = evt.model_number ? ` | Model <code>${evt.model_number}</code>` : '';
        return `<div class="timeline-item ${cls}"><span class="timeline-icon">${EI[t]||'•'}</span><div class="timeline-body"><div class="timeline-time">${evt.event_time||''}</div><div class="timeline-type">${t}</div><div class="timeline-detail">${evt.performed_by||''} — ${evt.details||''}${model}</div></div></div>`;
      }).join(''));
    } else UI.html('timelineList', '<p style="color:var(--text-muted)">No timeline events.</p>');

    // Email prefill
    const pending = li.filter(i=>(i.remaining_to_receive||0)>0);
    const ml = pending.length ? pending.map(i=>`Model ${i.model_number||i.rms_item_number} (Line ${i.purchase_order_line_number}) is still pending.`).join('\n') : `Model(s) under PO ${r.po_number} are still pending.`;
    UI.set('modelInput', ml);
    App._refreshBody();
    UI.show('po622Results');
  },

  _refreshBody() {
    const r = _state.po622Result; if (!r) return;
    const name = UI.val('recipientName')||'Kevin Buxton';
    UI.set('emailBody', `Hi ${name},\n\nThe store ${r.store_number} is trying to receive PO ${r.po_number} but they are getting the below error:\n\n    "Received count exceeds quantity ordered"\n\n${UI.val('modelInput')}\n\nThe store would now like to receive this item. Could you please advise on the appropriate next steps.\n\nRegards,\nRacpad Support Team`);
  },

  async sendPO622Email(e) {
    e.preventDefault(); UI.clearAlert('po622EmailStatus');
    if (!_state.po622Result) { UI.alert('po622EmailStatus','❌ Run diagnostic first.','error'); return; }
    const btn = e.target.querySelector('button[type=submit]');
    const orig = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span> Sending…'; btn.disabled = true;
    const { ok, data } = await api('POST', '/api/po622/send-email', {
      po_number: _state.po622Result.po_number, store_number: _state.po622Result.store_number,
      recipient_email: UI.val('recipientEmail'), recipient_name: UI.val('recipientName'),
      email_body: UI.val('emailBody'), model_lines: UI.val('modelInput'),
    });
    btn.innerHTML = orig; btn.disabled = false;
    if (ok) { UI.alert('po622EmailStatus', `✅ ${data.message}`, 'success'); toast(data.message, 'success'); }
    else { UI.alert('po622EmailStatus', `❌ ${data.error}`, 'error'); }
  },

  exportReport() {
    const r = _state.po622Result; if (!r) { toast('No result to export.','error'); return; }
    const S = '='.repeat(70); const lines = [S,'  PO622 DIAGNOSTIC REPORT',`  PO: ${r.po_number}  |  Store: ${r.store_number}`,`  Generated: ${new Date().toLocaleString()}`,S];
    if (r.overview?.[0]) { lines.push('\n── PO OVERVIEW ──'); for (const [k,v] of Object.entries(r.overview[0])) lines.push(`  ${k}: ${v??'—'}`); }
    lines.push('\n── LINE ITEMS ──');
    for (const i of (r.line_items||[])) lines.push(`  Line ${i.purchase_order_line_number} | RMS ${i.rms_item_number} | Model ${i.model_number||'—'} | Ordered: ${i.quantity_ordered} | Full: ${i.fully_received_count} | Partial: ${i.partial_received_count} | Rev: ${i.reversed_count} | Stuck: ${i.stuck_reversal_count} | Rem: ${i.remaining_to_receive}`);
    lines.push('\n── TIMELINE ──');
    for (const e of (r.timeline||[])) lines.push(`  ${e.event_time} | ${e.event_type} | ${e.performed_by} | ${e.details||''}`);
    lines.push('\n'+S);
    const blob = new Blob([lines.join('\n')], {type:'text/plain'});
    const ts = new Date().toISOString().replace(/[:T]/g,'_').slice(0,19);
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `po622_report_${r.po_number}_${r.store_number}_${ts}.txt` });
    a.click(); URL.revokeObjectURL(a.href); toast('Report exported!','success');
  },

  // ── Sidebar utilities ──
  async runConnectivity() {
    UI.html('connectivityResult', '<div style="padding:6px 0"><span class="spinner spinner-blue"></span> Checking…</div>');
    const { ok, data } = await api('POST', '/api/diagnostics/connectivity');
    if (!ok) { UI.html('connectivityResult', `<div style="color:#fca5a5;font-size:.78rem">❌ ${data.error}</div>`); return; }
    UI.html('connectivityResult', data.checks.map(c=>`<div class="check-item"><span>${c.ok?'✅':'❌'}</span><span>${c.label}${c.message?' — '+c.message:''}</span></div>`).join(''));
  },

  _browseTarget() { return document.querySelector('input[name="browseDb"]:checked')?.value || 'rac'; },

  async listDatabases() {
    UI.html('schemaResult', '<div style="padding:6px 0;color:rgba(255,255,255,.6)"><span class="spinner"></span></div>');
    const { ok, data } = await api('POST', '/api/db/databases', { db_target: App._browseTarget() });
    if (!ok) { UI.html('schemaResult', `<div style="color:#fca5a5;font-size:.76rem">❌ ${data.error}</div>`); return; }
    UI.html('schemaResult', `<p style="font-size:.72rem;color:rgba(255,255,255,.6);margin:6px 0">Connected to: <strong style="color:#fff">${data.connected_to}</strong></p><table><thead><tr><th>Database</th></tr></thead><tbody>${data.databases.map(d=>`<tr><td>${d}</td></tr>`).join('')}</tbody></table>`);
  },

  async listSchemas() {
    UI.html('schemaResult', '<div style="padding:6px 0;color:rgba(255,255,255,.6)"><span class="spinner"></span></div>');
    const { ok, data } = await api('POST', '/api/db/schemas', { db_target: App._browseTarget() });
    if (!ok) { UI.html('schemaResult', `<div style="color:#fca5a5;font-size:.76rem">❌ ${data.error}</div>`); return; }
    UI.html('schemaResult', `<p style="font-size:.72rem;color:rgba(255,255,255,.6);margin:6px 0">DB: <strong style="color:#fff">${data.connected_to}</strong> | Schemas: <strong style="color:#fff">${data.schemas.join(', ')}</strong></p><table><thead><tr><th>Schema</th><th>Table</th></tr></thead><tbody>${data.tables.map(r=>`<tr><td>${r.schema}</td><td>${r.table}</td></tr>`).join('')}</tbody></table>`);
  },
};

/* ─────────────────── Boot ─────────────────── */
function boot() {
  App.init();
  document.getElementById('recipientName')?.addEventListener('input', () => App._refreshBody());
  document.getElementById('modelInput')?.addEventListener('input', () => App._refreshBody());
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
