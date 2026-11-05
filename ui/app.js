'use strict';
/* 前端只做渲染：所有数据、排序、进度与预测都由 Python 侧算好并下发。 */
(function () {
  var api = null;
  var current = null;
  var toastTimer = null;

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function el(id) { return document.getElementById(id); }

  function toast(msg, kind) {
    var box = el('toast');
    if (!box || !msg) return;
    box.textContent = msg;
    box.className = 'toast show' + (kind === 'error' ? ' toast--error' : '');
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () { box.className = 'toast'; }, 2600);
  }

  /* ---------------- 共用片段 ---------------- */
  function prioBadge(p) {
    p = p || 'P2';
    return '<span class="prio prio--' + esc(p) + '">' + esc(p) + '</span>';
  }
  function predictLine(p) {
    if (!p) return '';
    return '<span class="' + (p.ok ? 'predict' : 'muted') + '" title="' + esc(p.detail || '') + '">' +
      esc(p.label) + '</span>';
  }
  function bar(o) {
    var st = o.stats || { total: 0, done: 0, pct: 0 };
    var empty = !st.total;
    return '<div class="stat-head"><span class="stat-label">' + esc(o.label) + '</span>' +
        '<span class="stat-nums">' + st.done + '/' + st.total + ' · ' + (empty ? 0 : st.pct) + '%</span></div>' +
      '<div class="bar' + (empty ? ' bar--empty' : '') + '"><div class="bar-fill" style="width:' +
        (empty ? 0 : st.pct) + '%;background:' + o.color + '"></div></div>' +
      '<div class="stat-foot">' + (empty
        ? '<span class="muted">该范围暂无' + esc(o.emptyWord || '任务') + '</span>'
        : predictLine(o.prediction)) + '</div>';
  }
  function crumbsHtml(crumbs) {
    return crumbs.map(function (c, i) {
      var sep = i ? '<span class="crumb-sep">/</span>' : '';
      if (c.current) return sep + '<span class="crumb-current" aria-current="page">' + esc(c.label) + '</span>';
      return sep + '<button class="crumb" type="button" data-act="crumb" data-page="' + c.page + '">' +
        esc(c.label) + '</button>';
    }).join('');
  }

  /* ---------------- 第 1 页 ---------------- */
  function page1(v) {
    var p = v.page1;
    var rows = p.files.map(function (f) {
      return '<div class="file-row' + (f.error ? ' is-error' : '') + '">' +
          '<div class="file-main"><span class="file-name">' + esc(f.displayName) + '</span>' +
            '<span class="file-sub">' + esc(f.sub) + '</span></div>' +
          '<button class="btn btn-small" type="button" data-act="remove-file" data-path="' + esc(f.path) + '">移除</button>' +
        '</div>';
    }).join('');
    return '<section class="page page-1">' +
        '<div class="page-head"><h1>选择任务 · 任务进度追踪</h1></div>' +
        '<p class="lead">选择题库 JSON（可一次多选，也可分多次追加）。列表名优先取 <code>meta.groupName</code>，' +
          '缺失时回退到文件名 <code>_checkbox_use</code> 之前的部分；勾选会直接写回原文件。</p>' +
        '<div class="drop card"><span class="drop-badge">JSON</span>' +
          '<button class="btn btn-primary" type="button" data-act="pick-files">选择文件</button>' +
          '<div class="muted small">支持多选与追加；建议同时载入健身组，月度/周度页会汇总健身任务</div></div>' +
        '<div class="file-section"><div class="section-head"><h2>已选择</h2>' +
          '<span class="muted small">' + p.total + ' 个文件 · ' + p.valid + ' 个可用（按任务数从高到低）</span></div>' +
          (p.files.length ? '<div class="file-list">' + rows + '</div>'
            : '<div class="empty-state">还没有选择文件。可先用 <code>sample_data/</code> 下的示例跑通四页。</div>') +
        '</div>' +
        '<div class="autosave card"><div class="autosave-main">' +
          '<div><span class="autosave-title">自动写盘</span>' +
            '<span class="autosave-status" id="autosaveStatus">' + esc(p.writeStatus) + '</span></div>' +
          '<div class="autosave-note">勾选/取消会立即写回该组原 JSON，只改 <code>done</code> / <code>doneAt</code> / ' +
            '<code>history</code>，键序、缩进与换行风格保持原样；外部改动会先按最新文件合并。</div>' +
        '</div><div class="autosave-actions"><span class="muted small">直接读写本地文件</span></div></div>' +
        '<div class="page-actions">' +
          '<button class="btn" type="button" data-act="clear-files"' + (p.files.length ? '' : ' disabled') + '>清空</button>' +
          '<button class="btn btn-primary" type="button" data-act="to-overview"' + (p.valid ? '' : ' disabled') + '>进入总览</button>' +
        '</div></section>';
  }

  /* ---------------- 第 2 页 ---------------- */
  function heatmap(h) {
    var yearBtns = h.years.length > 1 ? '<div class="heat-years">' + h.years.map(function (y) {
      return '<button type="button" class="heat-year' + (y === h.selected ? ' is-active' : '') +
        '" data-act="heat-year" data-year="' + y + '">' + y + ' 年</button>';
    }).join('') + '</div>' : '';
    var months = h.months.map(function (m) {
      return '<span class="heat-month" style="width:' + m.width + 'px">' + esc(m.label) + '</span>';
    }).join('');
    var cells = h.cells.map(function (c) {
      if (c.out) return '<span class="heat-cell is-out"></span>';
      return '<button type="button" class="heat-cell' + (c.level ? ' ' + c.level : '') +
        (c.active ? ' is-active' : '') + '" data-act="heat-day" data-date="' + c.key +
        '" title="' + esc(c.title) + '" aria-label="' + esc(c.title) + '"></button>';
    }).join('');
    return '<div class="heat-card card"><div class="heat-head">' +
        '<span class="heat-title">年度完成热力图</span>' + yearBtns + '</div>' +
      '<div class="heat-scroll"><div class="heat-inner"><div class="heat-months">' + months +
        '</div><div class="heat-grid">' + cells + '</div></div></div>' +
      '<div class="heat-foot"><span>本年完成 ' + h.yearDone + ' 项，累计 ' + h.uniqTotal + ' 项任务，完成率 ' +
        h.uniqPct + '%（已完成 ' + h.uniqDone + ' 项）</span>' +
        (h.tipText ? '<span class="heat-tip">' + esc(h.tipText) + '</span>' : '') + '</div>' +
      (h.totalDone ? '' : '<div class="heat-empty">暂无完成记录</div>') + '</div>';
  }

  function overviewCalendar(c) {
    if (!c) return '';
    var weekday = c.weekdays.map(function (w) { return '<div class="cal-weekday">' + w + '</div>'; }).join('');
    var cells = c.cells.map(function (cell) {
      if (cell.empty) return '<div class="cal-cell cal-cell--multi is-empty" aria-hidden="true"></div>';
      var chips = cell.chips.map(function (s) {
        return '<span class="cal-subj' + (s.isDone ? ' is-done' : '') + '" style="--sc:' + s.strong +
          ';--sc-soft:' + s.soft + '" title="' + esc(s.name + '：已完成 ' + s.done + '/' + s.total + ' 项') + '">' +
          '<i></i><b>' + esc(s.name) + '</b>' + s.done + '/' + s.total + '</span>';
      }).join('');
      return '<button type="button" class="cal-cell cal-cell--multi" data-act="open-day" data-date="' + cell.date +
        '" aria-label="查看 ' + cell.date + ' 全部科目任务"><span class="cal-day">' + cell.day +
        (cell.count ? '<em>' + cell.count + ' 项</em>' : '') + '</span>' + chips +
        (cell.more ? '<span class="cal-more">+' + cell.more + ' 科</span>' : '') +
        '<span class="cal-min">' + esc(cell.minutesText) + '</span></button>';
    }).join('');
    var legend = c.legend.map(function (g) {
      return '<span class="cal-legend-item"><span class="cal-legend-dot" style="background:' + g.color +
        '"></span>' + esc(g.name) + ' <b>' + g.count + '</b></span>';
    }).join('');
    return '<div class="month-cal card"><div class="cal-head">' +
        '<span class="cal-title">' + esc(c.title) + '</span><span class="cal-note">' + esc(c.note) + '</span>' +
        '<div class="cal-nav">' + (c.isCurMonth ? '' :
          '<button class="btn btn-small" type="button" data-act="ov-month-today">回到本月</button>') +
          '<button class="btn btn-small" type="button" data-act="ov-month-prev" aria-label="上一月">‹ 上月</button>' +
          '<button class="btn btn-small" type="button" data-act="ov-month-next" aria-label="下一月">下月 ›</button>' +
        '</div></div>' +
      '<div class="cal-scroll"><div class="calendar">' + weekday + cells + '</div></div>' +
      (legend ? '<div class="cal-legend">' + legend + '</div>' : '') +
      '<div class="cal-note" style="margin-top:6px">同一格内按科目并列展示（最多 3 科，超出显示 +N 科）；' +
        '点击日期查看当日全部科目任务。科目顺序与下方组横条一致。</div></div>';
  }

  function groupCards(groups) {
    return '<div class="group-grid">' + groups.map(function (g) {
      var topics = g.topics.map(function (t) {
        return '<span class="topic-item"><b>' + esc(t.topic) + '</b>' +
          t.texts.map(function (x) { return '<span class="ym">' + esc(x) + '</span>'; }).join('') + '</span>';
      }).join('');
      return '<article class="group-card" role="button" tabindex="0" data-act="open-group" data-path="' + esc(g.path) +
          '" style="--gc:' + g.mustKb + ';--gc-soft:' + g.soft + '">' +
        '<div class="group-head"><div><div class="group-name">' + esc(g.name) + '</div>' +
          '<div class="group-sub">' + esc(g.subject) + '</div></div>' +
          '<span class="kind-tag ' + (g.fit ? 'kind-fitness' : 'kind-study') + '">' + esc(g.kindLabel) + '</span></div>' +
        '<div class="topic-list">' + topics + '</div>' +
        '<div class="card-progress">' + bar({ label: '任务完成', stats: g.stats, color: g.mustKb,
          prediction: g.prediction }) + '</div></article>';
    }).join('') + '</div>';
  }

  function dayDetail(d) {
    if (!d) return '';
    var rows = d.rows.map(function (r) {
      return '<li class="cal-day-row' + (r.done ? ' is-done' : '') + '">' +
        '<span class="cal-subj cal-subj--tag" style="--sc:' + r.strong + ';--sc-soft:' + r.soft + '">' +
          '<i></i><b>' + esc(r.name) + '</b></span>' + prioBadge(r.priority) +
        '<span class="task-title">' + esc(r.title) + '</span>' +
        '<span class="task-meta">' + esc(r.minutesText) +
          (r.slot ? '<span>' + esc(r.slot) + '</span>' : '') +
          (r.was ? '<span class="task-was">' + esc(r.was) + '</span>' : '') + '</span></li>';
    }).join('');
    return '<div class="cal-detail" role="dialog" aria-modal="true" aria-label="当日任务">' +
      '<div class="cal-modal"><div class="cal-modal-head"><div><h3>' + esc(d.title) + '</h3>' +
        '<div class="cal-modal-sub">' + esc(d.sub) + '</div></div>' +
        '<button class="btn btn-small" type="button" data-act="close-day">关闭</button></div>' +
      (d.rows.length ? '<ul class="cal-day-list">' + rows + '</ul>'
        : '<div class="empty-state" style="margin-top:10px">当日暂无任务</div>') + '</div></div>';
  }

  function page2(v) {
    if (!v.groups.length) {
      return '<section class="page"><div class="empty-state">还没有可用的题库，请先返回选择文件。</div></section>';
    }
    return '<section class="page page-2"><div class="page-head"><h1>总览</h1>' +
        '<span class="muted small">' + v.head.groups + ' 组 · ' + v.head.tasks + ' 项任务</span></div>' +
      '<p class="lead">点击组横条进入月度安排。灰色文字是该组的「板块 月份」汇总；顶部热力图按完成时间统计。</p>' +
      heatmap(v.heat) + overviewCalendar(v.calendar) + groupCards(v.groups) + dayDetail(v.dayDetail) + '</section>';
  }

  /* ---------------- 第 3 页 ---------------- */
  function subjectCalendar(c) {
    if (!c) return '';
    var weekday = c.weekdays.map(function (w) { return '<div class="cal-weekday">' + w + '</div>'; }).join('');
    var cells = c.cells.map(function (cell) {
      if (cell.empty) return '<div class="cal-cell is-empty" aria-hidden="true"></div>';
      var tasks = cell.tasks.map(function (t) {
        var cls = t.fit ? 'cal-task--fitness' : 'cal-task--' + esc(t.priority);
        return '<span class="cal-task ' + cls + (t.done ? ' is-done' : '') + '" title="' + esc(t.title) + '">' +
          esc(t.title) + '</span>';
      }).join('');
      return '<button type="button" class="cal-cell" data-act="open-day" data-date="' + cell.date + '">' +
        '<span class="cal-day">' + cell.day + (cell.count ? '<em>' + cell.count + ' 项</em>' : '') + '</span>' +
        tasks + (cell.more ? '<span class="cal-more">+' + cell.more + ' 项</span>' : '') +
        '<span class="cal-min">' + esc(cell.minutesText) + '</span></button>';
    }).join('');
    return '<div class="month-cal card"><div class="cal-head"><span class="cal-title">' + esc(c.title) + '</span>' +
      '<span class="cal-note">' + esc(c.note) + '</span></div>' +
      '<div class="cal-scroll"><div class="calendar">' + weekday + cells + '</div></div>' +
      '<div class="cal-note" style="margin-top:6px">格内按 P0 → P1 → P2 排序，已完成任务灰字删除线下沉；' +
        '健身任务固定绿色；格内右下角为该日总时长。</div></div>';
  }

  function page3(v) {
    if (v.empty) return '<section class="page"><div class="empty-state">' + esc(v.empty) + '</div></section>';
    var chips = v.chips.map(function (c) {
      return '<button class="chip' + (c.active ? ' is-active' : '') + '" type="button" data-act="select-month" ' +
        'data-month="' + esc(c.id) + '">' + esc(c.label) + '</button>';
    }).join('');
    var cards = v.cards.map(function (m) {
      var lines = m.tasks.map(function (t) {
        return '<li class="task-line' + (t.done ? ' is-done' : '') + '">' + prioBadge(t.priority) +
          '<span class="task-title">' + esc(t.title) + '</span><span class="task-meta">' +
          (t.fit ? '<span class="tag tag--fitness">健身</span>' : '') +
          '<span>' + esc(t.dateText) + '</span><span>' + esc(t.minutesText) + '</span>' +
          (t.was ? '<span class="task-was">' + esc(t.was) + '</span>' : '') + '</span></li>';
      }).join('');
      return '<article class="month-card card' + (m.complete ? ' is-complete' : '') + '" role="button" tabindex="0" ' +
          'data-act="open-month" data-month="' + esc(m.id) + '"><div class="month-head"><div>' +
          '<h2>' + esc(m.label) + (m.complete ? '<span class="month-done-tag">已完成</span>' : '') + '</h2>' +
          '<div class="muted small">' + m.total + ' 项 · 已完成 ' + m.done + ' 项 · 共 ' + esc(m.minutesText) + '</div>' +
        '</div><span class="chev">进入周度 →</span></div>' +
        (m.tasks.length ? '<ul class="task-list">' + lines + '</ul>'
          : '<div class="empty-state" style="margin-top:12px">该月暂无任务</div>') + '</article>';
    }).join('');
    return '<section class="page page-3"><div class="page-head">' +
        '<button class="btn btn-small" type="button" data-act="back">← 返回总览</button>' +
        '<h1>' + esc(v.groupName) + ' <span class="muted">· 月度</span></h1></div>' +
      '<p class="lead">' + esc(v.lead) + '</p>' +
      '<div class="month-tabs">' + chips + '</div>' +
      '<div class="stat-panel card"><div>' + bar({ label: v.stat.label, stats: v.stat.stats, color: v.stat.color,
        emptyWord: v.stat.label + '任务', prediction: v.stat.prediction }) + '</div>' +
        '<div class="stat-scope">' + esc(v.stat.scope) + '</div></div>' +
      subjectCalendar(v.calendar) +
      '<div class="month-list">' + (cards || '<div class="empty-state">该组没有月份数据</div>') + '</div>' +
      dayDetail(v.dayDetail) + '</section>';
  }

  /* ---------------- 第 4 页 ---------------- */
  function page4(v) {
    if (v.empty) return '<section class="page"><div class="empty-state">' + esc(v.empty) + '</div></section>';
    var bars = v.bars.map(function (b) {
      return '<div>' + bar({ label: b.label, stats: b.stats, color: b.color, emptyWord: b.emptyWord,
        prediction: b.prediction }) + '</div>';
    }).join('');
    var weeks = v.weeks.map(function (w) {
      var body = '';
      if (w.open) {
        body = '<div class="week-body">' + (w.days.length ? w.days.map(function (d) {
          var rows = d.tasks.map(function (t) {
            return '<label class="task-row ' + (t.fit ? 'task-row--fitness' : 'task-row--study') +
                (t.done ? ' is-done' : '') + '"><input type="checkbox" data-path="' + esc(t.path) +
                '" data-task-id="' + esc(t.id) + '"' + (t.done ? ' checked' : '') + ' />' +
              '<span class="task-body"><span class="task-title">' + esc(t.title) + '</span>' +
                '<span class="task-meta">' + prioBadge(t.priority) + '<span>' + esc(t.minutesText) + '</span>' +
                  (t.slot ? '<span>' + esc(t.slot) + '</span>' : '') +
                  (t.fit ? '<span class="tag tag--fitness">健身</span>' : '') + '</span></span>' +
              '<span class="task-time' + (t.done ? ' is-done' : '') + '">' + esc(t.timeText) + '</span></label>';
          }).join('');
          return '<div class="day-group"><div class="day-head">' + esc(d.head) +
            '<span class="muted">' + esc(d.sub) + '</span></div>' + rows + '</div>';
        }).join('') : '<div class="empty-state" style="margin-top:10px">本周没有任务</div>') + '</div>';
      }
      return '<section class="week-card card' + (w.open ? ' is-open' : '') + '">' +
        '<button class="week-head" type="button" data-act="toggle-week" data-week="' + esc(w.key) +
          '" aria-expanded="' + (w.open ? 'true' : 'false') + '"><span class="week-head-main">' +
          '<span class="week-title">' + esc(w.title) + '</span>' +
          '<span class="week-sub muted">' + esc(w.sub) + '</span></span>' +
          '<span class="week-progress"><b>' + w.pct + '%</b> ' + w.done + '/' + w.total + '</span>' +
          '<span class="chev-arrow">▾</span></button>' + body + '</section>';
    }).join('');
    return '<section class="page page-4"><div class="page-head">' +
        '<button class="btn btn-small" type="button" data-act="back">← 返回月度</button>' +
        '<h1>' + esc(v.groupName) + ' <span class="muted">· ' + esc(v.monthLabel) + ' · 周度</span></h1></div>' +
      '<p class="lead">' + esc(v.lead) + '</p>' +
      '<div class="stat-panel card">' + bars + '<div class="stat-scope">' + esc(v.scope) + '</div></div>' +
      '<div class="week-list">' + (weeks || '<div class="empty-state">该月没有周数据</div>') + '</div></section>';
  }

  /* ---------------- 渲染与事件 ---------------- */
  function render(view) {
    current = view;
    var app = el('app');
    var y = window.scrollY || 0;
    var html = view.page === 1 ? page1(view)
      : view.page === 2 ? page2(view)
      : view.page === 3 ? page3(view) : page4(view);
    app.innerHTML = html;
    el('crumbs').innerHTML = crumbsHtml(view.crumbs);
    document.title = view.title;
    window.scrollTo(0, view.page === 2 || view.page === 1 ? 0 : Math.min(y, 220));
  }

  function apply(resp) {
    if (!resp) return;
    if (resp.view) render(resp.view);
    var r = resp.result || {};
    if (r.message) toast(r.message, r.kind);
  }

  function call(method, a, b) {
    if (!api || !api[method]) { toast('桥接尚未就绪', 'error'); return; }
    var p = method === 'do_action' ? api.do_action(a, b) : api[method]();
    p.then(apply).catch(function (e) { toast('操作失败：' + (e && e.message ? e.message : e), 'error'); });
  }

  var actions = {
    'pick-files': function () { call('pick_files'); },
    'import-progress': function () { call('import_progress'); },
    'export-progress': function () { call('export_progress'); },
    'remove-file': function (t) { call('do_action', 'remove_file', { path: t.getAttribute('data-path') }); },
    'clear-files': function () { call('do_action', 'clear_files'); },
    'to-overview': function () { call('do_action', 'to_overview'); },
    'open-group': function (t) { call('do_action', 'open_group', { path: t.getAttribute('data-path') }); },
    'select-month': function (t) { call('do_action', 'select_month', { month: t.getAttribute('data-month') }); },
    'open-month': function (t) { call('do_action', 'open_month', { month: t.getAttribute('data-month') }); },
    'toggle-week': function (t) { call('do_action', 'toggle_week', { week: t.getAttribute('data-week') }); },
    'back': function () { call('do_action', 'back'); },
    'crumb': function (t) { call('do_action', 'crumb', { page: +t.getAttribute('data-page') }); },
    'heat-year': function (t) { call('do_action', 'heat_year', { year: +t.getAttribute('data-year') }); },
    'heat-day': function (t) { call('do_action', 'heat_day', { date: t.getAttribute('data-date') }); },
    'ov-month-prev': function () { call('do_action', 'ov_month_prev'); },
    'ov-month-next': function () { call('do_action', 'ov_month_next'); },
    'ov-month-today': function () { call('do_action', 'ov_month_today'); },
    'open-day': function (t) { call('do_action', 'open_day', { date: t.getAttribute('data-date') }); },
    'close-day': function () { call('do_action', 'close_day'); },
    'reselect': function () { call('do_action', 'reselect'); }
  };

  function onClick(e) {
    if (e.target && e.target.classList && e.target.classList.contains('cal-detail')) {
      call('do_action', 'close_day');
      return;
    }
    var node = e.target.closest ? e.target.closest('[data-act]') : null;
    if (!node || node.disabled) return;
    var fn = actions[node.getAttribute('data-act')];
    if (fn) fn(node);
  }

  function onChange(e) {
    var cb = e.target;
    if (!cb || cb.tagName !== 'INPUT' || cb.type !== 'checkbox') return;
    var path = cb.getAttribute('data-path');
    var id = cb.getAttribute('data-task-id');
    if (!path || !id) return;
    call('do_action', 'toggle_task', { path: path, id: id, checked: cb.checked });
  }

  function onKeydown(e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var node = e.target.closest ? e.target.closest('[data-act][role="button"]') : null;
    if (!node) return;
    e.preventDefault();
    node.click();
  }

  function boot() {
    api = window.pywebview && window.pywebview.api;
    if (!api) return;
    document.addEventListener('click', onClick);
    document.addEventListener('change', onChange);
    document.addEventListener('keydown', onKeydown);
    el('btnExport').addEventListener('click', function () { actions['export-progress'](); });
    el('btnDataDir').addEventListener('click', function () { call('set_data_dir'); });
    el('btnReselect').addEventListener('click', function () { actions.reselect(); });
    var importLabel = document.querySelector('label[for="importInput"]');
    if (importLabel) importLabel.addEventListener('click', function (e) {
      e.preventDefault();
      actions['import-progress']();
    });
    api.get_view().then(function (view) {
      if (view) render(view);
    }).catch(function (e) { toast('初始化失败：' + (e && e.message ? e.message : e), 'error'); });
  }

  window.addEventListener('pywebviewready', boot);
  if (window.pywebview && window.pywebview.api) boot();
})();
