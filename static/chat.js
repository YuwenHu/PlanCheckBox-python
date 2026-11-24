/* PlanCheckBox · AI 助手
   实现方法参考 deepseek-ai/chat-demo（浏览器直连 API、SSE 流式、Key 仅存浏览器），
   并扩展为兼容两类服务：
   - OpenAI 兼容 Chat Completions（默认；api.deepseek.com 及各类网关）
   - Anthropic 兼容 Messages（DeepSeek 官方 /anthropic 路径，chat-demo 同款协议）
   SSE 解析按 WHATWG 规范实现（字段累积 / 空行派发 / 注释忽略 / 跨分片多字节安全）。
   错误分类：http / stream / network / interrupted / protocol。
   若网关不允许浏览器跨域，自动降级为经本机 app.py 转发（Key 仅透传不保存）。
   会话历史持久化到本应用 data/chat/ 目录（Key 除外）。 */
'use strict';

(function () {
  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));
  const SETTINGS_KEY = 'plancheckbox-chat-settings';
  const PROXY_HOSTS_KEY = 'plancheckbox-chat-proxy-hosts';
  const DEFAULTS = {
    key: '', origin: 'https://api.deepseek.com', model: 'deepseek-chat',
    thinking: false, protocol: 'openai', transport: 'auto',
  };

  let settings = loadSettings();
  let proxyHosts = loadProxyHosts();
  let sessions = [];
  let current = null;
  let generating = false;
  let abortCtrl = null;
  let saveTimer = null;
  let stickBottom = true;
  const createdProposals = {};

  function loadSettings() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}')); }
    catch (_) { return Object.assign({}, DEFAULTS); }
  }
  function persistSettings() {
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (_) {}
  }
  function loadProxyHosts() {
    try { return new Set(JSON.parse(localStorage.getItem(PROXY_HOSTS_KEY) || '[]')); }
    catch (_) { return new Set(); }
  }
  function markProxyHost(base) {
    proxyHosts.add(base);
    try { localStorage.setItem(PROXY_HOSTS_KEY, JSON.stringify(Array.from(proxyHosts))); } catch (_) {}
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function uid(prefix) {
    return prefix + '-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }
  function nowISO() { return new Date().toISOString(); }
  function PCB() { return window.PCB; }

  /* ================= URL 构造 ================= */
  /** 规范化基础地址：去尾斜杠与常见误粘的路径后缀，保留用户写的 /v1 */
  function baseOf(origin) {
    let o = String(origin || DEFAULTS.origin).trim().replace(/\s+/g, '');
    if (!o) o = DEFAULTS.origin;
    o = o.replace(/\/+$/, '');
    o = o.replace(/\/(chat\/completions|completions|messages|models)$/i, '');
    return o;
  }
  function chatURL(cfg) {
    const b = baseOf(cfg.origin);
    if (cfg.protocol === 'anthropic') {
      if (/\/anthropic(\/v1)?$/.test(b)) return b.replace(/\/$/, '') + (/\/v1$/.test(b) ? '/messages' : '/v1/messages');
      if (/\/v1$/.test(b)) return b.slice(0, -3) + '/anthropic/v1/messages';
      return b + '/anthropic/v1/messages';
    }
    return b + '/chat/completions';
  }
  function modelsURL(cfg) { return baseOf(cfg.origin) + '/models'; }
  function chatHeaders(cfg) {
    if (cfg.protocol === 'anthropic') return { 'x-api-key': cfg.key, 'Content-Type': 'application/json', Accept: 'text/event-stream' };
    return { Authorization: 'Bearer ' + cfg.key, 'Content-Type': 'application/json', Accept: 'text/event-stream' };
  }

  /* ================= SSE 解析（WHATWG 规范，移植自 chat-demo） ================= */
  const LINE_BREAK = /\r\n|\r|\n/g;
  class SSEDecoder {
    constructor() { this.buffer = ''; this.data = ''; this.hasData = false; this.eventType = ''; }
    push(text) {
      this.buffer += text;
      const events = [];
      let lineStart = 0;
      LINE_BREAK.lastIndex = 0;
      for (let m = LINE_BREAK.exec(this.buffer); m; m = LINE_BREAK.exec(this.buffer)) {
        if (m[0] === '\r' && LINE_BREAK.lastIndex === this.buffer.length) break;
        const ev = this.processLine(this.buffer.slice(lineStart, m.index));
        if (ev) events.push(ev);
        lineStart = LINE_BREAK.lastIndex;
      }
      this.buffer = this.buffer.slice(lineStart);
      return events;
    }
    end() {
      const ev = this.buffer.endsWith('\r') ? this.processLine(this.buffer.slice(0, -1)) : null;
      this.buffer = ''; this.data = ''; this.hasData = false; this.eventType = '';
      return ev ? [ev] : [];
    }
    processLine(line) {
      if (line === '') return this.dispatch();
      if (line.startsWith(':')) return null;
      const colon = line.indexOf(':');
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? '' : line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
      if (field === 'data') { this.data = this.hasData ? this.data + '\n' + value : value; this.hasData = true; }
      else if (field === 'event') this.eventType = value;
      return null;
    }
    dispatch() {
      const ev = this.hasData ? { event: this.eventType || 'message', data: this.data } : null;
      this.data = ''; this.hasData = false; this.eventType = '';
      return ev;
    }
  }

  async function* readSSE(body, signal) {
    const reader = body.getReader();
    const onAbort = () => reader.cancel().catch(() => {});
    if (signal) signal.addEventListener('abort', onAbort, { once: true });
    const td = new TextDecoder();
    const dec = new SSEDecoder();
    let finished = false;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          finished = true;
          yield* dec.push(td.decode());
          yield* dec.end();
          return;
        }
        yield* dec.push(td.decode(value, { stream: true }));
      }
    } finally {
      if (signal) signal.removeEventListener('abort', onAbort);
      if (!finished) reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  /* ================= 传输层：直连 / 本机代理 ================= */
  function chatErr(kind, message, status) {
    const e = new Error(message);
    e.kind = kind; e.status = status;
    return e;
  }
  async function readErrBody(res, kind) {
    const text = await res.text().catch(() => '');
    let message = text || res.statusText;
    try {
      const body = JSON.parse(text);
      const err = body && (body.error || body);
      if (err && typeof err.message === 'string') message = err.message;
      else if (err && err.error && typeof err.error.message === 'string') message = err.error.message;
    } catch (_) {}
    return chatErr(kind, message.slice(0, 300), res.status);
  }

  /** POST 聊天请求（直连或代理），返回 Response */
  async function llmPost(cfg, url, headers, body, signal) {
    const viaProxy = cfg.transport === 'proxy' ||
      (cfg.transport === 'auto' && proxyHosts.has(baseOf(cfg.origin)));
    if (!viaProxy) {
      try {
        return await fetch(url, {
          method: 'POST', headers, body: JSON.stringify(body), signal,
        });
      } catch (e) {
        if (signal && signal.aborted) throw e;
        if (cfg.transport === 'auto') {
          markProxyHost(baseOf(cfg.origin));
          if (PCB().toast) PCB().toast('该服务不允许浏览器跨域，已自动切换为经本机代理');
          return llmPost(cfg, url, headers, body, signal);
        }
        throw chatErr('network', '无法连接 API 服务（直连失败；可在设置把请求方式改为「自动」或「经本机代理」）');
      }
    }
    let res;
    try {
      res = await fetch('/api/llm/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, method: 'POST', headers, body }),
        signal,
      });
    } catch (e) {
      if (signal && signal.aborted) throw e;
      throw chatErr('network', e.message);
    }
    return res;
  }

  /** GET（/models 等），同样支持代理 */
  async function llmGet(cfg, url, headers, signal) {
    const viaProxy = cfg.transport === 'proxy' ||
      (cfg.transport === 'auto' && proxyHosts.has(baseOf(cfg.origin)));
    if (!viaProxy) {
      try {
        return await fetch(url, { headers, signal });
      } catch (e) {
        if (signal && signal.aborted) throw e;
        if (cfg.transport === 'auto') {
          markProxyHost(baseOf(cfg.origin));
          return llmGet(cfg, url, headers, signal);
        }
        throw chatErr('network', '无法连接 API 服务（' + e.message + '）');
      }
    }
    let res;
    try {
      res = await fetch('/api/llm/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, method: 'GET', headers, body: {} }),
        signal,
      });
    } catch (e) {
      if (signal && signal.aborted) throw e;
      throw chatErr('network', e.message);
    }
    return res;
  }

  /** GET /models 校验 Key（不产生费用） */
  async function verifyKey(cfg) {
    const res = await llmGet(cfg, modelsURL(cfg), { Authorization: 'Bearer ' + cfg.key });
    if (!res.ok) throw await readErrBody(res, 'http');
    return res.json();
  }

  async function fetchModels(cfg) {
    const data = await verifyKey(cfg);
    const list = (data && Array.isArray(data.data) ? data.data : []).map(m => m && m.id).filter(Boolean);
    if (!list.length) throw chatErr('protocol', '该服务返回的模型列表为空，请手动填写模型 ID');
    return list;
  }

  /**
   * 发起聊天并按统一回调消费流。
   * handlers: { onText(str), onThinking(str), signal }
   * 返回 { stopReason }；错误抛 chatErr。
   */
  async function streamChat(cfg, reqBody, handlers) {
    const res = await llmPost(cfg, chatURL(cfg), chatHeaders(cfg), reqBody, handlers.signal);
    if (!res.ok) throw await readErrBody(res, 'http');
    const ct = res.headers.get('Content-Type') || '';

    if (cfg.protocol === 'openai' && ct.includes('application/json')) {
      // 部分网关忽略 stream:true，直接返回完整 JSON —— 兼容处理
      const j = await res.json().catch(() => null);
      const choice = j && j.choices && j.choices[0];
      if (!choice) throw chatErr('protocol', '服务返回了无法解析的响应');
      if (choice.message && choice.message.reasoning_content) handlers.onThinking(choice.message.reasoning_content);
      if (choice.message && choice.message.content) handlers.onText(choice.message.content);
      return { stopReason: choice.finish_reason || 'end_turn' };
    }
    if (!res.body || !ct.includes('text/event-stream')) {
      throw await readErrBody(res, 'protocol');
    }

    if (cfg.protocol === 'anthropic') {
      return streamAnthropic(res, handlers);
    }
    return streamOpenAI(res, handlers);
  }

  /* Anthropic Messages SSE：content_block_start/delta/stop，message_delta(title)，message_stop */
  async function streamAnthropic(res, handlers) {
    for await (const { event, data } of readSSE(res.body, handlers.signal)) {
      let payload = null;
      try { payload = JSON.parse(data); } catch (_) { if (event !== 'error') continue; }
      if (payload && payload.error && typeof payload.error.message === 'string') {
        throw chatErr('stream', payload.error.message);
      }
      if (event === 'error') throw chatErr('stream', data);
      if (!payload || typeof payload.type !== 'string') continue;
      switch (payload.type) {
        case 'content_block_delta':
          if (payload.delta && payload.delta.type === 'text_delta') handlers.onText(payload.delta.text || '');
          else if (payload.delta && payload.delta.type === 'thinking_delta') handlers.onThinking(payload.delta.thinking || '');
          break;
        case 'message_delta':
          if (payload.delta && payload.delta.title) handlers.onTitle && handlers.onTitle(payload.delta.title);
          return { stopReason: (payload.delta && payload.delta.stop_reason) || 'end_turn' };
        case 'message_stop':
          return { stopReason: 'end_turn' };
        default:
          break;
      }
    }
    throw chatErr('interrupted', '回复在结束前中断');
  }

  /* OpenAI Chat Completions SSE：data: {choices:[{delta:{content|reasoning_content}}]} … [DONE] */
  async function streamOpenAI(res, handlers) {
    let gotDone = false;
    for await (const { data } of readSSE(res.body, handlers.signal)) {
      const payload = data.trim();
      if (!payload) continue;
      if (payload === '[DONE]') { gotDone = true; break; }
      let j = null;
      try { j = JSON.parse(payload); } catch (_) { continue; }
      if (j && j.error) {
        const m = typeof j.error === 'string' ? j.error : (j.error.message || '上游错误');
        throw chatErr('stream', m);
      }
      const choice = j && j.choices && j.choices[0];
      if (!choice) continue;
      const d = choice.delta || {};
      if (d.reasoning_content) handlers.onThinking(d.reasoning_content);
      if (d.content) handlers.onText(d.content);
      if (choice.finish_reason) gotDone = true;
    }
    if (!gotDone) throw chatErr('interrupted', '回复在结束前中断');
    return { stopReason: 'end_turn' };
  }

  function friendlyError(e, cfg) {
    cfg = cfg || settings;
    if (e.kind === 'network') return e.message || '无法连接 API 服务，请检查网络与 API 地址';
    if (e.kind === 'protocol') return 'API 返回了无法识别的响应：' + e.message + '。请确认 API 地址与协议选择是否匹配';
    if (e.kind === 'http') {
      if (e.status === 401) return 'API Key 无效或已过期（401），请在设置中检查';
      if (e.status === 402) return '账户余额不足（402）：' + e.message;
      if (e.status === 403) return '403：' + e.message + '。若提示模型不可用，请在设置点「拉取模型列表」，选择该 Key 可用的模型';
      if (e.status === 404) {
        if (cfg.protocol === 'anthropic') {
          return '404 Not Found：该地址没有 Anthropic 兼容端点。你的网关大概率是 OpenAI 兼容协议——请在设置把「API 协议」改为 OpenAI 兼容';
        }
        return '404 Not Found：API 地址或路径不对。填基础地址即可（如 https://网关域名/v1），应用会自动拼接 /chat/completions';
      }
      if (e.status === 429) return '请求过于频繁（429），稍后再试';
      return '请求失败（HTTP ' + e.status + '）：' + e.message;
    }
    if (e.kind === 'interrupted') return e.message + '，可点重试';
    return e.message || '请求失败';
  }

  /* ================= Markdown 渲染（零依赖） ================= */
  function inlineMD(text) {
    let s = esc(text);
    const codes = [];
    s = s.replace(/`([^`]+)`/g, (_, c) => {
      codes.push('<code class="inline">' + c + '</code>');
      return '\u0000' + (codes.length - 1) + '\u0000';
    });
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|mailto:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    if (!s.includes('<a ')) {
      s = s.replace(/(^|[\s>])(https?:\/\/[^\s<)]+)/g, (m, pre, url) =>
        pre + '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + url + '</a>');
    }
    s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => codes[+i]);
    return s;
  }
  function codeBlockHTML(lang, code) {
    return '<div class="cm-code"><div class="cm-code-head"><span>' + esc(lang || 'code') +
      '</span><button class="cm-code-copy" type="button">复制</button></div><pre><code>' +
      esc(code) + '</code></pre></div>';
  }
  function renderMarkdown(src) {
    const lines = String(src).split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(/^\s*```(\S*)\s*$/);
      if (fence) {
        const buf = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
        i++;
        out.push(codeBlockHTML(fence[1], buf.join('\n')));
        continue;
      }
      if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) { out.push('<h' + h[1].length + '>' + inlineMD(h[2]) + '</h' + h[1].length + '>'); i++; continue; }
      if (/^\s*>/.test(line)) {
        const buf = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, '')); i++; }
        out.push('<blockquote>' + buf.map(inlineMD).join('<br>') + '</blockquote>');
        continue;
      }
      if (line.includes('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
        const row = l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => inlineMD(c.trim()));
        const head = row(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { rows.push(row(lines[i])); i++; }
        out.push('<table><thead><tr>' + head.map(c => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>' +
          rows.map(r => '<tr>' + r.map(c => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</tbody></table>');
        continue;
      }
      if (/^\s*[-*]\s+/.test(line)) {
        const buf = [];
        while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { buf.push(lines[i].replace(/^\s*[-*]\s+/, '')); i++; }
        out.push('<ul>' + buf.map(x => '<li>' + inlineMD(x) + '</li>').join('') + '</ul>');
        continue;
      }
      if (/^\s*\d+[.、)]\s+/.test(line)) {
        const buf = [];
        while (i < lines.length && /^\s*\d+[.、)]\s+/.test(lines[i])) { buf.push(lines[i].replace(/^\s*\d+[.、)]\s+/, '')); i++; }
        out.push('<ol>' + buf.map(x => '<li>' + inlineMD(x) + '</li>').join('') + '</ol>');
        continue;
      }
      if (!line.trim()) { i++; continue; }
      const buf = [];
      while (i < lines.length && lines[i].trim() &&
        !/^\s*(```|#{1,4}\s|>|[-*]\s|\d+[.、)]\s)/.test(lines[i]) &&
        !/^\s*(---+|\*\*\*+)\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
      out.push('<p>' + buf.map(inlineMD).join('<br>') + '</p>');
    }
    return out.join('');
  }

  /* ================= 计划提案 ================= */
  const PLAN_FENCE = /```plan-json\s*\n([\s\S]*?)```/g;
  function splitProposals(text) {
    const parts = [];
    let last = 0, idx = 0, m;
    PLAN_FENCE.lastIndex = 0;
    while ((m = PLAN_FENCE.exec(text))) {
      if (m.index > last) parts.push({ type: 'md', text: text.slice(last, m.index) });
      let json = null;
      try { json = JSON.parse(m[1]); } catch (_) {}
      parts.push({ type: 'plan', json, raw: m[1], idx: idx++ });
      last = m.index + m[0].length;
    }
    if (last < text.length) parts.push({ type: 'md', text: text.slice(last) });
    return parts;
  }
  function proposalHTML(msg, part) {
    const p = part.json;
    if (!p || typeof p.name !== 'string' || !Array.isArray(p.tasks)) {
      return '<div class="plan-proposal"><div class="pp-invalid">计划数据不完整，无法一键创建（可让 AI 重新生成）</div></div>';
    }
    const color = ['pine', 'amber', 'coral', 'blue', 'mint', 'magenta', 'lavender', 'teal'].includes(p.color) ? p.color : 'pine';
    const tasks = p.tasks.filter(t => t && typeof t.title === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(t.date || ''));
    const created = (createdProposals[msg.id] || {})[part.idx];
    const shown = tasks.slice(0, 4);
    return '<div class="plan-proposal c-' + color + '">' +
      '<div class="pp-head"><span class="pp-emoji">' + esc(p.emoji || '🎯') + '</span>' +
      '<span style="flex:1;min-width:0"><span class="pp-name">' + esc(p.name) + '</span>' +
      '<div class="pp-range">' + esc(p.startDate || '') + ' → ' + esc(p.endDate || '') + ' · ' + tasks.length + ' 个任务</div></span>' +
      '<span class="pp-badge">AI 提案</span></div>' +
      (shown.length ? '<div class="pp-tasks">' + shown.map(t =>
        '<div class="pp-task"><span class="d">' + esc(t.date.slice(5).replace('-', '/')) + '</span><span class="t">' + esc(t.title) + '</span></div>').join('') + '</div>' : '') +
      (tasks.length > 4 ? '<div class="pp-more">…以及另外 ' + (tasks.length - 4) + ' 个任务</div>' : '') +
      '<div class="pp-foot">' + (created
        ? '<div class="pp-created">✓ 已创建「' + esc(created) + '」，可在左侧列表查看</div>'
        : '<button class="primary-btn pp-create" type="button" data-create-plan="' + msg.id + '|' + part.idx + '">＋ 创建此计划</button>') +
      '</div></div>';
  }
  function assistantBodyHTML(msg) {
    const parts = splitProposals(msg.text || '');
    return parts.map(part => part.type === 'md' ? renderMarkdown(part.text) : proposalHTML(msg, part)).join('');
  }
  async function createProposal(msgId, idx) {
    const msg = current && current.messages.find(x => x.id === msgId);
    if (!msg) return;
    const part = splitProposals(msg.text).filter(x => x.type === 'plan')[idx];
    if (!part || !part.json) return;
    const p = part.json;
    try {
      const np = await PCB().api('/api/plans', 'POST', {
        name: p.name, emoji: p.emoji || '🎯', color: p.color,
        description: p.description || '', startDate: p.startDate, endDate: p.endDate,
        tasks: (p.tasks || []).filter(t => t && t.title && t.date),
      });
      createdProposals[msgId] = Object.assign(createdProposals[msgId] || {}, { [idx]: np.name });
      await PCB().refresh();
      PCB().toast('已从 AI 提案创建计划「' + np.name + '」');
      renderMessages();
    } catch (e) { PCB().toast('创建失败：' + e.message); }
  }

  /* ================= 系统提示词（计划上下文） ================= */
  function systemPrompt() {
    const pcb = PCB();
    const today = pcb.today || new Date().toISOString().slice(0, 10);
    const plans = pcb.plans || [];
    let ctx;
    if (!plans.length) {
      ctx = '用户当前还没有任何计划。';
    } else {
      ctx = plans.map(p => {
        const done = p.tasks.filter(t => t.done).length;
        const todays = p.tasks.filter(t => t.date === today)
          .map(t => (t.done ? '[已完成] ' : '[未完成] ') + t.title).join('；') || '今日无任务';
        return '- ' + p.emoji + ' ' + p.name + '（' + p.startDate + ' ~ ' + p.endDate + '，进度 ' + done + '/' + p.tasks.length + '）：' + todays;
      }).join('\n');
    }
    return '你是 PlanCheckBox（纸间计划）应用内置的 AI 计划助手。今天是 ' + today + '。\n' +
      '用户当前的计划概况：\n' + ctx + '\n\n' +
      '职责：帮用户制定与调整计划、回答今天的安排、复盘进度、给出可执行的调整建议。' +
      '回答用简体中文，简洁友好，可用 Markdown（列表/表格/代码块），不要空泛说教。\n' +
      '当用户要求制定、新增或安排一个计划时，在回答中输出一个 ```plan-json 围栏代码块，内容为严格 JSON：\n' +
      '{"name":"计划名","emoji":"单个emoji","color":"pine|amber|coral|blue|mint|magenta|lavender|teal 之一",' +
      '"description":"一句话说明","startDate":"YYYY-MM-DD","endDate":"YYYY-MM-DD",' +
      '"tasks":[{"title":"任务标题","date":"YYYY-MM-DD"}]}\n' +
      '要求：日期合理（从今天或用户指定日期开始）、任务不超过 60 条、每天任务量适度；代码块外配简短说明。' +
      '用户可以在界面上一键创建该提案。不要虚构用户未提供的个人信息。';
  }

  /* ================= 会话管理 ================= */
  function newSession() {
    return { id: uid('c'), title: '新对话', createdAt: nowISO(), updatedAt: nowISO(), messages: [] };
  }
  async function loadSessions() {
    try {
      const data = await PCB().api('/api/chat/sessions');
      sessions = data.sessions || [];
    } catch (_) { sessions = []; }
  }
  function saveSoon() {
    if (!current || !current.messages.length) return;
    current.updatedAt = nowISO();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flushSave, 500);
  }
  async function flushSave() {
    clearTimeout(saveTimer);
    if (!current || !current.messages.length) return;
    const s = current;
    const i = sessions.findIndex(x => x.id === s.id);
    if (i >= 0) sessions[i] = s; else sessions.unshift(s);
    try {
      await PCB().api('/api/chat/sessions/' + s.id, 'PUT', {
        title: s.title, createdAt: s.createdAt, messages: s.messages,
      });
    } catch (e) { PCB().toast('会话保存失败：' + e.message); }
  }
  function switchSession(s) {
    if (generating) stopGeneration();
    flushSave();
    current = s;
    $('#chatTitle').textContent = s.title;
    renderMessages();
    hideSessionList();
  }
  async function deleteSession(s, ev) {
    if (ev) ev.stopPropagation();
    try { await PCB().api('/api/chat/sessions/' + s.id, 'DELETE'); } catch (_) {}
    sessions = sessions.filter(x => x.id !== s.id);
    if (current && current.id === s.id) { current = newSession(); $('#chatTitle').textContent = current.title; renderMessages(); }
    renderSessionList();
    PCB().toast('已删除会话「' + s.title + '」', async () => {
      try {
        await PCB().api('/api/chat/sessions/' + s.id, 'PUT', { title: s.title, createdAt: s.createdAt, messages: s.messages });
        sessions.unshift(s);
        renderSessionList();
        PCB().toast('已恢复');
      } catch (e) { PCB().toast('恢复失败：' + e.message); }
    });
  }

  /* ================= 渲染 ================= */
  function renderSessionList() {
    const box = $('#chatSessionList');
    const list = sessions.slice().sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));
    if (!list.length) { box.innerHTML = '<div class="cs-empty">还没有历史会话</div>'; return; }
    box.innerHTML = list.map(s =>
      '<div class="cs-item ' + (current && s.id === current.id ? 'active' : '') + '" data-sid="' + s.id + '">' +
      '<span class="cs-item-title">' + esc(s.title) + '</span>' +
      '<span class="cs-item-date">' + esc((s.updatedAt || '').slice(5, 10)) + '</span>' +
      '<button class="cs-item-del" data-rename="' + s.id + '" title="重命名">✎</button>' +
      '<button class="cs-item-del" data-delsid="' + s.id + '" title="删除">🗑</button></div>').join('');
    box.querySelectorAll('.cs-item').forEach(el => {
      el.addEventListener('click', () => {
        const s = sessions.find(x => x.id === el.dataset.sid);
        if (s) switchSession(s);
      });
    });
    box.querySelectorAll('[data-delsid]').forEach(b => b.addEventListener('click', ev => {
      const s = sessions.find(x => x.id === b.dataset.delsid);
      if (s) deleteSession(s, ev);
    }));
    box.querySelectorAll('[data-rename]').forEach(b => b.addEventListener('click', ev => {
      ev.stopPropagation();
      const s = sessions.find(x => x.id === b.dataset.rename);
      if (!s) return;
      const item = b.closest('.cs-item');
      item.classList.add('cs-item-renaming');
      item.innerHTML = '<input maxlength="80" value="' + esc(s.title) + '">';
      const inp = item.querySelector('input');
      inp.focus(); inp.select();
      const commit = async () => {
        const t = inp.value.trim();
        if (t) {
          s.title = t;
          if (current && current.id === s.id) { current.title = t; $('#chatTitle').textContent = t; }
          try {
            await PCB().api('/api/chat/sessions/' + s.id, 'PUT', { title: s.title, createdAt: s.createdAt, messages: s.messages });
          } catch (_) {}
        }
        renderSessionList();
      };
      inp.addEventListener('keydown', e2 => {
        if (e2.key === 'Enter') commit();
        if (e2.key === 'Escape') { e2.stopPropagation(); renderSessionList(); }
      });
      inp.addEventListener('blur', commit);
    }));
  }
  function hideSessionList() { $('#chatSessionList').classList.add('hidden'); }

  const ASSISTANT_ICON = '<svg viewBox="0 0 20 20" width="13" height="13"><path d="M10 2.5l1.7 4.3 4.3 1.7-4.3 1.7L10 14.5l-1.7-4.3L4 8.5l4.3-1.7L10 2.5z" fill="currentColor"/></svg>';

  function messageNode(msg) {
    const el = document.createElement('div');
    el.className = 'chat-msg ' + msg.role;
    el.dataset.mid = msg.id;
    if (msg.role === 'user') {
      el.innerHTML = '<div class="cm-bubble">' + esc(msg.text) + '</div>';
    } else {
      el.innerHTML =
        '<div class="cm-meta">' + ASSISTANT_ICON + '计划助手</div>' +
        (msg.thinking ? thinkingHTML(msg) : '') +
        '<div class="cm-bubble-md"></div>' +
        '<div class="cm-tail"></div>';
      updateAssistantNode(el, msg);
    }
    return el;
  }
  function thinkingHTML(msg) {
    const streaming = msg.status === 'streaming';
    return '<details class="cm-thinking"' + (streaming ? ' open' : '') + '><summary>' +
      (streaming ? '<span class="th-spin"></span>' : '<span class="th-arrow">▶</span>') +
      '深度思考' + (streaming ? '中…' : '过程') + '</summary>' +
      '<div class="th-body">' + esc(msg.thinking) + '</div></details>';
  }
  function updateAssistantNode(el, msg) {
    const bubble = el.querySelector('.cm-bubble-md');
    const streaming = msg.status === 'streaming';
    let html = assistantBodyHTML(msg);
    if (streaming && !msg.text) html = '<span style="color:var(--ink-3)">正在思考…</span>';
    if (streaming) html += '<span class="cm-cursor"></span>';
    bubble.innerHTML = html;
    const th = el.querySelector('.cm-thinking');
    if (msg.thinking) {
      if (th) {
        th.querySelector('.th-body').textContent = msg.thinking;
        if (!streaming) {
          th.removeAttribute('open');
          th.querySelector('summary').innerHTML = '<span class="th-arrow">▶</span>深度思考过程';
        }
      } else {
        bubble.insertAdjacentHTML('beforebegin', thinkingHTML(msg));
      }
    }
    const tail = el.querySelector('.cm-tail');
    let tailHTML = '';
    if (msg.status === 'stopped') tailHTML += '<div class="cm-note">已停止生成</div>';
    if (msg.status === 'error') {
      tailHTML += '<div class="cm-error"><span>' + esc(msg.error || '请求失败') + '</span>' +
        '<button type="button" data-retry>重试</button></div>';
    }
    if (msg.status === 'done' || msg.status === 'stopped') {
      tailHTML += '<div class="cm-actions">' +
        '<button class="cm-act" data-copy>复制</button>' +
        '<button class="cm-act" data-regen>重新生成</button></div>';
    }
    tail.innerHTML = tailHTML;
  }

  function renderMessages() {
    const box = $('#chatMessages');
    box.innerHTML = '';
    if (!settings.key) {
      box.innerHTML = '<div class="chat-setup-card">' +
        '<svg viewBox="0 0 48 48" width="44" height="44" style="color:var(--pine)"><path d="M24 6l4.2 10.8L39 21l-10.8 4.2L24 36l-4.2-10.8L9 21l10.8-4.2L24 6z" fill="currentColor"/></svg>' +
        '<h4>先配置 API 连接</h4><p>支持 DeepSeek 官方 API，或任意 OpenAI/Anthropic 兼容服务与网关。<br>Key 只保存在本浏览器，不会上传到本应用服务器。</p>' +
        '<button class="primary-btn" id="chatSetupBtn" type="button">配置 API 连接</button></div>';
      $('#chatSetupBtn').addEventListener('click', openSettings);
      return;
    }
    if (!current || !current.messages.length) {
      box.innerHTML = '<div class="chat-welcome">' +
        '<div class="cw-icon"><svg viewBox="0 0 48 48" width="46" height="46"><path d="M24 6l4.2 10.8L39 21l-10.8 4.2L24 36l-4.2-10.8L9 21l10.8-4.2L24 6z" fill="currentColor"/><path d="M37 32l2 4.6 4.6 2-4.6 2-2 4.6-2-4.6-4.6-2 4.6-2 2-4.6z" fill="currentColor" opacity=".6"/></svg></div>' +
        '<h4>我是你的计划助手</h4><p>我了解你左侧的全部计划与进度。<br>可以帮你安排今天、制定新计划、复盘调整。</p>' +
        '<div class="chat-suggestions">' +
        '<button class="chat-suggestion" type="button">📋 我今天应该做什么？按优先级排一下</button>' +
        '<button class="chat-suggestion" type="button">🏃 帮我制定一个 30 天的晨跑计划，循序渐进</button>' +
        '<button class="chat-suggestion" type="button">📊 复盘我这一周的完成情况，给点调整建议</button>' +
        '</div></div>';
      box.querySelectorAll('.chat-suggestion').forEach(b =>
        b.addEventListener('click', () => { $('#chatInput').value = b.textContent.replace(/^[^\s]+\s/, ''); sendMessage(); }));
      return;
    }
    current.messages.forEach(msg => box.appendChild(messageNode(msg)));
    scrollBottom(true);
  }
  function scrollBottom(force) {
    const box = $('#chatMessages');
    if (force || stickBottom) box.scrollTop = box.scrollHeight;
  }

  /* ================= 生成流程 ================= */
  function setGenerating(on) {
    generating = on;
    $('#chatStopBtn').classList.toggle('hidden', !on);
    $('#chatSendBtn').classList.toggle('hidden', on);
    $('#chatSendBtn').disabled = on;
    $('#chatStatus').classList.toggle('hidden', !on);
    if (on) $('#chatStatus').innerHTML = '<span class="th-spin"></span>正在生成回复…可随时停止';
  }
  function historyForAPI() {
    const msgs = [];
    current.messages.forEach(m => {
      if (m.status === 'streaming') return;
      if (m.role === 'user') msgs.push(m);
      else if (m.text && (m.status === 'done' || m.status === 'stopped')) msgs.push(m);
    });
    return msgs;
  }
  function buildRequest(cfg) {
    const hist = historyForAPI();
    if (cfg.protocol === 'anthropic') {
      return {
        model: cfg.model || DEFAULTS.model,
        system: systemPrompt(),
        messages: hist.map(m => m.role === 'user'
          ? { role: 'user', content: m.text }
          : { role: 'assistant', content: [{ type: 'text', text: m.text }] }),
        thinking: { type: cfg.thinking ? 'enabled' : 'disabled' },
        tools: [],
        title: { enabled: true },
      };
    }
    const messages = [{ role: 'system', content: systemPrompt() }];
    hist.forEach(m => messages.push({ role: m.role, content: m.text }));
    const body = { model: cfg.model || DEFAULTS.model, messages, stream: true };
    if (cfg.thinking) body.thinking = { type: 'enabled' };
    return body;
  }
  function stopGeneration() { if (abortCtrl) abortCtrl.abort(); }

  async function generate() {
    const cfg = Object.assign({}, settings);
    if (!cfg.model) { openSettings(); PCB().toast('请先在设置中填写模型 ID'); return; }
    const msg = { id: uid('m'), role: 'assistant', text: '', thinking: '', status: 'streaming', error: '', createdAt: nowISO() };
    current.messages.push(msg);
    const box = $('#chatMessages');
    const node = messageNode(msg);
    box.appendChild(node);
    scrollBottom(true);
    setGenerating(true);
    abortCtrl = new AbortController();
    let raf = 0;
    const scheduleRender = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        updateAssistantNode(node, msg);
        scrollBottom(false);
      });
    };
    try {
      await streamChat(cfg, buildRequest(cfg), {
        signal: abortCtrl.signal,
        onText: t => { msg.text += t; scheduleRender(); },
        onThinking: t => { msg.thinking += t; scheduleRender(); },
        onTitle: title => {
          if (current.title === '新对话' || !current.title) {
            current.title = String(title).slice(0, 40);
            $('#chatTitle').textContent = current.title;
          }
        },
      });
      msg.status = 'done';
    } catch (e) {
      if (abortCtrl.signal.aborted) {
        msg.status = 'stopped';
      } else {
        msg.status = 'error';
        msg.error = friendlyError(e, cfg);
      }
    }
    if (raf) cancelAnimationFrame(raf);
    setGenerating(false);
    abortCtrl = null;
    updateAssistantNode(node, msg);
    scrollBottom(false);
    saveSoon();
  }

  async function sendMessage() {
    const input = $('#chatInput');
    const text = input.value.trim();
    if (!text || generating) return;
    if (!settings.key) { openSettings(); return; }
    if (!current) current = newSession();
    if (!current.messages.length && current.title === '新对话') {
      current.title = text.slice(0, 24);
      $('#chatTitle').textContent = current.title;
    }
    input.value = '';
    input.style.height = 'auto';
    const msg = { id: uid('m'), role: 'user', text, status: 'done', createdAt: nowISO() };
    current.messages.push(msg);
    if (current.messages.length === 1) renderMessages();
    else $('#chatMessages').appendChild(messageNode(msg));
    scrollBottom(true);
    saveSoon();
    await generate();
  }

  function regenerate() {
    if (generating || !current) return;
    let i = current.messages.length - 1;
    while (i >= 0 && current.messages[i].role !== 'assistant') i--;
    if (i < 0) return;
    current.messages = current.messages.slice(0, i);
    renderMessages();
    generate();
  }

  /* ================= 面板 / 设置 ================= */
  async function openPanel() {
    $('#chatPanel').classList.add('open');
    $('#chatToggleBtn').classList.add('active');
    if (window.innerWidth <= 860) $('#chatScrim').classList.remove('hidden');
    await loadSessions();
    if (!current) current = sessions[0] || newSession();
    $('#chatTitle').textContent = current.title;
    renderMessages();
    setTimeout(() => $('#chatInput').focus(), 300);
  }
  function closePanel() {
    if (generating) stopGeneration();
    flushSave();
    $('#chatPanel').classList.remove('open');
    $('#chatToggleBtn').classList.remove('active');
    $('#chatScrim').classList.add('hidden');
    hideSessionList();
  }
  function formCfg() {
    return {
      key: $('#csKey').value.trim(),
      origin: $('#csOrigin').value.trim() || DEFAULTS.origin,
      model: $('#csModel').value.trim(),
      protocol: $('#csProto').value,
      transport: $('#csTransport').value,
      thinking: $('#csThinking').checked,
    };
  }
  function openSettings() {
    $('#csProto').value = settings.protocol || DEFAULTS.protocol;
    $('#csOrigin').value = settings.origin;
    $('#csKey').value = settings.key;
    $('#csModel').value = settings.model;
    $('#csTransport').value = settings.transport || DEFAULTS.transport;
    $('#csThinking').checked = !!settings.thinking;
    $('#csKeyErr').textContent = '';
    $('#csModelList').innerHTML = '';
    $('#chatSettingsModal').classList.remove('hidden');
    setTimeout(() => $('#csKey').focus(), 60);
  }
  async function doVerify() {
    const cfg = formCfg();
    if (!cfg.key) { $('#csKeyErr').textContent = '请先填写 API Key'; return; }
    const btn = $('#csVerify');
    btn.disabled = true; btn.textContent = '验证中…';
    try {
      await verifyKey(cfg);
      $('#csKeyErr').textContent = '';
      PCB().toast('连接验证通过 ✓');
    } catch (e) {
      $('#csKeyErr').textContent = friendlyError(e, cfg);
    }
    btn.disabled = false; btn.textContent = '验证';
  }
  async function doFetchModels() {
    const cfg = formCfg();
    if (!cfg.key) { $('#csKeyErr').textContent = '请先填写 API Key'; return; }
    const btn = $('#csFetchModels');
    btn.disabled = true; btn.textContent = '拉取中…';
    try {
      const list = await fetchModels(cfg);
      $('#csModelList').innerHTML = list.map(id => '<option value="' + esc(id) + '"></option>').join('');
      if (!$('#csModel').value || !list.includes($('#csModel').value)) {
        $('#csModel').value = list.includes(cfg.model) ? cfg.model : list[0];
      }
      PCB().toast('获取到 ' + list.length + ' 个可用模型');
    } catch (e) {
      PCB().toast('拉取失败：' + friendlyError(e, formCfg()));
    }
    btn.disabled = false; btn.textContent = '拉取模型列表';
  }

  /* ================= 事件绑定 ================= */
  function bind() {
    $('#chatToggleBtn').addEventListener('click', () => {
      if ($('#chatPanel').classList.contains('open')) closePanel();
      else openPanel();
    });
    $('#chatCloseBtn').addEventListener('click', closePanel);
    $('#chatScrim').addEventListener('click', closePanel);
    $('#chatNewBtn').addEventListener('click', () => {
      if (generating) stopGeneration();
      flushSave();
      current = newSession();
      $('#chatTitle').textContent = current.title;
      renderMessages();
      hideSessionList();
      $('#chatInput').focus();
    });
    $('#chatSessionsBtn').addEventListener('click', () => {
      const box = $('#chatSessionList');
      if (box.classList.contains('hidden')) { renderSessionList(); box.classList.remove('hidden'); }
      else hideSessionList();
    });
    document.addEventListener('mousedown', e => {
      const box = $('#chatSessionList');
      if (!box.classList.contains('hidden') && !box.contains(e.target) && !e.target.closest('#chatSessionsBtn')) hideSessionList();
    });

    $('#chatSettingsBtn').addEventListener('click', openSettings);
    $('#csKeyShow').addEventListener('click', () => {
      const inp = $('#csKey');
      const show = inp.type === 'password';
      inp.type = show ? 'text' : 'password';
      $('#csKeyShow').textContent = show ? '隐藏' : '显示';
    });
    $('#csVerify').addEventListener('click', doVerify);
    $('#csFetchModels').addEventListener('click', doFetchModels);
    $('#csSave').addEventListener('click', () => {
      settings = Object.assign({}, DEFAULTS, formCfg());
      persistSettings();
      $('#chatSettingsModal').classList.add('hidden');
      renderMessages();
      PCB().toast(settings.key ? 'AI 助手设置已保存' : '已保存（未配置 Key，聊天暂不可用）');
    });

    const input = $('#chatInput');
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 140) + 'px';
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(); }
    });
    $('#chatSendBtn').addEventListener('click', sendMessage);
    $('#chatStopBtn').addEventListener('click', stopGeneration);

    $('#chatMessages').addEventListener('scroll', () => {
      const box = $('#chatMessages');
      stickBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    });
    $('#chatMessages').addEventListener('click', e => {
      const create = e.target.closest('[data-create-plan]');
      if (create) {
        const [mid, idx] = create.dataset.createPlan.split('|');
        create.disabled = true;
        createProposal(mid, +idx);
        return;
      }
      const copyCode = e.target.closest('.cm-code-copy');
      if (copyCode) {
        const code = copyCode.closest('.cm-code').querySelector('code').textContent;
        navigator.clipboard.writeText(code).then(() => {
          copyCode.textContent = '已复制 ✓';
          setTimeout(() => { copyCode.textContent = '复制'; }, 1500);
        }).catch(() => PCB().toast('复制失败'));
        return;
      }
      const msgEl = e.target.closest('.chat-msg');
      if (!msgEl || !current) return;
      const msg = current.messages.find(x => x.id === msgEl.dataset.mid);
      if (!msg) return;
      if (e.target.closest('[data-copy]')) {
        navigator.clipboard.writeText(msg.text).then(() => PCB().toast('已复制回复')).catch(() => PCB().toast('复制失败'));
      } else if (e.target.closest('[data-regen]') || e.target.closest('[data-retry]')) {
        regenerate();
      }
    });

    // Esc 优先关闭聊天面板（捕获阶段，避免与主应用 Esc 冲突）
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      if (!$('#chatSettingsModal').classList.contains('hidden')) return; // 交给主应用关弹窗
      if ($('#chatPanel').classList.contains('open')) {
        e.stopPropagation();
        closePanel();
      }
    }, true);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();
