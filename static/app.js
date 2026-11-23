/* PlanCheckBox · 纸间计划 —— 前端逻辑（零依赖原生 JS） */
'use strict';

/* ================= 状态 ================= */
const S = {
  plans: [], today: null, colors: [], emojis: [],
  view: 'day', anchor: null, filterPlan: null, search: '', sort: 'custom',
};
const LS_KEY = 'plancheckbox-prefs';
let drawerPlanId = null, drawerTab = 'all';
let editingPlanId = null, pmTasks = [], pmEmojiSel = '🎯', pmColorSel = 'pine';
let tmCtx = null; // {planId, taskId}
let qaDate = null;
let importQueue = []; // [{payload, preview}]
let dragPlanId = null;

const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const WD = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
const CHECK_SVG = '<svg viewBox="0 0 20 20" aria-hidden="true"><path class="check-path" d="M4 10.5l4 4 8-9"/></svg>';

/* ================= 工具 ================= */
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
function hi(text) {
  const q = S.search.trim();
  const safe = esc(text);
  if (!q) return safe;
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return safe;
  return esc(text.slice(0, idx)) + '<mark>' + esc(text.slice(idx, idx + q.length)) + '</mark>' + esc(text.slice(idx + q.length));
}
function parseD(s) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }
function fmtD(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function startOfWeek(d) { const x = new Date(d); const wd = (x.getDay() + 6) % 7; return addDays(x, -wd); }
function md(s) { const d = parseD(s); return (d.getMonth() + 1) + '月' + d.getDate() + '日'; }
function planById(id) { return S.plans.find(p => p.id === id) || null; }
function pct(p) { return p.tasks.length ? Math.round(p.tasks.filter(t => t.done).length / p.tasks.length * 100) : 0; }
function matchTask(t) {
  const q = S.search.trim().toLowerCase();
  if (!q) return true;
  return (t.title + ' ' + (t.note || '')).toLowerCase().includes(q);
}
function visiblePlans() {
  let list = S.plans.slice();
  if (S.filterPlan) list = list.filter(p => p.id === S.filterPlan);
  const q = S.search.trim().toLowerCase();
  if (q) list = list.filter(p => p.name.toLowerCase().includes(q) || p.tasks.some(matchTask));
  if (S.sort === 'name') list.sort((a, b) => a.name.localeCompare(b.name, 'zh'));
  else if (S.sort === 'progress') list.sort((a, b) => pct(b) - pct(a));
  else if (S.sort === 'tasks') list.sort((a, b) => b.tasks.length - a.tasks.length);
  return list;
}
function tasksOn(dateStr, plans) {
  const out = [];
  (plans || visiblePlans()).forEach(p => p.tasks.forEach(t => {
    if (t.date === dateStr && matchTask(t)) out.push({ plan: p, task: t });
  }));
  return out;
}
function ringSVG(percent, size, stroke) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r;
  const off = c * (1 - percent / 100);
  return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <circle class="ring-bg" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-width="${stroke}"/>
    <circle class="ring-fg" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-width="${stroke}"
      stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"/></svg>`;
}

/* ================= API ================= */
async function api(path, method = 'GET', body = null) {
  const opt = { method, headers: {} };
  if (body !== null) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const res = await fetch(path, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ('请求失败 (' + res.status + ')'));
  return data;
}
async function reloadState() {
  const data = await api('/api/state');
  S.plans = data.plans; S.today = data.today; S.colors = data.colors; S.emojis = data.emojis;
}

/* ================= Toast ================= */
function toast(msg, undoFn = null, ms = null) {
  const box = $('#toasts');
  while (box.children.length >= 3) box.firstChild.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  const dur = ms || (undoFn ? 6000 : 3200);
  el.innerHTML = `<span class="toast-msg">${esc(msg)}</span>` +
    (undoFn ? '<button class="toast-undo">撤销</button>' : '') +
    `<span class="toast-bar" style="animation-duration:${dur}ms"></span>`;
  box.appendChild(el);
  const kill = () => { el.classList.add('out'); setTimeout(() => el.remove(), 230); };
  const timer = setTimeout(kill, dur);
  if (undoFn) el.querySelector('.toast-undo').addEventListener('click', () => {
    clearTimeout(timer); kill(); undoFn();
  });
}

/* ================= 渲染：侧栏 ================= */
function renderSidebar() {
  const list = visiblePlans();
  $('#planCount').textContent = S.plans.length;
  $('#allPlansBtn').classList.toggle('active', !S.filterPlan);
  const box = $('#planList');
  if (!S.plans.length) {
    box.innerHTML = '<div class="preview-empty">还没有计划。<br>点右上角「新建计划」开始。</div>';
    return;
  }
  if (!list.length) {
    box.innerHTML = '<div class="preview-empty">没有匹配的计划</div>';
    return;
  }
  box.innerHTML = list.map((p, i) => {
    const done = p.tasks.filter(t => t.done).length;
    return `<div class="plan-card c-${p.color}" data-plan="${p.id}" draggable="${S.sort === 'custom'}"
        style="animation-delay:${Math.min(i * 40, 240)}ms" title="查看详情">
      <span class="pc-drag">⋮⋮</span>
      <span class="pc-emoji">${p.emoji}</span>
      <span class="pc-info">
        <span class="pc-name">${hi(p.name)}</span>
        <span class="pc-range">${md(p.startDate)} – ${md(p.endDate)} · ${done}/${p.tasks.length}</span>
      </span>
      <span class="pc-ring">${ringSVG(pct(p), 38, 4)}<span class="ring-text">${pct(p)}%</span></span>
    </div>`;
  }).join('');

  box.querySelectorAll('.plan-card').forEach(card => {
    card.addEventListener('click', () => openDrawer(card.dataset.plan));
    card.addEventListener('dragstart', e => {
      dragPlanId = card.dataset.plan;
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', dragPlanId); } catch (_) {}
    });
    card.addEventListener('dragend', () => {
      dragPlanId = null;
      box.querySelectorAll('.plan-card').forEach(c => c.classList.remove('dragging', 'drag-over'));
    });
    card.addEventListener('dragover', e => {
      if (!dragPlanId || dragPlanId === card.dataset.plan) return;
      e.preventDefault();
      card.classList.add('drag-over');
    });
    card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
    card.addEventListener('drop', async e => {
      e.preventDefault();
      card.classList.remove('drag-over');
      if (!dragPlanId || dragPlanId === card.dataset.plan) return;
      const ids = S.plans.map(p => p.id);
      const from = ids.indexOf(dragPlanId), to = ids.indexOf(card.dataset.plan);
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      S.plans.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
      S.plans.forEach((p, i) => p.order = i);
      renderAll();
      try { await api('/api/reorder', 'POST', { ids }); }
      catch (err) { toast('排序保存失败：' + err.message); }
    });
  });
}

/* ================= 渲染：日视图 ================= */
function renderDay(root) {
  const ds = fmtD(S.anchor);
  const isToday = ds === S.today;
  const items = tasksOn(ds);
  const done = items.filter(x => x.task.done).length;
  const percent = items.length ? Math.round(done / items.length * 100) : 0;

  let streak = 0;
  if (isToday) {
    let cur = parseD(S.today);
    const dayAllDone = dstr => {
      const it = tasksOn(dstr);
      return it.length > 0 && it.every(x => x.task.done);
    };
    if (!dayAllDone(S.today)) cur = addDays(cur, -1);
    while (dayAllDone(fmtD(cur)) && streak < 365) { streak++; cur = addDays(cur, -1); }
  }

  let html = `<div class="day-view">
    <div class="day-head">
      <div class="day-big">${S.anchor.getDate()}</div>
      <div class="day-meta">
        <div class="day-title">${S.anchor.getMonth() + 1}月 · ${WD[S.anchor.getDay()]}
          ${isToday ? '<span class="today-badge">今天</span>' : ''}
          ${streak >= 2 ? `<span class="streak-badge">🔥 连续 ${streak} 天达成</span>` : ''}
        </div>
        <div class="day-sub">${S.anchor.getFullYear()} 年 · ${items.length ? items.length + ' 项安排' : '暂无安排'}</div>
      </div>
      <div class="day-progress">
        <div class="day-stats"><b>${done}</b> / ${items.length} 已完成 · ${percent}%</div>
        <div class="progress-bar"><div class="progress-fill" style="width:${percent}%"></div></div>
      </div>
    </div>`;

  // 逾期提醒（仅今天视角）
  if (isToday) {
    const overdue = [];
    visiblePlans().forEach(p => p.tasks.forEach(t => {
      if (t.date < S.today && !t.done && matchTask(t)) overdue.push({ plan: p, task: t });
    }));
    if (overdue.length) {
      html += `<div class="overdue-card">
        <div class="overdue-head">⚠ 之前还有 ${overdue.length} 项未完成</div>
        ${overdue.slice(0, 6).map(x => `<div class="overdue-item c-${x.plan.color}">
          <span class="t-title">${esc(x.plan.emoji)} ${hi(x.task.title)} <span style="color:var(--ink-3);font-size:11px">· ${md(x.task.date)}</span></span>
          <button class="carry-btn" data-carry="${x.plan.id}|${x.task.id}">顺延到今天</button>
        </div>`).join('')}
        ${overdue.length > 6 ? `<div style="font-size:11.5px;color:var(--ink-3)">…以及另外 ${overdue.length - 6} 项</div>` : ''}
      </div>`;
    }
  }

  const groups = visiblePlans().map(p => ({
    plan: p, tasks: p.tasks.filter(t => t.date === ds && matchTask(t))
  })).filter(g => g.tasks.length);

  if (groups.length) {
    html += groups.map(g => `<div class="task-group c-${g.plan.color}">
      <div class="group-head">
        <span class="group-emoji">${g.plan.emoji}</span>
        <span class="group-name">${hi(g.plan.name)}</span>
        <span class="group-count">${g.tasks.filter(t => t.done).length}/${g.tasks.length}</span>
        <span class="group-bar"></span>
      </div>
      ${g.tasks.map((t, i) => taskRowHTML(g.plan, t, i)).join('')}
    </div>`).join('');
  } else if (!S.search.trim()) {
    html += `<div class="empty-state">
      <div class="empty-art"><svg viewBox="0 0 96 96" width="88" height="88">
        <rect x="14" y="14" width="68" height="68" rx="18" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="8 6"/>
        <path d="M32 49l11 11 22-25" stroke="currentColor" stroke-width="4.5" fill="none" stroke-linecap="round" stroke-linejoin="round" opacity=".45"/>
      </svg></div>
      <div class="empty-title">这一天还没有安排</div>
      <div class="empty-sub">在下方快速添加一条任务，或创建一个新计划</div>
    </div>`;
  } else {
    html += `<div class="empty-state"><div class="empty-title">没有匹配「${esc(S.search.trim())}」的任务</div>
      <div class="empty-sub">换个关键词试试，或清空搜索</div></div>`;
  }

  // 快速添加栏
  const plans = visiblePlans();
  if (plans.length) {
    const def = S.filterPlan || plans[0].id;
    html += `<div class="quick-bar">
      <span class="plus">＋</span>
      <input class="quick-input" id="dayQuickInput" maxlength="200" placeholder="添加任务到 ${md(ds)}，回车确认" autocomplete="off">
      <select class="quick-select" id="dayQuickPlan">
        ${plans.map(p => `<option value="${p.id}" ${p.id === def ? 'selected' : ''}>${p.emoji} ${esc(p.name)}</option>`).join('')}
      </select>
      <button class="primary-btn small" id="dayQuickAdd">添加</button>
    </div>`;
  }
  html += '</div>';
  root.innerHTML = html;

  const qi = $('#dayQuickInput');
  if (qi) {
    const submit = () => {
      const title = qi.value.trim();
      if (!title) { qi.focus(); return; }
      addTask($('#dayQuickPlan').value, { title, date: ds });
      qi.value = '';
    };
    $('#dayQuickAdd').addEventListener('click', submit);
    qi.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) submit(); });
  }
}

function taskRowHTML(plan, t, i) {
  return `<div class="task-row c-${plan.color} ${t.done ? 'done' : ''}" style="animation-delay:${Math.min(i * 35, 280)}ms">
    <button class="t-check" data-toggle="${plan.id}|${t.id}" aria-label="标记完成">${CHECK_SVG}</button>
    <div class="t-body">
      <div class="t-title">${hi(t.title)}</div>
      ${t.note ? `<div class="t-note">${esc(t.note)}</div>` : ''}
    </div>
    <div class="t-actions">
      <button class="t-act" data-edit="${plan.id}|${t.id}" title="编辑">✎</button>
      <button class="t-act del" data-del="${plan.id}|${t.id}" title="删除">🗑</button>
    </div>
  </div>`;
}

/* ================= 渲染：周视图 ================= */
function renderWeek(root) {
  const mon = startOfWeek(S.anchor);
  const days = Array.from({ length: 7 }, (_, i) => addDays(mon, i));
  const plans = visiblePlans();
  let total = 0, done = 0;
  const dayInfo = days.map(d => {
    const it = tasksOn(fmtD(d), plans);
    total += it.length; done += it.filter(x => x.task.done).length;
    return { d, items: it };
  });
  const isCurWeek = fmtD(mon) === fmtD(startOfWeek(parseD(S.today)));

  let html = `<div class="week-view">
    <div class="week-summary">
      <span class="ws-text">本周 <b>${done}</b> / ${total} 已完成${isCurWeek ? ' · 本周' : ''}</span>
      <div class="ws-days">${dayInfo.map(x => {
        const p = x.items.length ? x.items.filter(i => i.task.done).length / x.items.length * 100 : 0;
        return `<div class="ws-day"><div class="ws-bar"><i style="width:${p}%"></i></div><span>${x.d.getDate()}</span></div>`;
      }).join('')}</div>
    </div>
    <div class="week-grid">`;

  html += dayInfo.map((x, ci) => {
    const ds = fmtD(x.d);
    const today = ds === S.today;
    const weekend = ci >= 5;
    const shown = x.items.slice(0, 6);
    const dn = x.items.filter(i => i.task.done).length;
    return `<div class="week-col ${today ? 'today' : ''} ${weekend ? 'weekend' : ''}" style="animation-delay:${ci * 40}ms">
      <div class="wc-head">
        <span class="wc-wd">${WD[x.d.getDay()]}</span>
        <span class="wc-num">${x.d.getDate()}</span>
        <span class="wc-count">${x.items.length ? dn + '/' + x.items.length : ''}</span>
      </div>
      <div class="wc-body">
        ${shown.map((it, i) => `<div class="w-chip c-${it.plan.color} ${it.task.done ? 'done' : ''}" style="animation-delay:${i * 30}ms">
          <button class="w-check" data-toggle="${it.plan.id}|${it.task.id}" aria-label="标记完成">${CHECK_SVG}</button>
          <span class="w-title" data-edit="${it.plan.id}|${it.task.id}" title="${esc(it.plan.name)}：${esc(it.task.title)}">${hi(it.task.title)}</span>
        </div>`).join('')}
        ${x.items.length > 6 ? `<button class="wc-more" data-goto="${ds}">＋${x.items.length - 6} 更多</button>` : ''}
      </div>
      <button class="wc-add" data-quickadd="${ds}">＋ 添加</button>
    </div>`;
  }).join('');

  html += '</div></div>';
  root.innerHTML = html;
}

/* ================= 渲染：月视图 ================= */
function renderMonth(root) {
  const y = S.anchor.getFullYear(), m = S.anchor.getMonth();
  const first = new Date(y, m, 1);
  const offset = (first.getDay() + 6) % 7;
  const dim = new Date(y, m + 1, 0).getDate();
  const weeks = Math.ceil((offset + dim) / 7);
  const start = addDays(first, -offset);
  const plans = visiblePlans();

  let total = 0, done = 0;
  for (let i = 0; i < weeks * 7; i++) {
    const d = addDays(start, i);
    if (d.getMonth() !== m) continue;
    const it = tasksOn(fmtD(d), plans);
    total += it.length; done += it.filter(x => x.task.done).length;
  }
  const percent = total ? Math.round(done / total * 100) : 0;

  let html = `<div class="month-view">
    <div class="month-head">
      <div class="mh-ring c-pine">${ringSVG(percent, 54, 5)}<span class="ring-text">${percent}%</span></div>
      <div class="mh-text">本月 <b>${done}</b> / ${total} 已完成<br><span style="font-size:11.5px;color:var(--ink-3)">点击日期进入当日视图</span></div>
    </div>
    <div class="month-weekdays">${['一', '二', '三', '四', '五', '六', '日'].map((w, i) => `<span class="${i >= 5 ? 'weekend' : ''}">${w}</span>`).join('')}</div>
    <div class="month-grid">`;

  for (let i = 0; i < weeks * 7; i++) {
    const d = addDays(start, i);
    const ds = fmtD(d);
    const other = d.getMonth() !== m;
    const today = ds === S.today;
    const items = tasksOn(ds, plans);
    const dots = items.slice(0, 5).map(x =>
      `<span class="m-dot c-${x.plan.color} ${x.task.done ? 'done' : ''}" title="${esc(x.plan.name)}：${esc(x.task.title)}"></span>`).join('');
    const titles = items.length <= 2 && !other ? `<div class="m-titles">${items.map(x =>
      `<span class="m-title ${x.task.done ? 'done' : ''}">${esc(x.task.title)}</span>`).join('')}</div>` : '';
    html += `<div class="m-cell ${other ? 'other' : ''} ${today ? 'today' : ''}" data-goto="${ds}" style="animation-delay:${Math.min(i * 12, 300)}ms">
      <span class="m-num">${d.getDate()}</span>
      <button class="m-add" data-quickadd="${ds}" title="快速添加">＋</button>
      ${items.length ? `<div class="m-dots">${dots}</div>` : ''}
      ${items.length > 5 ? `<div class="m-more">＋${items.length - 5}</div>` : ''}
      ${titles}
    </div>`;
  }
  html += '</div></div>';
  root.innerHTML = html;
}

/* ================= 渲染：主入口 ================= */
function renderView() {
  const root = $('#viewRoot');
  root.style.animation = 'none';
  void root.offsetWidth;
  root.style.animation = '';

  if (!S.plans.length) {
    root.innerHTML = `<div class="empty-state" style="padding-top:9vh">
      <div class="empty-art"><svg viewBox="0 0 96 96" width="104" height="104">
        <rect x="14" y="14" width="68" height="68" rx="18" fill="none" stroke="currentColor" stroke-width="3"/>
        <path d="M32 49l11 11 22-25" stroke="currentColor" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      </svg></div>
      <div class="empty-title">开始你的第一个计划</div>
      <div class="empty-sub">在界面上直接创建，或拖入已有的 JSON 计划文件</div>
      <div class="empty-btns">
        <button class="primary-btn" id="emptyNew">＋ 新建计划</button>
        <button class="ghost-btn" id="emptyImport">导入文件</button>
      </div>
    </div>`;
    $('#emptyNew').addEventListener('click', () => openPlanModal());
    $('#emptyImport').addEventListener('click', () => $('#fileInput').click());
  } else if (S.view === 'day') renderDay(root);
  else if (S.view === 'week') renderWeek(root);
  else renderMonth(root);

  // 顶栏状态
  $$('.view-switch button').forEach(b => b.classList.toggle('active', b.dataset.view === S.view));
  const act = $(`.view-switch button[data-view="${S.view}"]`);
  const pill = $('.switch-pill');
  if (act && pill) {
    pill.style.width = act.offsetWidth + 'px';
    pill.style.transform = `translateX(${act.offsetLeft - 3}px)`;
  }
  const a = S.anchor;
  if (S.view === 'month') $('#rangeLabel').textContent = `${a.getFullYear()}年${a.getMonth() + 1}月`;
  else if (S.view === 'week') {
    const mon = startOfWeek(a), sun = addDays(mon, 6);
    $('#rangeLabel').textContent = `${mon.getMonth() + 1}月${mon.getDate()}日 – ${sun.getMonth() + 1}月${sun.getDate()}日`;
  } else $('#rangeLabel').textContent = `${a.getMonth() + 1}月${a.getDate()}日 · ${WD[a.getDay()]}`;

  // 筛选 chip
  const chip = $('#filterChip');
  const fp = planById(S.filterPlan);
  if (fp) {
    chip.className = `filter-chip c-${fp.color}`;
    chip.innerHTML = `只看：${fp.emoji} ${esc(fp.name)} <button id="filterClear" aria-label="清除筛选">×</button>`;
    $('#filterClear').addEventListener('click', () => { S.filterPlan = null; savePrefs(); renderAll(); });
  } else chip.classList.add('hidden');
}

function renderAll() {
  renderSidebar();
  renderView();
  if (drawerPlanId) {
    if (planById(drawerPlanId)) renderDrawer();
    else closeDrawer();
  }
}

function savePrefs() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ view: S.view, sort: S.sort, filterPlan: S.filterPlan }));
  } catch (_) {}
}
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    if (['day', 'week', 'month'].includes(p.view)) S.view = p.view;
    if (['custom', 'name', 'progress', 'tasks'].includes(p.sort)) S.sort = p.sort;
    if (p.filterPlan) S.filterPlan = p.filterPlan;
  } catch (_) {}
}

/* ================= 任务操作 ================= */
async function toggleTask(planId, taskId) {
  const p = planById(planId); if (!p) return;
  const t = p.tasks.find(x => x.id === taskId); if (!t) return;
  t.done = !t.done;
  t.doneAt = t.done ? new Date().toISOString() : '';
  renderAll();
  try { await api(`/api/plans/${planId}/tasks/${taskId}`, 'PUT', t); }
  catch (err) { t.done = !t.done; renderAll(); toast('保存失败：' + err.message); }
}

async function addTask(planId, fields, silent = false) {
  const p = planById(planId); if (!p) return;
  try {
    const nt = await api(`/api/plans/${planId}/tasks`, 'POST', fields);
    p.tasks.push(nt);
    p.tasks.sort((a, b) => a.date === b.date ? a.title.localeCompare(b.title, 'zh') : a.date < b.date ? -1 : 1);
    renderAll();
    if (!silent) toast(`已添加「${nt.title}」到 ${md(nt.date)}`);
    return nt;
  } catch (err) { toast('添加失败：' + err.message); }
}

async function deleteTask(planId, taskId) {
  const p = planById(planId); if (!p) return;
  const idx = p.tasks.findIndex(x => x.id === taskId); if (idx < 0) return;
  const [t] = p.tasks.splice(idx, 1);
  renderAll();
  try {
    await api(`/api/plans/${planId}/tasks/${taskId}`, 'DELETE');
    toast(`已删除「${t.title}」`, async () => {
      try {
        const nt = await api(`/api/plans/${planId}/tasks`, 'POST', t);
        const pp = planById(planId);
        if (pp) { pp.tasks.push(nt); pp.tasks.sort((a, b) => a.date < b.date ? -1 : 1); }
        renderAll(); toast('已恢复');
      } catch (err) { toast('恢复失败：' + err.message); }
    });
  } catch (err) { p.tasks.splice(idx, 0, t); renderAll(); toast('删除失败：' + err.message); }
}

async function carryTask(planId, taskId) {
  const p = planById(planId); if (!p) return;
  const t = p.tasks.find(x => x.id === taskId); if (!t) return;
  const old = t.date;
  t.date = S.today;
  renderAll();
  try {
    await api(`/api/plans/${planId}/tasks/${taskId}`, 'PUT', t);
    toast(`已顺延到今天`);
  } catch (err) { t.date = old; renderAll(); toast('操作失败：' + err.message); }
}

async function deletePlan(planId) {
  const idx = S.plans.findIndex(p => p.id === planId); if (idx < 0) return;
  const [p] = S.plans.splice(idx, 1);
  if (S.filterPlan === planId) S.filterPlan = null;
  if (drawerPlanId === planId) closeDrawer();
  renderAll();
  try {
    await api(`/api/plans/${planId}`, 'DELETE');
    toast(`已删除计划「${p.name}」`, async () => {
      try {
        const np = await api('/api/plans', 'POST', p);
        S.plans.push(np);
        S.plans.sort((a, b) => a.order - b.order);
        renderAll(); toast('已恢复');
      } catch (err) { toast('恢复失败：' + err.message); }
    });
  } catch (err) { S.plans.splice(idx, 0, p); renderAll(); toast('删除失败：' + err.message); }
}

/* ================= 计划弹窗 ================= */
function openPlanModal(plan = null) {
  editingPlanId = plan ? plan.id : null;
  $('#planModalTitle').textContent = plan ? '编辑计划' : '新建计划';
  $('#pmSubmit').textContent = plan ? '保存修改' : '创建计划';
  $('#pmName').value = plan ? plan.name : '';
  $('#pmDesc').value = plan ? plan.description : '';
  $('#pmStart').value = plan ? plan.startDate : S.today;
  $('#pmEnd').value = plan ? plan.endDate : fmtD(addDays(parseD(S.today), 29));
  $('#pmNameErr').textContent = '';
  $('#pmDateErr').textContent = '';
  pmEmojiSel = plan ? plan.emoji : '🎯';
  pmColorSel = plan ? plan.color : S.colors[S.plans.length % S.colors.length];
  pmTasks = plan
    ? plan.tasks.map(t => ({ id: t.id, title: t.title, date: t.date, done: t.done, doneAt: t.doneAt, note: t.note }))
    : [{ title: '', date: $('#pmStart').value }];

  $('#pmEmoji').innerHTML = S.emojis.map(e =>
    `<button type="button" class="emoji-btn ${e === pmEmojiSel ? 'selected' : ''}" data-emoji="${e}">${e}</button>`).join('');
  $('#pmColors').innerHTML = S.colors.map(c =>
    `<button type="button" class="color-dot c-${c} ${c === pmColorSel ? 'selected' : ''}" data-color="${c}" title="${c}" aria-label="颜色 ${c}"></button>`).join('');
  $$('#pmEmoji .emoji-btn').forEach(b => b.addEventListener('click', () => {
    pmEmojiSel = b.dataset.emoji;
    $$('#pmEmoji .emoji-btn').forEach(x => x.classList.toggle('selected', x === b));
  }));
  $$('#pmColors .color-dot').forEach(b => b.addEventListener('click', () => {
    pmColorSel = b.dataset.color;
    $$('#pmColors .color-dot').forEach(x => x.classList.toggle('selected', x === b));
  }));

  $('#pmPaste').value = '';
  $('#pmRepeatTitle').value = '';
  $$('#pmWeekdays button').forEach(b => b.classList.toggle('on', ['0', '1', '2', '3', '4'].includes(b.dataset.wd)));
  switchPmTab('rows');
  renderPmRows();
  renderPmPreview();
  $('#planModal').classList.remove('hidden');
  setTimeout(() => $('#pmName').focus(), 60);
}

function switchPmTab(tab) {
  $$('.pm-tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $('#pmTabRows').classList.toggle('hidden', tab !== 'rows');
  $('#pmTabPaste').classList.toggle('hidden', tab !== 'paste');
  $('#pmTabRepeat').classList.toggle('hidden', tab !== 'repeat');
  updatePmCounts();
}

function renderPmRows() {
  const box = $('#pmTaskRows');
  box.innerHTML = pmTasks.map((t, i) => `<div class="pm-row">
    <input class="text-input row-title" data-row="${i}" maxlength="200" placeholder="任务标题" value="${esc(t.title)}" autocomplete="off">
    <input type="date" class="text-input row-date" data-rowdate="${i}" value="${t.date}">
    <button type="button" class="pm-row-del" data-rowdel="${i}" title="移除">×</button>
  </div>`).join('');
  box.querySelectorAll('.row-title').forEach(inp => {
    inp.addEventListener('input', () => { pmTasks[+inp.dataset.row].title = inp.value; renderPmPreview(); });
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault();
        if (+inp.dataset.row === pmTasks.length - 1) { pmTasks.push({ title: '', date: $('#pmStart').value }); renderPmRows(); }
        const next = box.querySelector(`[data-row="${+inp.dataset.row + 1}"]`);
        if (next) next.focus();
      }
    });
  });
  box.querySelectorAll('.row-date').forEach(inp =>
    inp.addEventListener('change', () => { pmTasks[+inp.dataset.rowdate].date = inp.value || $('#pmStart').value; renderPmPreview(); }));
  box.querySelectorAll('.pm-row-del').forEach(btn =>
    btn.addEventListener('click', () => { pmTasks.splice(+btn.dataset.rowdel, 1); renderPmRows(); renderPmPreview(); }));
}

function parsePaste() {
  const start = $('#pmStart').value || S.today;
  return $('#pmPaste').value.split('\n').map(line => {
    const s = line.trim();
    if (!s) return null;
    const m = s.match(/^(\d{4}-\d{2}-\d{2})\s+(.+)$/);
    if (m) return { title: m[2].trim(), date: m[1] };
    return { title: s, date: start };
  }).filter(Boolean);
}

function repeatTasks() {
  const title = $('#pmRepeatTitle').value.trim();
  const wds = $$('#pmWeekdays button.on').map(b => +b.dataset.wd);
  if (!title || !wds.length) return [];
  const start = parseD($('#pmStart').value || S.today);
  const end = parseD($('#pmEnd').value || $('#pmStart').value || S.today);
  const out = [];
  for (let d = new Date(start); d <= end && out.length < 400; d = addDays(d, 1)) {
    if (wds.includes((d.getDay() + 6) % 7)) out.push({ title, date: fmtD(d) });
  }
  return out;
}

function updatePmCounts() {
  const pp = parsePaste();
  $('#pmPasteCount').textContent = pp.length ? `识别到 ${pp.length} 条任务` : '';
  const rp = repeatTasks();
  $('#pmRepeatCount').textContent = rp.length ? `将生成 ${rp.length} 条任务` : '';
}

function renderPmPreview() {
  const valid = pmTasks.filter(t => t.title.trim());
  $('#pmTaskCount').textContent = valid.length ? `${valid.length} 条` : '';
  const days = new Set(valid.map(t => t.date)).size;
  $('#pmSummary').textContent = valid.length ? `共 ${valid.length} 个任务 · 覆盖 ${days} 天` : '可以先创建计划，之后再添加任务';
  const box = $('#pmTaskPreview');
  if (!valid.length) {
    box.innerHTML = '<div class="preview-empty">任务会显示在这里</div>';
    return;
  }
  box.innerHTML = valid.slice(0, 60).map(t => {
    const i = pmTasks.indexOf(t);
    return `<div class="preview-chip">
      <span class="chip-date">${t.date.slice(5).replace('-', '/')}</span>
      <span class="chip-title">${esc(t.title)}</span>
      <button type="button" class="chip-del" data-chipdel="${i}">×</button>
    </div>`;
  }).join('') + (valid.length > 60 ? `<div class="preview-empty">…以及另外 ${valid.length - 60} 条</div>` : '');
  box.querySelectorAll('.chip-del').forEach(b =>
    b.addEventListener('click', () => { pmTasks.splice(+b.dataset.chipdel, 1); renderPmRows(); renderPmPreview(); }));
}

async function submitPlanModal() {
  const name = $('#pmName').value.trim();
  const start = $('#pmStart').value, end = $('#pmEnd').value;
  $('#pmNameErr').textContent = name ? '' : '请填写计划名称';
  $('#pmDateErr').textContent = (!start || !end) ? '请选择日期范围' : (end < start ? '结束日期不能早于开始日期' : '');
  if (!name || !start || !end || end < start) return;

  const tasks = pmTasks.filter(t => t.title.trim()).map(t => ({
    id: t.id, title: t.title.trim(), date: t.date || start,
    done: !!t.done, doneAt: t.doneAt || '', note: t.note || '',
  }));
  const payload = {
    name, emoji: pmEmojiSel, color: pmColorSel, description: $('#pmDesc').value.trim(),
    startDate: start, endDate: end, tasks,
  };
  const btn = $('#pmSubmit');
  btn.disabled = true;
  try {
    if (editingPlanId) {
      const old = planById(editingPlanId);
      payload.order = old ? old.order : 0;
      payload.createdAt = old ? old.createdAt : undefined;
      const np = await api(`/api/plans/${editingPlanId}`, 'PUT', payload);
      const i = S.plans.findIndex(p => p.id === editingPlanId);
      if (i >= 0) S.plans[i] = np;
      toast(`已保存「${np.name}」`);
    } else {
      const np = await api('/api/plans', 'POST', payload);
      S.plans.push(np);
      toast(`计划「${np.name}」已创建，共 ${np.tasks.length} 个任务`);
      const a = fmtD(S.anchor);
      if (a < np.startDate || a > np.endDate) S.anchor = parseD(np.startDate);
    }
    $('#planModal').classList.add('hidden');
    renderAll();
  } catch (err) { toast('保存失败：' + err.message); }
  btn.disabled = false;
}

/* ================= 任务弹窗 ================= */
function openTaskModal(planId, taskId) {
  const p = planById(planId); if (!p) return;
  const t = p.tasks.find(x => x.id === taskId); if (!t) return;
  tmCtx = { planId, taskId };
  $('#tmTitle').value = t.title;
  $('#tmDate').value = t.date;
  $('#tmNote').value = t.note || '';
  $('#tmTitleErr').textContent = '';
  $('#tmPlan').innerHTML = S.plans.map(x =>
    `<option value="${x.id}" ${x.id === planId ? 'selected' : ''}>${x.emoji} ${esc(x.name)}</option>`).join('');
  $('#taskModal').classList.remove('hidden');
  setTimeout(() => $('#tmTitle').focus(), 60);
}

async function submitTaskModal() {
  if (!tmCtx) return;
  const title = $('#tmTitle').value.trim();
  if (!title) { $('#tmTitleErr').textContent = '请填写任务标题'; return; }
  const { planId, taskId } = tmCtx;
  const p = planById(planId);
  const t = p && p.tasks.find(x => x.id === taskId);
  if (!t) return;
  const newPlanId = $('#tmPlan').value;
  const fields = { title, date: $('#tmDate').value || t.date, note: $('#tmNote').value.trim(), done: t.done, doneAt: t.doneAt };
  const btn = $('#tmSave');
  btn.disabled = true;
  try {
    if (newPlanId !== planId) {
      await api(`/api/plans/${planId}/tasks/${taskId}`, 'DELETE');
      const nt = await api(`/api/plans/${newPlanId}/tasks`, 'POST', { ...fields, id: taskId });
      p.tasks = p.tasks.filter(x => x.id !== taskId);
      const np = planById(newPlanId);
      if (np) { np.tasks.push(nt); np.tasks.sort((a, b) => a.date < b.date ? -1 : 1); }
    } else {
      const nt = await api(`/api/plans/${planId}/tasks/${taskId}`, 'PUT', { ...fields, id: taskId });
      Object.assign(t, nt);
      p.tasks.sort((a, b) => a.date === b.date ? a.title.localeCompare(b.title, 'zh') : a.date < b.date ? -1 : 1);
    }
    $('#taskModal').classList.add('hidden');
    tmCtx = null;
    renderAll();
    toast('任务已保存');
  } catch (err) { toast('保存失败：' + err.message); }
  btn.disabled = false;
}

/* ================= 抽屉 ================= */
function openDrawer(planId) {
  drawerPlanId = planId;
  drawerTab = 'all';
  renderDrawer();
  $('#drawer').classList.add('open');
  $('#drawerScrim').classList.remove('hidden');
}
function closeDrawer() {
  drawerPlanId = null;
  $('#drawer').classList.remove('open');
  $('#drawerScrim').classList.add('hidden');
}
function renderDrawer() {
  const p = planById(drawerPlanId); if (!p) return;
  const done = p.tasks.filter(t => t.done).length;
  const total = p.tasks.length;
  const percent = total ? Math.round(done / total * 100) : 0;
  const daysLeft = Math.max(0, Math.ceil((parseD(p.endDate) - parseD(S.today)) / 86400000));
  let tasks = p.tasks.slice();
  if (drawerTab === 'todo') tasks = tasks.filter(t => !t.done);
  if (drawerTab === 'done') tasks = tasks.filter(t => t.done);
  const byDate = {};
  tasks.forEach(t => { (byDate[t.date] = byDate[t.date] || []).push(t); });

  $('#drawerContent').innerHTML = `<div class="c-${p.color}">
    <div class="drawer-head">
      <div class="dh-top">
        <span class="dh-emoji">${p.emoji}</span>
        <span class="dh-name">${esc(p.name)}</span>
        <button class="icon-btn dh-close" id="drawerClose" aria-label="关闭">×</button>
      </div>
      <div class="dh-range">${p.startDate} → ${p.endDate}</div>
      ${p.description ? `<div class="dh-desc">${esc(p.description)}</div>` : ''}
    </div>
    <div class="drawer-stats">
      <div class="stat-box"><div class="stat-num">${total}</div><div class="stat-label">总任务</div></div>
      <div class="stat-box"><div class="stat-num">${done}</div><div class="stat-label">已完成</div></div>
      <div class="stat-box"><div class="stat-num">${percent}%</div><div class="stat-label">完成率</div></div>
      <div class="stat-box"><div class="stat-num">${daysLeft}</div><div class="stat-label">剩余天数</div></div>
    </div>
    <div class="drawer-actions">
      <button class="ghost-btn small" id="drawerEdit">✎ 编辑计划</button>
      <button class="ghost-btn small" id="drawerFilter">${S.filterPlan === p.id ? '✓ 已筛选' : '只看此计划'}</button>
      <button class="ghost-btn small" id="drawerExport">导出 JSON</button>
      <button class="danger-btn" id="drawerDelete" style="height:30px;font-size:12.5px">删除计划</button>
    </div>
    <div class="drawer-tabs">
      <button data-dtab="all" class="${drawerTab === 'all' ? 'active' : ''}">全部 ${total}</button>
      <button data-dtab="todo" class="${drawerTab === 'todo' ? 'active' : ''}">未完成 ${total - done}</button>
      <button data-dtab="done" class="${drawerTab === 'done' ? 'active' : ''}">已完成 ${done}</button>
    </div>
    <div class="drawer-tasks">
      ${Object.keys(byDate).sort().map(d => `<div>
        <div class="d-group-date ${d < S.today && byDate[d].some(t => !t.done) ? 'overdue' : ''}">${md(d)} · ${WD[parseD(d).getDay()]}<span class="line"></span></div>
        ${byDate[d].map(t => `<div class="d-task c-${p.color} ${t.done ? 'done' : ''}">
          <button class="t-check" data-toggle="${p.id}|${t.id}" aria-label="标记完成">${CHECK_SVG}</button>
          <div class="t-body" data-edit="${p.id}|${t.id}">
            <div class="t-title">${esc(t.title)}</div>
            ${t.note ? `<div class="t-note">${esc(t.note)}</div>` : ''}
          </div>
          <div class="t-actions"><button class="t-act del" data-del="${p.id}|${t.id}" title="删除">🗑</button></div>
        </div>`).join('')}
      </div>`).join('') || '<div class="preview-empty">这里没有任务</div>'}
    </div>
  </div>`;

  $('#drawerClose').addEventListener('click', closeDrawer);
  $('#drawerEdit').addEventListener('click', () => { const pp = planById(drawerPlanId); closeDrawer(); openPlanModal(pp); });
  $('#drawerFilter').addEventListener('click', () => {
    S.filterPlan = S.filterPlan === p.id ? null : p.id;
    savePrefs(); closeDrawer(); renderAll();
  });
  $('#drawerExport').addEventListener('click', () => { window.location.href = `/api/export/${p.id}`; });
  const delBtn = $('#drawerDelete');
  delBtn.addEventListener('click', () => {
    if (delBtn.classList.contains('confirm-armed')) { deletePlan(p.id); }
    else {
      delBtn.classList.add('confirm-armed');
      delBtn.textContent = '确认删除？';
      setTimeout(() => { delBtn.classList.remove('confirm-armed'); delBtn.textContent = '删除计划'; }, 3000);
    }
  });
  $$('.drawer-tabs button').forEach(b => b.addEventListener('click', () => { drawerTab = b.dataset.dtab; renderDrawer(); }));
}

/* ================= 快速添加气泡 ================= */
function openQuickAdd(dateStr, anchorEl) {
  qaDate = dateStr;
  const plans = S.plans;
  if (!plans.length) { openPlanModal(); return; }
  $('#qaDate').textContent = `添加到 ${md(dateStr)} · ${WD[parseD(dateStr).getDay()]}`;
  $('#qaTitle').value = '';
  $('#qaPlan').innerHTML = plans.map(p =>
    `<option value="${p.id}" ${p.id === S.filterPlan ? 'selected' : ''}>${p.emoji} ${esc(p.name)}</option>`).join('');
  const qa = $('#quickAdd');
  qa.classList.remove('hidden');
  const r = anchorEl.getBoundingClientRect();
  const left = Math.max(8, Math.min(r.left, window.innerWidth - 312));
  let top = r.bottom + 8;
  if (top + 150 > window.innerHeight) top = Math.max(8, r.top - 158);
  qa.style.left = left + 'px';
  qa.style.top = top + 'px';
  setTimeout(() => $('#qaTitle').focus(), 40);
}
function closeQuickAdd() { $('#quickAdd').classList.add('hidden'); qaDate = null; }
async function submitQuickAdd() {
  const title = $('#qaTitle').value.trim();
  if (!title || !qaDate) { $('#qaTitle').focus(); return; }
  await addTask($('#qaPlan').value, { title, date: qaDate });
  closeQuickAdd();
}

/* ================= 导入 ================= */
async function handleFiles(files) {
  const ok = [];
  for (const f of files) {
    try {
      const text = await f.text();
      const payload = JSON.parse(text);
      const res = await api('/api/import', 'POST', { payload, dryRun: true });
      if (!res.imported || !res.imported.length) throw new Error('文件中没有可识别的计划');
      res.imported.forEach(it => ok.push({ payload, item: it, file: f.name }));
    } catch (err) {
      toast(`「${f.name}」导入失败：${err.message}`);
    }
  }
  if (!ok.length) return;
  importQueue = ok;
  $('#importPreview').innerHTML = ok.map(x => {
    const p = x.item.plan;
    return `<div class="import-item c-${p.color}">
      <span class="ii-emoji">${p.emoji}</span>
      <span class="ii-info">
        <span class="ii-name">${esc(p.name)}</span>
        <span class="ii-meta">${p.tasks.length} 个任务 · ${p.startDate} → ${p.endDate}</span>
      </span>
      <span class="ii-badge">${esc(x.item.source)}</span>
    </div>`;
  }).join('');
  $('#importConfirm').textContent = `导入 ${ok.length} 个计划`;
  $('#importModal').classList.remove('hidden');
}
async function confirmImport() {
  const btn = $('#importConfirm');
  btn.disabled = true;
  let n = 0;
  for (const x of importQueue) {
    try {
      const res = await api('/api/import', 'POST', { payload: x.payload });
      n += res.imported.length;
    } catch (err) { toast('导入失败：' + err.message); }
  }
  btn.disabled = false;
  $('#importModal').classList.add('hidden');
  importQueue = [];
  await reloadState();
  renderAll();
  if (n) toast(`成功导入 ${n} 个计划`);
}

/* ================= 事件绑定 ================= */
function bindEvents() {
  // 视图切换 / 日期导航
  $$('.view-switch button').forEach(b => b.addEventListener('click', () => {
    S.view = b.dataset.view; savePrefs(); renderView();
  }));
  $('#prevBtn').addEventListener('click', () => navigate(-1));
  $('#nextBtn').addEventListener('click', () => navigate(1));
  $('#todayBtn').addEventListener('click', () => { S.anchor = parseD(S.today); renderView(); });

  // 搜索
  $('#searchInput').addEventListener('input', e => {
    S.search = e.target.value;
    $('#searchClear').classList.toggle('hidden', !S.search);
    renderAll();
  });
  $('#searchClear').addEventListener('click', () => {
    S.search = ''; $('#searchInput').value = '';
    $('#searchClear').classList.add('hidden'); renderAll();
  });

  // 排序 / 全部计划
  $('#sortSelect').value = S.sort;
  $('#sortSelect').addEventListener('change', e => { S.sort = e.target.value; savePrefs(); renderSidebar(); });
  $('#allPlansBtn').addEventListener('click', () => { S.filterPlan = null; savePrefs(); renderAll(); });

  // 新建 / 导入 / 导出
  $('#newPlanBtn').addEventListener('click', () => openPlanModal());
  $('#importBtn').addEventListener('click', () => $('#fileInput').click());
  $('#fileInput').addEventListener('change', e => { handleFiles(Array.from(e.target.files)); e.target.value = ''; });
  $('#exportAllBtn').addEventListener('click', () => { window.location.href = '/api/export'; });
  $('#importConfirm').addEventListener('click', confirmImport);

  // 计划弹窗
  $('#pmSubmit').addEventListener('click', submitPlanModal);
  $('#pmAddRow').addEventListener('click', () => {
    pmTasks.push({ title: '', date: $('#pmStart').value });
    renderPmRows();
    const rows = $$('#pmTaskRows .row-title');
    if (rows.length) rows[rows.length - 1].focus();
  });
  $$('.pm-tabs button').forEach(b => b.addEventListener('click', () => switchPmTab(b.dataset.tab)));
  $('#pmPaste').addEventListener('input', updatePmCounts);
  $('#pmPasteAdd').addEventListener('click', () => {
    const pp = parsePaste();
    if (!pp.length) return;
    pmTasks = pmTasks.filter(t => t.title.trim()).concat(pp);
    $('#pmPaste').value = '';
    renderPmRows(); renderPmPreview(); updatePmCounts();
    toast(`已添加 ${pp.length} 条任务`);
  });
  $('#pmRepeatTitle').addEventListener('input', updatePmCounts);
  $$('#pmWeekdays button').forEach(b => b.addEventListener('click', () => { b.classList.toggle('on'); updatePmCounts(); }));
  $('#pmRepeatAdd').addEventListener('click', () => {
    const rp = repeatTasks();
    if (!rp.length) { toast('请先填写标题并选择至少一个星期'); return; }
    pmTasks = pmTasks.filter(t => t.title.trim()).concat(rp);
    renderPmRows(); renderPmPreview();
    toast(`已生成 ${rp.length} 条重复任务`);
  });
  $$('.range-chips button').forEach(b => b.addEventListener('click', () => {
    const start = $('#pmStart').value || S.today;
    $('#pmEnd').value = fmtD(addDays(parseD(start), +b.dataset.days - 1));
    updatePmCounts();
  }));
  $('#pmStart').addEventListener('change', updatePmCounts);
  $('#pmEnd').addEventListener('change', updatePmCounts);

  // 任务弹窗
  $('#tmSave').addEventListener('click', submitTaskModal);
  $('#tmDelete').addEventListener('click', () => {
    if (!tmCtx) return;
    const { planId, taskId } = tmCtx;
    $('#taskModal').classList.add('hidden');
    tmCtx = null;
    deleteTask(planId, taskId);
  });

  // 弹窗关闭
  $$('.modal-close').forEach(b => b.addEventListener('click', () => {
    b.closest('.modal-backdrop').classList.add('hidden');
    if (b.closest('#taskModal')) tmCtx = null;
  }));
  $$('.modal-backdrop').forEach(bd => bd.addEventListener('mousedown', e => {
    if (e.target === bd) { bd.classList.add('hidden'); if (bd.id === 'taskModal') tmCtx = null; }
  }));

  // 抽屉
  $('#drawerScrim').addEventListener('click', closeDrawer);

  // 快速添加
  $('#qaSubmit').addEventListener('click', submitQuickAdd);
  $('#qaTitle').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) submitQuickAdd(); });
  document.addEventListener('mousedown', e => {
    const qa = $('#quickAdd');
    if (!qa.classList.contains('hidden') && !qa.contains(e.target) && !e.target.closest('[data-quickadd]')) closeQuickAdd();
  });

  // 主区域事件委托
  $('#viewRoot').addEventListener('click', e => {
    const el = e.target.closest('[data-toggle],[data-edit],[data-del],[data-goto],[data-quickadd],[data-carry]');
    if (!el) return;
    if (el.dataset.toggle) { const [p, t] = el.dataset.toggle.split('|'); toggleTask(p, t); }
    else if (el.dataset.edit) { const [p, t] = el.dataset.edit.split('|'); openTaskModal(p, t); }
    else if (el.dataset.del) { const [p, t] = el.dataset.del.split('|'); deleteTask(p, t); }
    else if (el.dataset.carry) { const [p, t] = el.dataset.carry.split('|'); carryTask(p, t); }
    else if (el.dataset.quickadd) { e.stopPropagation(); openQuickAdd(el.dataset.quickadd, el); }
    else if (el.dataset.goto) { S.anchor = parseD(el.dataset.goto); S.view = 'day'; savePrefs(); renderView(); }
  });
  // 抽屉内委托
  $('#drawerContent').addEventListener('click', e => {
    const el = e.target.closest('[data-toggle],[data-edit],[data-del]');
    if (!el) return;
    if (el.dataset.toggle) { const [p, t] = el.dataset.toggle.split('|'); toggleTask(p, t); }
    else if (el.dataset.edit) { const [p, t] = el.dataset.edit.split('|'); openTaskModal(p, t); }
    else if (el.dataset.del) { const [p, t] = el.dataset.del.split('|'); deleteTask(p, t); }
  });

  // 文件拖放
  let dragDepth = 0;
  window.addEventListener('dragenter', e => {
    if (e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')) {
      dragDepth++; $('#dropOverlay').classList.remove('hidden');
    }
  });
  window.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) $('#dropOverlay').classList.add('hidden');
  });
  window.addEventListener('dragover', e => {
    if (e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault();
  });
  window.addEventListener('drop', e => {
    if (e.dataTransfer && e.dataTransfer.files.length) {
      e.preventDefault();
      dragDepth = 0; $('#dropOverlay').classList.add('hidden');
      handleFiles(Array.from(e.dataTransfer.files));
    }
  });

  // 移动端侧栏
  $('#sidebarToggle').addEventListener('click', () => {
    document.body.classList.toggle('sidebar-open');
    $('#sidebarScrim').classList.toggle('hidden', !document.body.classList.contains('sidebar-open'));
  });
  $('#sidebarScrim').addEventListener('click', () => {
    document.body.classList.remove('sidebar-open');
    $('#sidebarScrim').classList.add('hidden');
  });

  // 键盘
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (!$('#quickAdd').classList.contains('hidden')) { closeQuickAdd(); return; }
      const open = $$('.modal-backdrop').find(m => !m.classList.contains('hidden'));
      if (open) { open.classList.add('hidden'); if (open.id === 'taskModal') tmCtx = null; return; }
      if ($('#drawer').classList.contains('open')) { closeDrawer(); return; }
      if (document.body.classList.contains('sidebar-open')) {
        document.body.classList.remove('sidebar-open'); $('#sidebarScrim').classList.add('hidden');
      }
      return;
    }
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.isComposing) return;
    if ($$('.modal-backdrop').some(m => !m.classList.contains('hidden'))) return;
    if (e.key === 'n' || e.key === 'N') { e.preventDefault(); openPlanModal(); }
    else if (e.key === 't' || e.key === 'T') { S.anchor = parseD(S.today); renderView(); }
    else if (e.key === '1') { S.view = 'month'; savePrefs(); renderView(); }
    else if (e.key === '2') { S.view = 'week'; savePrefs(); renderView(); }
    else if (e.key === '3') { S.view = 'day'; savePrefs(); renderView(); }
    else if (e.key === '/') { e.preventDefault(); $('#searchInput').focus(); }
    else if (e.key === 'ArrowLeft') navigate(-1);
    else if (e.key === 'ArrowRight') navigate(1);
  });

  window.addEventListener('resize', () => {
    const act = $(`.view-switch button[data-view="${S.view}"]`);
    const pill = $('.switch-pill');
    if (act && pill) {
      pill.style.width = act.offsetWidth + 'px';
      pill.style.transform = `translateX(${act.offsetLeft - 3}px)`;
    }
  });
  const mq = window.matchMedia('(max-width: 560px)');
  const onMq = () => renderView();
  if (mq.addEventListener) mq.addEventListener('change', onMq);
  else if (mq.addListener) mq.addListener(onMq);
}

function navigate(dir) {
  if (S.view === 'month') S.anchor = new Date(S.anchor.getFullYear(), S.anchor.getMonth() + dir, 1);
  else if (S.view === 'week') S.anchor = addDays(S.anchor, dir * 7);
  else S.anchor = addDays(S.anchor, dir);
  renderView();
}

/* ================= 对外钩子（供 chat.js 使用） ================= */
window.PCB = {
  get plans() { return S.plans; },
  get today() { return S.today; },
  api, toast,
  refresh: async () => { await reloadState(); renderAll(); },
};

/* ================= 启动 ================= */
(async function init() {
  loadPrefs();
  try {
    await reloadState();
  } catch (err) {
    $('#viewRoot').innerHTML = `<div class="empty-state"><div class="empty-title">无法连接本地服务</div>
      <div class="empty-sub">${esc(err.message)}<br>请确认 app.py 正在运行</div></div>`;
    return;
  }
  if (S.filterPlan && !planById(S.filterPlan)) S.filterPlan = null;
  S.anchor = parseD(S.today);
  bindEvents();
  renderAll();
})();
