// ── State ────────────────────────────────────────────────
let currentUser = null;
let token = null;
let currentView = 'cases';
let _idleTimer = null;
const IDLE_TIMEOUT_MS = 5 * 60 * 1000;
let cases = [];
let selectedSimCase = null;
let selectedMode = null;
let selectedAnalysis = 'comprehensive';
let selectedDocType = 'evidence_list';
let sessionId = null;
let detailCaseId = null;

const TYPE_LABELS = {
  civil: '民事', criminal: '刑事', administrative: '行政',
  commercial: '商事', labor: '劳动争议', intellectual_property: '知识产权',
};
const ROLE_LABELS = { plaintiff: '原告', defendant: '被告' };
const MODE_LABELS = {
  adversarial: '对抗辩论', full_trial: '完整庭审',
  witness_exam: '证人质询', argument_analysis: '即时分析',
};

// ── API Helper ───────────────────────────────────────────
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { logout(); throw new Error('登录已过期'); }
  return res;
}

// ── Init ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSiteConfig();
  const saved = localStorage.getItem('auth');
  if (saved) {
    try {
      const data = JSON.parse(saved);
      token = data.token;
      currentUser = data.user;
      enterApp();
    } catch { localStorage.removeItem('auth'); }
  }
});

async function loadSiteConfig() {
  try {
    const res = await fetch('/api/site-config');
    const cfg = await res.json();
    if (cfg.firm_name) {
      const loginEl = document.getElementById('login-firm-name');
      if (loginEl) { loginEl.textContent = cfg.firm_name; loginEl.classList.remove('hidden'); }
      const sidebarEl = document.getElementById('sidebar-firm-name');
      if (sidebarEl) sidebarEl.textContent = cfg.firm_name;
      document.title = `AI 模拟法庭 - ${cfg.firm_name}`;
    }
    if (cfg.firm_logo) {
      const loginImg = document.getElementById('login-logo-img');
      const loginIcon = document.getElementById('login-logo-icon');
      const loginWrap = document.getElementById('login-logo-wrap');
      if (loginImg && loginIcon) {
        loginImg.src = cfg.firm_logo;
        loginImg.classList.remove('hidden');
        loginIcon.classList.add('hidden');
        if (loginWrap) {
          loginWrap.style.background = 'none';
          loginWrap.style.border = 'none';
          loginWrap.style.boxShadow = 'none';
        }
      }
      const sideImg = document.getElementById('sidebar-logo-img');
      const sideIcon = document.getElementById('sidebar-logo-icon');
      const sideWrap = document.getElementById('sidebar-logo-wrap');
      if (sideImg && sideIcon) {
        sideImg.src = cfg.firm_logo;
        sideImg.classList.remove('hidden');
        sideIcon.classList.add('hidden');
        if (sideWrap) {
          sideWrap.style.background = 'none';
          sideWrap.style.border = 'none';
          sideWrap.style.boxShadow = 'none';
        }
      }
    }
  } catch (e) { /* config is optional */ }
}

// ── Auth ─────────────────────────────────────────────────
async function handleAuth(e) {
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form));
  const errEl = document.getElementById('auth-error');
  errEl.classList.add('hidden');

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: data.username, password: data.password }),
    });
    const body = await res.json();
    if (!res.ok) {
      errEl.textContent = body.detail || '登录失败';
      errEl.classList.remove('hidden');
      return;
    }
    token = body.access_token;
    currentUser = body.user;
    localStorage.setItem('auth', JSON.stringify({ token, user: currentUser }));
    enterApp();
  } catch (err) {
    errEl.textContent = '网络错误: ' + err.message;
    errEl.classList.remove('hidden');
  }
}

function enterApp() {
  document.getElementById('login-page').classList.add('hidden');
  document.getElementById('main-app').classList.remove('hidden');
  const name = currentUser.display_name || currentUser.username;
  document.getElementById('user-name').textContent = name;
  document.getElementById('user-avatar').textContent = name.charAt(0).toUpperCase();
  document.getElementById('user-role').textContent = currentUser.role === 'admin' ? '管理员' : '律师';
  if (currentUser.role === 'admin') {
    document.getElementById('nav-admin-group').classList.remove('hidden');
  }
  showView('cases');
  _startIdleTimer();
}

function logout() {
  _stopIdleTimer();
  token = null;
  currentUser = null;
  localStorage.removeItem('auth');
  document.getElementById('main-app').classList.add('hidden');
  document.getElementById('login-page').classList.remove('hidden');
  document.getElementById('auth-form').reset();
  document.getElementById('nav-admin-group').classList.add('hidden');
}

function _resetIdleTimer() {
  if (!token) return;
  clearTimeout(_idleTimer);
  _idleTimer = setTimeout(() => { alert('您已超过5分钟未操作，系统自动退出登录。'); logout(); }, IDLE_TIMEOUT_MS);
}
function _startIdleTimer() {
  ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'click'].forEach(evt =>
    document.addEventListener(evt, _resetIdleTimer, { passive: true })
  );
  _resetIdleTimer();
}
function _stopIdleTimer() {
  clearTimeout(_idleTimer);
  ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'click'].forEach(evt =>
    document.removeEventListener(evt, _resetIdleTimer)
  );
}

// ── Navigation ───────────────────────────────────────────
const ADMIN_VIEWS = ['admin-monitor', 'admin-users', 'admin-stats', 'admin-backup', 'admin-llm'];

function showView(view) {
  if (ADMIN_VIEWS.includes(view) && (!currentUser || currentUser.role !== 'admin')) return;
  document.querySelectorAll('.content-panel').forEach(el => el.classList.add('hidden'));
  document.getElementById(`view-${view}`).classList.remove('hidden');
  document.querySelectorAll('.sidebar-item').forEach(b => b.classList.remove('active'));
  const navEl = document.getElementById(`nav-${view}`);
  if (navEl) navEl.classList.add('active');
  currentView = view;
  if (view === 'cases') loadCases();
  if (view === 'simulate' || view === 'analysis' || view === 'documents') populateCaseSelects();
  if (view === 'admin-monitor') loadMonitor();
  if (view === 'admin-users') loadUsers();
  if (view === 'admin-stats') loadStatistics();
  if (view === 'admin-backup') { loadBackups(); loadSchedule(); }
  if (view === 'admin-llm') loadLlmConfig();
}

// ── Case Management ──────────────────────────────────────
async function loadCases() {
  try {
    const res = await api('/api/cases');
    cases = await res.json();
    renderCaseList();
  } catch (e) { console.error(e); }
}

function renderCaseList() {
  const list = document.getElementById('case-list');
  const empty = document.getElementById('case-empty');
  document.getElementById('case-detail-wrapper').classList.add('hidden');
  list.classList.remove('hidden');
  if (cases.length === 0) { list.innerHTML = ''; empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');
  list.innerHTML = cases.map(c => `
    <div class="case-card" onclick="viewCase(${c.id})">
      <div class="flex items-center justify-between mb-2">
        <span class="case-type-badge ${c.case_type}">${TYPE_LABELS[c.case_type] || c.case_type}</span>
        <span class="text-xs text-gray-500">${ROLE_LABELS[c.our_role] || ''}</span>
      </div>
      <h3 class="font-semibold mb-1.5 truncate" style="color:#111827">${esc(c.title)}</h3>
      <p class="text-xs text-gray-500 line-clamp-2">${esc(c.case_facts.substring(0, 100))}...</p>
      ${currentUser && currentUser.role === 'admin' && c.owner_display_name ? `<div class="text-xs text-blue-600 mt-1"><i class="ri-user-line"></i> ${esc(c.owner_display_name || c.owner_name)}</div>` : ''}
      <div class="flex items-center justify-between mt-3 pt-2" style="border-top:1px solid #e5e7eb">
        <span class="text-xs text-gray-400">${c.court_name || '未指定法院'}</span>
        <div class="flex gap-2">
          <button onclick="event.stopPropagation(); startSimWith(${c.id})"
            class="text-xs text-amber-600 hover:text-amber-700 font-medium">模拟</button>
          <button onclick="event.stopPropagation(); viewCase(${c.id})"
            class="text-xs text-blue-500 hover:text-blue-600 font-medium">编辑</button>
          <button onclick="event.stopPropagation(); deleteCase(${c.id})"
            class="text-xs text-gray-400 hover:text-red-500">删除</button>
        </div>
      </div>
    </div>`).join('');
}

function showCaseForm() {
  document.getElementById('case-form-wrapper').classList.remove('hidden');
  document.getElementById('case-list').classList.add('hidden');
  document.getElementById('case-empty').classList.add('hidden');
  document.getElementById('case-detail-wrapper').classList.add('hidden');
}
function hideCaseForm() {
  document.getElementById('case-form-wrapper').classList.add('hidden');
  document.getElementById('case-form').reset();
  renderCaseList();
}

async function submitCase(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const res = await api('/api/cases', { method: 'POST', body: JSON.stringify(data) });
    if (!res.ok) throw new Error(await res.text());
    await loadCases();
    hideCaseForm();
  } catch (err) { alert('保存失败: ' + err.message); }
}

function viewCase(id) { showCaseDetail(id); }

async function deleteCase(id) {
  if (!confirm('确定要删除此案件吗？')) return;
  await api(`/api/cases/${id}`, { method: 'DELETE' });
  await loadCases();
}

function startSimWith(id) {
  showView('simulate');
  document.getElementById('sim-case-select').value = id;
  selectedSimCase = id;
  updateStartBtn();
  loadCaseHistory(id);
}

// ── Case Detail & Records ───────────────────────────────
const EDIT_FIELDS = ['title','case_type','court_name','our_role','case_facts',
  'our_claims','our_evidence','our_legal_basis','opposing_claims',
  'opposing_evidence','opposing_legal_basis','judge_tendencies','additional_context'];

async function showCaseDetail(id) {
  detailCaseId = id;
  let c = cases.find(x => x.id === id);
  if (!c) {
    try { const res = await api(`/api/cases/${id}`); c = await res.json(); } catch { return; }
  }
  document.getElementById('detail-case-title').textContent = c.title;
  document.getElementById('detail-case-meta').textContent =
    `${TYPE_LABELS[c.case_type] || c.case_type} · ${ROLE_LABELS[c.our_role] || ''} · ${c.court_name || '未指定法院'}`;

  EDIT_FIELDS.forEach(f => {
    const el = document.getElementById('edit-' + f);
    if (el) el.value = c[f] || '';
  });

  document.getElementById('case-list').classList.add('hidden');
  document.getElementById('case-empty').classList.add('hidden');
  document.getElementById('case-detail-wrapper').classList.remove('hidden');
  switchDetailTab('info');
  hideRecordForm();
  await loadRecords(id);
}

function switchDetailTab(tab) {
  document.querySelectorAll('.detail-tab').forEach(b => b.classList.remove('active'));
  document.querySelector(`.detail-tab[data-tab="${tab}"]`).classList.add('active');
  document.getElementById('detail-tab-info').classList.toggle('hidden', tab !== 'info');
  document.getElementById('detail-tab-materials').classList.toggle('hidden', tab !== 'materials');
}

async function submitCaseEdit(e) {
  e.preventDefault();
  if (!detailCaseId) return;
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const res = await api(`/api/cases/${detailCaseId}`, { method: 'PUT', body: JSON.stringify(data) });
    if (!res.ok) throw new Error(await res.text());
    const updated = await res.json();
    const idx = cases.findIndex(x => x.id === detailCaseId);
    if (idx >= 0) Object.assign(cases[idx], updated);
    document.getElementById('detail-case-title').textContent = updated.title;
    document.getElementById('detail-case-meta').textContent =
      `${TYPE_LABELS[updated.case_type] || updated.case_type} · ${ROLE_LABELS[updated.our_role] || ''} · ${updated.court_name || '未指定法院'}`;
    alert('案件信息已更新');
  } catch (err) { alert('保存失败: ' + err.message); }
}

async function deleteCaseFromDetail() {
  if (!detailCaseId) return;
  if (!confirm('确定要删除此案件？关联的所有材料、模拟和分析记录也将被删除。')) return;
  try {
    await api(`/api/cases/${detailCaseId}`, { method: 'DELETE' });
    detailCaseId = null;
    await loadCases();
  } catch (err) { alert('删除失败: ' + err.message); }
}

function hideCaseDetail() {
  document.getElementById('case-detail-wrapper').classList.add('hidden');
  detailCaseId = null;
  renderCaseList();
}

function startSimFromDetail() {
  if (detailCaseId) startSimWith(detailCaseId);
}
function startAnalysisFromDetail() {
  if (detailCaseId) {
    showView('analysis');
    document.getElementById('analysis-case-select').value = detailCaseId;
    loadCaseHistory(detailCaseId);
  }
}
function startDocGenFromDetail() {
  if (detailCaseId) {
    showView('documents');
    document.getElementById('doc-case-select').value = detailCaseId;
    loadDocHistory(detailCaseId);
  }
}

function showRecordForm() {
  document.getElementById('record-form-wrapper').classList.remove('hidden');
}
function hideRecordForm() {
  document.getElementById('record-form-wrapper').classList.add('hidden');
  document.getElementById('record-title').value = '';
  document.getElementById('record-content').value = '';
  document.getElementById('record-file').value = '';
  document.getElementById('record-file-label').textContent = '点击选择文件或拖放';
}

function onRecordFileChange(input) {
  const label = document.getElementById('record-file-label');
  label.textContent = input.files.length ? input.files[0].name : '点击选择文件或拖放';
}

async function submitRecord() {
  const title = document.getElementById('record-title').value.trim();
  if (!title) { alert('请输入记录标题'); return; }
  const recordType = document.getElementById('record-type').value;
  const contentText = document.getElementById('record-content').value.trim();
  const fileInput = document.getElementById('record-file');
  const file = fileInput.files.length ? fileInput.files[0] : null;

  if (!contentText && !file) { alert('请上传文件或输入文字内容'); return; }

  const formData = new FormData();
  formData.append('title', title);
  formData.append('record_type', recordType);
  formData.append('content_text', contentText);
  if (file) formData.append('file', file);

  try {
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`/api/cases/${detailCaseId}/records`, {
      method: 'POST', headers, body: formData,
    });
    if (!res.ok) { const e = await res.json(); alert('保存失败: ' + (e.detail || '未知错误')); return; }
    hideRecordForm();
    await loadRecords(detailCaseId);
  } catch (err) { alert('网络错误: ' + err.message); }
}

async function loadRecords(caseId) {
  try {
    const res = await api(`/api/cases/${caseId}/records`);
    const records = await res.json();
    const list = document.getElementById('records-list');
    const empty = document.getElementById('records-empty');
    document.getElementById('records-count').textContent = records.length;
    if (records.length === 0) { list.innerHTML = ''; empty.classList.remove('hidden'); return; }
    empty.classList.add('hidden');
    const RTYPE = { complaint: '起诉状/答辩状', evidence: '证据材料', contract: '合同/协议', hearing: '庭审笔录', ruling: '裁定/判决书', letter: '律师函/通知', other: '其他' };
    list.innerHTML = records.map(r => `
      <div class="record-item">
        <div class="flex items-start gap-3">
          <div class="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${_matBg(r.record_type)}">
            <i class="${_matIcon(r.record_type)}"></i>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-medium text-sm" style="color:#111827">${esc(r.title)}</span>
              <span class="text-xs text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">${RTYPE[r.record_type] || r.record_type}</span>
            </div>
            ${r.file_name ? `<div class="text-xs text-gray-500"><i class="ri-attachment-line"></i> ${esc(r.file_name)}</div>` : ''}
            <div class="text-xs text-gray-600 mt-1">${esc(r.content_text.substring(0, 120))}${r.content_text.length > 120 ? '...' : ''}</div>
            <div class="text-xs text-gray-700 mt-1">${new Date(r.created_at).toLocaleString('zh-CN')}</div>
          </div>
          <div class="flex gap-1 flex-shrink-0">
            <button onclick="previewRecord(${r.id})" class="btn-ghost text-xs" title="查看"><i class="ri-eye-line"></i></button>
            <button onclick="deleteRecord(${r.id})" class="btn-ghost danger text-xs" title="删除"><i class="ri-delete-bin-line"></i></button>
          </div>
        </div>
      </div>`).join('');
  } catch (e) { console.error(e); }
}

let _previewRecordCache = {};
async function previewRecord(recordId) {
  if (_previewRecordCache[recordId]) {
    showRecordModal(_previewRecordCache[recordId]);
    return;
  }
  try {
    const res = await api(`/api/cases/${detailCaseId}/records`);
    const records = await res.json();
    const r = records.find(x => x.id === recordId);
    if (r) {
      _previewRecordCache[recordId] = r;
      showRecordModal(r);
    }
  } catch (e) { console.error(e); }
}

function showRecordModal(record) {
  const existing = document.getElementById('record-modal');
  if (existing) existing.remove();
  const modal = document.createElement('div');
  modal.id = 'record-modal';
  modal.className = 'record-modal-overlay';
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
  modal.innerHTML = `
    <div class="record-modal-content">
      <div class="flex items-center justify-between mb-4">
        <h3 class="font-bold text-lg">${esc(record.title)}</h3>
        <button onclick="document.getElementById('record-modal').remove()" class="btn-ghost"><i class="ri-close-line text-xl"></i></button>
      </div>
      <div class="prose-dark text-sm whitespace-pre-wrap max-h-96 overflow-y-auto">${esc(record.content_text)}</div>
    </div>`;
  document.body.appendChild(modal);
}

async function deleteRecord(recordId) {
  if (!confirm('确定删除此记录？')) return;
  try {
    await api(`/api/records/${recordId}`, { method: 'DELETE' });
    delete _previewRecordCache[recordId];
    await loadRecords(detailCaseId);
  } catch (e) { alert('删除失败: ' + e.message); }
}

// ── Case History (shared for sim/analysis) ──────────────
async function loadCaseHistory(caseId) {
  try {
    const res = await api(`/api/cases/${caseId}/history`);
    const data = await res.json();
    renderSimHistory(data.sessions || []);
    renderAnalysisHistory(data.analyses || []);
    const hasContext = (data.sessions && data.sessions.length > 0) || (data.analyses && data.analyses.length > 0);
    const simHint = document.getElementById('sim-context-hint');
    const anaHint = document.getElementById('analysis-context-hint');
    if (simHint) simHint.classList.toggle('hidden', !hasContext);
    if (anaHint) anaHint.classList.toggle('hidden', !hasContext);
  } catch (e) { console.error(e); }
}

function renderSimHistory(sessions) {
  const panel = document.getElementById('sim-history-panel');
  const list = document.getElementById('sim-history-list');
  if (!sessions.length) { panel.classList.add('hidden'); return; }
  panel.classList.remove('hidden');
  list.innerHTML = sessions.slice(0, 10).map(s => `
    <div class="history-item">
      <div class="flex items-center gap-2">
        <i class="ri-message-3-line text-blue-500 text-sm"></i>
        <span class="text-sm font-medium" style="color:#374151">${MODE_LABELS[s.mode] || s.mode}</span>
      </div>
      <span class="text-xs text-gray-600">${new Date(s.created_at).toLocaleString('zh-CN')}</span>
    </div>`).join('');
}

function renderAnalysisHistory(analyses) {
  const panel = document.getElementById('analysis-history-panel');
  const list = document.getElementById('analysis-history-list');
  if (!analyses.length) { panel.classList.add('hidden'); return; }
  panel.classList.remove('hidden');
  const FOCUS_LABELS = { comprehensive: '全面分析', weakness: '风险识别', strategy: '庭审策略', questions: '问题预测' };
  list.innerHTML = analyses.slice(0, 10).map(a => `
    <div class="history-item" onclick="showHistoryAnalysis(${a.id})">
      <div class="flex items-center gap-2">
        <i class="ri-file-text-line text-purple-500 text-sm"></i>
        <span class="text-sm font-medium" style="color:#374151">${FOCUS_LABELS[a.focus] || a.focus}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-xs text-gray-600">${new Date(a.created_at).toLocaleString('zh-CN')}</span>
        <i class="ri-eye-line text-xs text-gray-600"></i>
      </div>
    </div>`).join('');
}

async function showHistoryAnalysis(analysisId) {
  try {
    const caseId = document.getElementById('analysis-case-select').value;
    if (!caseId) return;
    const res = await api(`/api/cases/${caseId}/history`);
    const data = await res.json();
    const a = (data.analyses || []).find(x => x.id === analysisId);
    if (!a) return;
    document.getElementById('analysis-content').innerHTML = formatText(a.analysis_text);
    document.getElementById('analysis-result').classList.remove('hidden');
  } catch (e) { console.error(e); }
}

// ── Simulation ───────────────────────────────────────────
function populateCaseSelects() {
  const opts = cases.map(c =>
    `<option value="${c.id}">${esc(c.title)} (${TYPE_LABELS[c.case_type]})</option>`
  ).join('');
  const def = '<option value="">-- 请选择案件 --</option>';
  ['sim-case-select', 'analysis-case-select', 'doc-case-select'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = def + opts;
  });
}

function onSimCaseChange() {
  const v = document.getElementById('sim-case-select').value;
  selectedSimCase = v ? parseInt(v) : null;
  updateStartBtn();
  if (selectedSimCase) loadCaseHistory(selectedSimCase);
}
function selectMode(mode) {
  selectedMode = mode;
  document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('active'));
  document.querySelector(`[data-mode="${mode}"]`).classList.add('active');
  updateStartBtn();
}
function updateStartBtn() {
  document.getElementById('btn-start-sim').disabled = !(selectedSimCase && selectedMode);
}

function startSimulation() {
  if (!selectedSimCase || !selectedMode) return;
  sessionId = null;
  document.getElementById('sim-setup').classList.add('hidden');
  document.getElementById('sim-chat').classList.remove('hidden');
  const c = cases.find(x => x.id === selectedSimCase);
  document.getElementById('sim-title').textContent = c ? c.title : '庭审模拟';
  document.getElementById('sim-mode-badge').textContent = MODE_LABELS[selectedMode];
  document.getElementById('chat-messages').innerHTML = '';
  addSystemMessage(getOpeningHint());
}
function getOpeningHint() {
  const h = {
    adversarial: '模拟已就绪。AI 将扮演对方代理律师与你进行法庭辩论。\n请输入你的开庭陈述或辩论观点开始。',
    full_trial: '完整庭审模拟已就绪。AI 将同时扮演审判长和对方律师。\n请以你的开庭陈述开始。',
    witness_exam: '证人质询模拟已就绪。AI 将扮演案件相关证人。\n请开始提问。',
    argument_analysis: '即时分析模式已就绪。输入你的论点，AI 将从对方视角进行点评和反馈。',
  };
  return h[selectedMode] || '模拟已就绪，请开始发言。';
}
function backToSetup() {
  document.getElementById('sim-chat').classList.add('hidden');
  document.getElementById('sim-setup').classList.remove('hidden');
}
function clearChat() {
  sessionId = null;
  document.getElementById('chat-messages').innerHTML = '';
  addSystemMessage(getOpeningHint());
}

function addSystemMessage(text) {
  const el = document.getElementById('chat-messages');
  el.innerHTML += `<div class="text-center"><span class="system-msg">${esc(text)}</span></div>`;
  el.scrollTop = el.scrollHeight;
}
function addMessage(role, label, text) {
  const el = document.getElementById('chat-messages');
  const cls = role === 'user' ? 'msg-user' : 'msg-ai';
  el.innerHTML += `<div class="msg ${cls}">
    <div class="msg-header">${esc(label)}</div><div>${formatText(text)}</div></div>`;
  el.scrollTop = el.scrollHeight;
}
function showTyping() {
  const el = document.getElementById('chat-messages');
  el.innerHTML += `<div id="typing" class="typing-indicator"><span></span><span></span><span></span></div>`;
  el.scrollTop = el.scrollHeight;
}
function hideTyping() { const t = document.getElementById('typing'); if (t) t.remove(); }

async function sendMessage(e) {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMessage('user', '我方律师', text);
  showTyping();
  const sendBtn = document.getElementById('btn-send');
  sendBtn.disabled = true;
  try {
    const res = await api('/api/simulate', {
      method: 'POST',
      body: JSON.stringify({ case_id: selectedSimCase, mode: selectedMode, user_message: text, session_id: sessionId }),
    });
    hideTyping();
    if (!res.ok) { const err = await res.json(); addSystemMessage('出错: ' + (err.detail || '请求失败')); return; }
    const data = await res.json();
    sessionId = data.session_id;
    const rl = { opposing_counsel: '对方律师', full_trial: '庭审回应', witness: '证人', analyst: '策略分析师' };
    addMessage('ai', rl[data.role] || 'AI', data.content);
  } catch (err) { hideTyping(); addSystemMessage('网络错误: ' + err.message); }
  finally { sendBtn.disabled = false; input.focus(); }
}

function handleChatKey(e) {
  if (e.ctrlKey && e.key === 'Enter') {
    e.preventDefault();
    document.querySelector('#sim-chat form').dispatchEvent(new Event('submit'));
  }
}

// ── Analysis ─────────────────────────────────────────────
function onAnalysisCaseChange() {
  const v = document.getElementById('analysis-case-select').value;
  if (v) loadCaseHistory(parseInt(v));
}

function selectAnalysis(type) {
  selectedAnalysis = type;
  document.querySelectorAll('.analysis-card').forEach(c => c.classList.remove('active'));
  document.querySelector(`[data-analysis="${type}"]`).classList.add('active');
}
async function runAnalysis() {
  const caseId = document.getElementById('analysis-case-select').value;
  if (!caseId) { alert('请先选择案件'); return; }
  document.getElementById('analysis-result').classList.add('hidden');
  document.getElementById('analysis-loading').classList.remove('hidden');
  document.getElementById('btn-analyze').disabled = true;
  try {
    const res = await api('/api/analyze', {
      method: 'POST',
      body: JSON.stringify({ case_id: parseInt(caseId), focus: selectedAnalysis }),
    });
    if (!res.ok) { const err = await res.json(); alert('分析失败: ' + (err.detail || '未知错误')); return; }
    const data = await res.json();
    document.getElementById('analysis-content').innerHTML = formatText(data.analysis);
    document.getElementById('analysis-result').classList.remove('hidden');
  } catch (err) { alert('网络错误: ' + err.message); }
  finally {
    document.getElementById('analysis-loading').classList.add('hidden');
    document.getElementById('btn-analyze').disabled = false;
  }
}

// ── Document Generation ──────────────────────────────────
const DOC_TYPE_LABELS = {
  evidence_list: '证据清单', legal_opinion: '代理词/辩护词',
  cross_exam: '质证意见', pretrial_checklist: '庭前准备清单',
  debate_outline: '辩论提纲', closing_statement: '结辩词',
};

function onDocCaseChange() {
  const v = document.getElementById('doc-case-select').value;
  if (v) loadDocHistory(parseInt(v));
}

function selectDocType(type) {
  selectedDocType = type;
  document.querySelectorAll('[data-doctype]').forEach(c => c.classList.remove('active'));
  document.querySelector(`[data-doctype="${type}"]`).classList.add('active');
}

async function loadDocHistory(caseId) {
  try {
    const res = await api(`/api/cases/${caseId}/documents`);
    const docs = await res.json();
    const panel = document.getElementById('doc-history-panel');
    const list = document.getElementById('doc-history-list');
    if (!docs.length) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    list.innerHTML = docs.map(d => `
      <div class="history-item">
        <div class="flex items-center gap-2 flex-1 min-w-0">
          <i class="ri-file-text-line text-blue-500 text-sm"></i>
          <span class="text-sm font-medium truncate" style="color:#374151">${esc(d.doc_title)}</span>
          <span class="text-xs text-gray-500">${new Date(d.created_at).toLocaleString('zh-CN')}</span>
        </div>
        <div class="flex gap-1 flex-shrink-0">
          <button onclick="viewGeneratedDoc(${d.id})" class="btn-ghost text-xs"><i class="ri-eye-line"></i></button>
          <button onclick="deleteGeneratedDoc(${d.id})" class="btn-ghost danger text-xs"><i class="ri-delete-bin-line"></i></button>
        </div>
      </div>`).join('');
  } catch (e) { console.error(e); }
}

async function generateDocument() {
  const caseId = document.getElementById('doc-case-select').value;
  if (!caseId) { alert('请先选择案件'); return; }
  document.getElementById('doc-result').classList.add('hidden');
  document.getElementById('doc-loading').classList.remove('hidden');
  document.getElementById('btn-gen-doc').disabled = true;
  try {
    const res = await api(`/api/cases/${caseId}/generate-document`, {
      method: 'POST',
      body: JSON.stringify({ doc_type: selectedDocType }),
    });
    if (!res.ok) { const err = await res.json(); alert('生成失败: ' + (err.detail || '未知错误')); return; }
    const doc = await res.json();
    document.getElementById('doc-result-title').textContent = doc.doc_title;
    document.getElementById('doc-content').innerHTML = formatText(doc.content);
    document.getElementById('doc-result').classList.remove('hidden');
    loadDocHistory(parseInt(caseId));
  } catch (err) { alert('网络错误: ' + err.message); }
  finally {
    document.getElementById('doc-loading').classList.add('hidden');
    document.getElementById('btn-gen-doc').disabled = false;
  }
}

async function viewGeneratedDoc(docId) {
  try {
    const res = await api(`/api/documents/${docId}`);
    if (!res.ok) return;
    const doc = await res.json();
    document.getElementById('doc-result-title').textContent = doc.doc_title;
    document.getElementById('doc-content').innerHTML = formatText(doc.content);
    document.getElementById('doc-result').classList.remove('hidden');
  } catch (e) { console.error(e); }
}

async function deleteGeneratedDoc(docId) {
  if (!confirm('确定删除此文书？')) return;
  try {
    await api(`/api/documents/${docId}`, { method: 'DELETE' });
    const caseId = document.getElementById('doc-case-select').value;
    if (caseId) loadDocHistory(parseInt(caseId));
  } catch (e) { alert('删除失败: ' + e.message); }
}

function copyDocContent() {
  const el = document.getElementById('doc-content');
  const text = el.innerText || el.textContent;
  navigator.clipboard.writeText(text).then(() => alert('已复制到剪贴板')).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
    alert('已复制到剪贴板');
  });
}

// ── Admin ────────────────────────────────────────────────
async function loadStatistics() {
  try {
    const res = await api('/api/admin/statistics');
    const d = await res.json();

    document.getElementById('stats-summary').innerHTML = `
      <div class="stat-card"><div class="stat-value">${d.total_users}</div><div class="stat-label">总用户数</div></div>
      <div class="stat-card"><div class="stat-value">${d.total_cases}</div><div class="stat-label">总案件数</div></div>
      <div class="stat-card"><div class="stat-value">${d.total_sessions}</div><div class="stat-label">总模拟次数</div></div>`;

    document.getElementById('stats-by-user').innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th>用户</th><th style="text-align:center">角色</th><th>案件</th><th>模拟</th>
        </tr></thead>
        <tbody>${d.by_user.map(u => `<tr>
          <td><span class="font-medium">${esc(u.display_name || u.username)}</span></td>
          <td style="text-align:center"><span class="role-badge ${u.role}">${u.role === 'admin' ? '管理员' : '用户'}</span></td>
          <td>${u.case_count}</td>
          <td>${u.session_count}</td>
        </tr>`).join('')}</tbody>
      </table>`;

    document.getElementById('stats-by-type').innerHTML = d.by_case_type.length ? `
      <table class="data-table">
        <thead><tr><th>类型</th><th>数量</th></tr></thead>
        <tbody>${d.by_case_type.map(t => `<tr>
          <td><span class="case-type-badge ${t.case_type}">${TYPE_LABELS[t.case_type] || t.case_type}</span></td>
          <td>${t.count}</td>
        </tr>`).join('')}</tbody>
      </table>` : '<p class="text-gray-500 text-sm text-center py-6">暂无数据</p>';

    document.getElementById('stats-recent').innerHTML = d.recent_cases.length ? `
      <table class="data-table">
        <thead><tr><th>案件</th><th>律师</th><th>时间</th></tr></thead>
        <tbody>${d.recent_cases.map(c => `<tr>
          <td class="truncate" style="max-width:200px">${esc(c.title)}</td>
          <td>${esc(c.owner || '-')}</td>
          <td class="text-xs whitespace-nowrap">${new Date(c.created_at).toLocaleDateString('zh-CN')}</td>
        </tr>`).join('')}</tbody>
      </table>` : '<p class="text-gray-500 text-sm text-center py-6">暂无案件</p>';
  } catch (e) { console.error(e); }
}

async function loadMonitor() {
  loadDbHealth();
  try {
    const res = await api('/api/admin/monitor');
    const d = await res.json();
    const upH = Math.floor(d.uptime_seconds / 3600);
    const upM = Math.floor((d.uptime_seconds % 3600) / 60);
    document.getElementById('monitor-cards').innerHTML = `
      <div class="stat-card"><div class="stat-value">${d.user_count}</div><div class="stat-label">用户数</div></div>
      <div class="stat-card"><div class="stat-value">${d.case_count}</div><div class="stat-label">案件数</div></div>
      <div class="stat-card"><div class="stat-value">${d.session_count}</div><div class="stat-label">模拟会话</div></div>
      <div class="stat-card"><div class="stat-value">${d.database_size}</div><div class="stat-label">数据库大小</div></div>
      <div class="stat-card"><div class="stat-value">${d.active_connections}</div><div class="stat-label">活跃连接</div></div>
      <div class="stat-card"><div class="stat-value">${d.pool_size} / ${d.pool_free}</div><div class="stat-label">连接池</div></div>
      <div class="stat-card col-span-2"><div class="stat-value">${upH}h ${upM}m</div><div class="stat-label">服务运行时长</div></div>`;
    if (d.tables && d.tables.length > 0) {
      document.getElementById('monitor-tables').innerHTML = `
        <table class="data-table">
          <thead><tr>
            <th>表名</th><th>行数</th><th>大小</th>
          </tr></thead>
          <tbody>${d.tables.map(t => `<tr>
            <td>${esc(t.name)}</td><td style="text-align:right">${t.row_count}</td><td>${t.size}</td>
          </tr>`).join('')}</tbody>
        </table>`;
    }
  } catch (e) { console.error(e); }
}

async function loadDbHealth() {
  const dot = document.getElementById('db-health-dot');
  const badge = document.getElementById('db-health-badge');
  const msg = document.getElementById('db-health-msg');
  const detail = document.getElementById('db-health-detail');
  dot.className = 'w-3 h-3 rounded-full flex-shrink-0 mt-1.5 bg-yellow-400 animate-pulse';
  badge.className = 'text-xs px-2 py-0.5 rounded-full bg-yellow-50 text-yellow-600';
  badge.textContent = '检测中';
  msg.textContent = '正在检测数据库连接...';
  msg.className = 'text-xs mt-1 text-yellow-600';
  detail.classList.add('hidden');
  try {
    const res = await api('/api/admin/db-health');
    const h = await res.json();
    if (h.status === 'healthy') {
      dot.className = 'w-3 h-3 rounded-full flex-shrink-0 mt-1.5 bg-green-500';
      badge.className = 'text-xs px-2 py-0.5 rounded-full bg-green-50 text-green-700';
      badge.textContent = '正常运行';
      msg.textContent = h.message;
      msg.className = 'text-xs mt-1 text-green-600';
      const ver = (h.version || '').split(' ').slice(0, 2).join(' ');
      detail.innerHTML = `
        <div><span class="text-gray-400">版本:</span> <span class="font-medium text-gray-700">${esc(ver)}</span></div>
        <div><span class="text-gray-400">数据库:</span> <span class="font-medium text-gray-700">${esc(h.database)}</span></div>
        <div><span class="text-gray-400">运行时长:</span> <span class="font-medium text-gray-700">${esc(h.uptime)}</span></div>
        <div><span class="text-gray-400">连接池:</span> <span class="font-medium text-gray-700">${h.pool_size}/${h.pool_max} (空闲 ${h.pool_free})</span></div>
        ${h.is_replica ? '<div class="col-span-2 text-amber-600"><i class="ri-alert-line"></i> 只读副本模式</div>' : ''}`;
      detail.classList.remove('hidden');
    } else {
      dot.className = 'w-3 h-3 rounded-full flex-shrink-0 mt-1.5 bg-red-500';
      badge.className = 'text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-700';
      badge.textContent = '异常';
      msg.textContent = h.message;
      msg.className = 'text-xs mt-1 text-red-600';
      detail.innerHTML = `<div class="col-span-4 p-3 bg-red-50 rounded-lg text-red-700">${esc(h.message)}</div>`;
      detail.classList.remove('hidden');
    }
  } catch (e) {
    dot.className = 'w-3 h-3 rounded-full flex-shrink-0 mt-1.5 bg-red-500';
    badge.className = 'text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-700';
    badge.textContent = '无法检测';
    msg.textContent = '无法连接到服务器: ' + e.message;
    msg.className = 'text-xs mt-1 text-red-600';
  }
}

async function loadUsers() {
  try {
    const res = await api('/api/admin/users');
    const users = await res.json();
    document.getElementById('users-table').innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th>用户名</th><th>显示名</th><th style="text-align:center">角色</th><th>操作</th>
        </tr></thead>
        <tbody>${users.map(u => `<tr>
          <td><span class="font-medium">${esc(u.username)}</span></td>
          <td>${esc(u.display_name)}</td>
          <td style="text-align:center">
            <select onchange="changeRole(${u.id}, this.value)" class="bg-white border border-gray-300 rounded px-2 py-1 text-xs text-gray-700 cursor-pointer">
              <option value="user" ${u.role === 'user' ? 'selected' : ''}>普通用户</option>
              <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>管理员</option>
            </select>
          </td>
          <td>
            ${u.id !== currentUser.id ? `<button onclick="deleteUser(${u.id})" class="btn-ghost danger text-xs">删除</button>` : '<span class="text-xs text-gray-600">当前</span>'}
          </td>
        </tr>`).join('')}</tbody>
      </table>`;
  } catch (e) { console.error(e); }
}

async function addUser(e) {
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form));
  const errEl = document.getElementById('add-user-error');
  errEl.classList.add('hidden');
  try {
    const res = await api('/api/admin/create-user', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const body = await res.json();
      errEl.textContent = body.detail || '创建失败';
      errEl.classList.remove('hidden');
      return;
    }
    form.reset();
    loadUsers();
  } catch (err) {
    errEl.textContent = '网络错误: ' + err.message;
    errEl.classList.remove('hidden');
  }
}

async function changeRole(userId, role) {
  await api(`/api/admin/users/${userId}`, { method: 'PUT', body: JSON.stringify({ role }) });
  loadUsers();
}

async function deleteUser(userId) {
  if (!confirm('确定删除此用户？其所有案件和会话都会被删除。')) return;
  await api(`/api/admin/users/${userId}`, { method: 'DELETE' });
  loadUsers();
}

async function loadBackups() {
  try {
    const res = await api('/api/admin/backups');
    const list = await res.json();
    const el = document.getElementById('backup-list');
    const empty = document.getElementById('backup-empty');
    if (list.length === 0) { el.innerHTML = ''; empty.classList.remove('hidden'); return; }
    empty.classList.add('hidden');
    el.innerHTML = list.map(b => `
      <div class="backup-item">
        <div>
          <div class="text-sm font-medium" style="color:#111827"><i class="ri-file-zip-line text-amber-600 mr-1"></i>${esc(b.filename)}</div>
          <div class="text-xs text-gray-500 mt-0.5">${formatSize(b.size_bytes)} · ${b.created_at.replace('T', ' ').substring(0, 19)}</div>
        </div>
        <div class="flex gap-1">
          <button onclick="restoreBackup('${b.filename}')" class="btn-ghost text-xs"><i class="ri-refresh-line"></i> 恢复</button>
          <a href="/api/admin/backups/${b.filename}/download" class="btn-ghost text-xs"><i class="ri-download-2-line"></i> 下载</a>
          <button onclick="removeBackup('${b.filename}')" class="btn-ghost danger text-xs"><i class="ri-delete-bin-line"></i></button>
        </div>
      </div>`).join('');
  } catch (e) { console.error(e); }
}

async function createBackup() {
  const btn = document.getElementById('btn-backup');
  btn.disabled = true; btn.innerHTML = '<i class="ri-loader-4-line animate-spin"></i> 备份中...';
  try {
    const res = await api('/api/admin/backup', { method: 'POST' });
    if (!res.ok) { const e = await res.json(); alert('备份失败: ' + e.detail); return; }
    await loadBackups();
  } catch (e) { alert('错误: ' + e.message); }
  finally { btn.disabled = false; btn.innerHTML = '<i class="ri-download-line"></i> 立即备份'; }
}

async function restoreBackup(filename) {
  if (!confirm(`确定要从 ${filename} 恢复数据？当前数据将被覆盖！`)) return;
  try {
    const res = await api(`/api/admin/restore/${filename}`, { method: 'POST' });
    if (!res.ok) { const e = await res.json(); alert('恢复失败: ' + e.detail); return; }
    alert('数据恢复成功！');
    loadCases();
  } catch (e) { alert('错误: ' + e.message); }
}

async function removeBackup(filename) {
  if (!confirm('确定删除此备份文件？')) return;
  await api(`/api/admin/backups/${filename}`, { method: 'DELETE' });
  loadBackups();
}

async function loadSchedule() {
  try {
    const res = await api('/api/admin/backup-schedule');
    const s = await res.json();
    document.getElementById('sched-enabled').checked = s.enabled;
    document.getElementById('sched-hour').value = s.cron_hour;
    document.getElementById('sched-minute').value = s.cron_minute;
    document.getElementById('sched-keep').value = s.keep_count;
  } catch (e) { console.error(e); }
}

async function saveSchedule(e) {
  e.preventDefault();
  const data = {
    enabled: document.getElementById('sched-enabled').checked,
    cron_hour: parseInt(document.getElementById('sched-hour').value),
    cron_minute: parseInt(document.getElementById('sched-minute').value),
    keep_count: parseInt(document.getElementById('sched-keep').value),
  };
  try {
    const res = await api('/api/admin/backup-schedule', { method: 'PUT', body: JSON.stringify(data) });
    if (res.ok) alert('定时备份设置已保存');
  } catch (e) { alert('保存失败: ' + e.message); }
}

// ── LLM Config ──────────────────────────────────────────
let _llmProviders = {};
let _selectedProvider = 'ollama';
let _activeConfig = {};

const PROVIDER_ICONS = {
  ollama: 'ri-server-line', openai: 'ri-openai-fill', claude: 'ri-message-3-line',
  qwen: 'ri-translate-2', copilot: 'ri-copilot-line', gemini: 'ri-sparkling-line',
  deepseek: 'ri-search-eye-line', glm: 'ri-chat-ai-line',
};

async function loadLlmConfig() {
  try {
    const [provRes, cfgRes] = await Promise.all([
      api('/api/admin/llm-providers'),
      api('/api/admin/llm-config'),
    ]);
    _llmProviders = await provRes.json();
    _activeConfig = await cfgRes.json();
    _selectedProvider = _activeConfig.provider || 'ollama';

    const list = document.getElementById('llm-provider-list');
    list.innerHTML = Object.entries(_llmProviders).map(([k, v]) => `
      <button type="button" onclick="selectLlmProvider('${k}')"
        class="llm-provider-btn w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left ${k === _selectedProvider ? 'border-amber-500 bg-amber-50' : 'border-gray-200 bg-white hover:border-gray-300'}"
        data-provider="${k}">
        <i class="${PROVIDER_ICONS[k] || 'ri-robot-line'} text-lg ${k === _selectedProvider ? 'text-amber-600' : 'text-gray-500'}"></i>
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium" style="color:#111827">${esc(v.label)}</div>
          <div class="text-xs text-gray-500">${esc(v.default_model)}</div>
        </div>
        ${k === _activeConfig.provider ? '<span class="text-xs text-green-600 font-medium">当前</span>' : ''}
      </button>`).join('');

    fillLlmForm(_activeConfig);
    updateLlmStatusCard(_activeConfig);
    await loadModelList(_activeConfig.provider, _activeConfig.model);
    testLlmConnection();
  } catch (e) { console.error(e); }
}

function selectLlmProvider(provider) {
  _selectedProvider = provider;
  document.querySelectorAll('.llm-provider-btn').forEach(b => {
    const p = b.dataset.provider;
    b.className = `llm-provider-btn w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left ${p === provider ? 'border-amber-500 bg-amber-50' : 'border-gray-200 bg-white hover:border-gray-300'}`;
    b.querySelector('i').className = `${PROVIDER_ICONS[p] || 'ri-robot-line'} text-lg ${p === provider ? 'text-amber-600' : 'text-gray-500'}`;
  });
  const meta = _llmProviders[provider];
  if (!meta) return;

  if (provider === _activeConfig.provider) {
    fillLlmForm(_activeConfig);
    loadModelList(provider, _activeConfig.model);
  } else {
    document.getElementById('llm-provider').value = provider;
    document.getElementById('llm-provider-label').textContent = meta.label;
    document.getElementById('llm-base-url').value = meta.base_url;
    document.getElementById('llm-api-key').value = '';
    document.getElementById('llm-key-hint').textContent = meta.needs_key ? '(必填)' : '(可选)';
    document.getElementById('llm-icon').className = `${PROVIDER_ICONS[provider] || 'ri-robot-line'} text-xl text-blue-600`;
    document.getElementById('llm-ctx').value = 20000;
    document.getElementById('llm-timeout').value = 3600;
    document.getElementById('llm-active-hint').textContent = '';
    loadModelList(provider, meta.default_model);
  }
}

async function loadModelList(provider, selectedModel) {
  const sel = document.getElementById('llm-model');
  const custom = document.getElementById('llm-model-custom');
  sel.innerHTML = '<option value="">加载中...</option>';
  custom.classList.add('hidden');
  custom.value = '';

  let models = [];
  try {
    const res = await api(`/api/admin/llm-models/${provider}`);
    const data = await res.json();
    models = data.models || [];
  } catch (e) {
    const meta = _llmProviders[provider];
    models = meta ? (meta.models || []) : [];
  }

  sel.innerHTML = '';
  models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m;
    sel.appendChild(opt);
  });
  const customOpt = document.createElement('option');
  customOpt.value = '__custom__';
  customOpt.textContent = '— 自定义模型 —';
  sel.appendChild(customOpt);

  if (selectedModel && models.includes(selectedModel)) {
    sel.value = selectedModel;
  } else if (selectedModel) {
    const extra = document.createElement('option');
    extra.value = selectedModel;
    extra.textContent = selectedModel + ' (当前)';
    sel.insertBefore(extra, sel.firstChild);
    sel.value = selectedModel;
  } else if (models.length) {
    sel.value = models[0];
  }

  sel.onchange = () => {
    if (sel.value === '__custom__') {
      custom.classList.remove('hidden');
      custom.focus();
    } else {
      custom.classList.add('hidden');
      custom.value = '';
    }
  };
}

function getSelectedModel() {
  const sel = document.getElementById('llm-model');
  const custom = document.getElementById('llm-model-custom');
  if (sel.value === '__custom__') return custom.value.trim();
  return sel.value;
}

function fillLlmForm(cfg) {
  const provider = cfg.provider || 'ollama';
  const meta = _llmProviders[provider] || {};
  document.getElementById('llm-provider').value = provider;
  document.getElementById('llm-provider-label').textContent = meta.label || provider;
  document.getElementById('llm-base-url').value = cfg.base_url || meta.base_url || '';
  document.getElementById('llm-api-key').value = cfg.api_key_masked || '';
  document.getElementById('llm-ctx').value = cfg.context_window || 20000;
  document.getElementById('llm-timeout').value = cfg.timeout || 3600;
  document.getElementById('llm-key-hint').textContent = (meta.needs_key) ? '(必填)' : '(可选)';
  document.getElementById('llm-active-hint').textContent = '当前活跃配置';
  document.getElementById('llm-icon').className = `${PROVIDER_ICONS[provider] || 'ri-robot-line'} text-xl text-blue-600`;
}

function updateLlmStatusCard(cfg) {
  const providerLabel = (_llmProviders[cfg.provider] || {}).label || cfg.provider || '-';
  document.getElementById('llm-status-provider').textContent = providerLabel;
  document.getElementById('llm-status-model').textContent = cfg.model || '-';
  document.getElementById('llm-status-url').textContent = cfg.base_url || '-';
}

function setLlmStatus(ok, msg) {
  const dot = document.getElementById('llm-status-dot');
  const msgEl = document.getElementById('llm-status-msg');
  dot.className = 'w-3 h-3 rounded-full flex-shrink-0 ' + (ok === true ? 'bg-green-500' : ok === false ? 'bg-red-500' : 'bg-yellow-400 animate-pulse');
  msgEl.textContent = msg;
  msgEl.className = 'text-xs mt-0.5 ' + (ok === true ? 'text-green-600' : ok === false ? 'text-red-600' : 'text-yellow-600');
}

async function testLlmConnection() {
  const btn = document.getElementById('btn-llm-test');
  btn.disabled = true;
  btn.innerHTML = '<i class="ri-loader-4-line animate-spin"></i> 检测中...';
  setLlmStatus(null, '正在检测连接...');
  try {
    const res = await api('/api/admin/llm-test', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      setLlmStatus(true, `${data.message} (${data.provider} / ${data.model})`);
    } else {
      setLlmStatus(false, data.message);
    }
  } catch (e) {
    setLlmStatus(false, '网络错误: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="ri-link"></i> 测试连接';
  }
}

function toggleKeyVisibility() {
  const input = document.getElementById('llm-api-key');
  const eye = document.getElementById('llm-key-eye');
  if (input.type === 'password') {
    input.type = 'text';
    eye.className = 'ri-eye-off-line';
  } else {
    input.type = 'password';
    eye.className = 'ri-eye-line';
  }
}

async function saveLlmConfig(e) {
  e.preventDefault();
  const data = {
    provider: _selectedProvider,
    base_url: document.getElementById('llm-base-url').value.trim(),
    api_key: document.getElementById('llm-api-key').value,
    model: getSelectedModel(),
    context_window: parseInt(document.getElementById('llm-ctx').value) || 20000,
    timeout: parseInt(document.getElementById('llm-timeout').value) || 3600,
  };
  try {
    const res = await api('/api/admin/llm-config', { method: 'PUT', body: JSON.stringify(data) });
    if (!res.ok) { const err = await res.json(); alert('保存失败: ' + (err.detail || '未知错误')); return; }
    const result = await res.json();
    const msg = document.getElementById('llm-save-msg');
    msg.textContent = `已切换到 ${result.provider} / ${result.model}`;
    msg.classList.remove('hidden');
    setTimeout(() => msg.classList.add('hidden'), 3000);
    await loadLlmConfig();
  } catch (err) { alert('网络错误: ' + err.message); }
}

// ── Helpers ──────────────────────────────────────────────
function _matBg(t) {
  const m = { complaint: 'bg-purple-50', evidence: 'bg-blue-50', contract: 'bg-green-50',
    hearing: 'bg-amber-50', ruling: 'bg-red-50', letter: 'bg-indigo-50' };
  return m[t] || 'bg-gray-100';
}
function _matIcon(t) {
  const m = { complaint: 'ri-draft-line text-purple-600', evidence: 'ri-file-text-line text-blue-600',
    contract: 'ri-file-paper-2-line text-green-600', hearing: 'ri-mic-line text-amber-600',
    ruling: 'ri-hammer-line text-red-600', letter: 'ri-mail-send-line text-indigo-600' };
  return m[t] || 'ri-file-line text-gray-500';
}
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function formatText(text) {
  let h = esc(text);
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  h = h.replace(/^### (.+)$/gm, '<h3 class="text-base font-bold text-amber-700 mt-4 mb-1">$1</h3>');
  h = h.replace(/^## (.+)$/gm, '<h2 class="text-lg font-bold text-amber-800 mt-5 mb-2">$1</h2>');
  h = h.replace(/^# (.+)$/gm, '<h1 class="text-xl font-bold text-gray-900 mt-6 mb-2">$1</h1>');
  h = h.replace(/^---$/gm, '<hr class="border-gray-200 my-4">');
  return h;
}
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}
