// CONVERSATION_ROUTING_V1: rendering is textContent-only, no model HTML/links.
export function renderAgentSources(host, sources = [], doc = document) {
  host.replaceChildren();
  host.open = false; // New answers must not leave a long source panel expanded.
  const valid = Array.isArray(sources) ? sources.filter(s => s && typeof s.source_id === 'string').slice(0, 3) : [];
  host.hidden = !valid.length;
  const summary = doc.createElement('summary');
  summary.textContent = '查看本轮资料依据（' + valid.length + '）';
  host.append(summary);
  valid.forEach((source, index) => {
    const item = doc.createElement('p');
    item.textContent = `[${index + 1}] ${String(source.title || '').slice(0, 150)}\n${source.source_id.slice(0, 180)}`
      + (typeof source.quote === 'string' ? '\n原文：' + source.quote.slice(0, 500) : '');
    host.append(item);
  });
}

// Transport adapter only: existing VRM rendering, text, TTS and motions remain.
const SESSION_KEY = 'anxin.agent.session.v1';
const ATTEMPT_KEY = 'anxin.agent.attempt.v1';
export const isAgentMode = () => typeof window !== 'undefined' && new URL(window.location.href).searchParams.get('agent') === '1';
// AGENT_TIMEOUT_PROFILE_V1: only the Agent route gets the longer wait.
export const agentChatTimeoutMs = () => isAgentMode() ? 100000 : 25000;


export class AgentTransport {
  constructor({fetchImpl = globalThis.fetch.bind(globalThis), storage = null, uuid = () => crypto.randomUUID().replaceAll('-', '')} = {}) {
    this.fetch = fetchImpl;
    this.storage = storage;
    this.uuid = uuid;
    this.session = this.read(SESSION_KEY);
    this.lastAttempt = this.read(ATTEMPT_KEY);
    this.pending = null;
    this.epoch = 0;
    this.onState = () => {};
  }
  read(key) { try { return JSON.parse(this.storage?.getItem(key) || 'null'); } catch { return null; } }
  write(key, value) { try { this.storage?.setItem(key, JSON.stringify(value)); } catch { /* memory-only session */ } }
  headers(session = this.session) {
    return {'Content-Type': 'application/json', Authorization: 'Bearer ' + session.access_token};
  }
  async restore(signal) {
    if (!this.session) return null;
    const epoch = this.epoch;
    const response = await this.fetch(`/api/agent/sessions/${this.session.session_id}`,
      {headers: this.headers(), cache: 'no-store', signal});
    if (response.status === 401) {
      // Never move an unknown confirmation result into a newly created session.
      if (this.lastAttempt && !this.lastAttempt.completed) throw new Error('旧会话已过期；不能自动重放到新会话。');
      this.session = null;
      this.write(SESSION_KEY, null);
      return null;
    }
    if (!response.ok) throw new Error(`Agent session HTTP ${response.status}`);
    const data = await response.json();
    if (epoch !== this.epoch) return null;
    this.pending = data.pending;
    if (this.lastAttempt && data.last_response?.request_id === this.lastAttempt.body.request_id) {
      this.lastAttempt.completed = true;
      this.write(ATTEMPT_KEY, this.lastAttempt);
    }
    this.onState(data);
    return data;
  }
  async ensureSession(signal) {
    if (this.session) {
      await this.restore(signal);
      if (this.session) return;
    }
    const response = await this.fetch('/api/agent/sessions', {method: 'POST', signal, headers: {'Content-Type': 'application/json'}});
    if (!response.ok) throw new Error(`Agent session HTTP ${response.status}`);
    this.session = await response.json();
    this.write(SESSION_KEY, this.session);
  }
  async post(payload, {signal, retry = false, startNewService = false} = {}) {
    this.epoch += 1;
    if (!retry || !this.lastAttempt) {
      await this.ensureSession(signal);
      const text = payload.text.trim();
      const decision = this.pending && (text === '确认模拟预约' ? 'approve' : text === '取消本次操作' ? 'reject' : null);
      const base = {request_id: this.uuid(), avatar_id: payload.avatar_id || null, voice_gender: payload.voice_gender || 'auto'};
      const body = decision
        ? {...base, proposal_id: this.pending.proposal_id, confirmation_token: this.pending.confirmation_token, decision}
        : {...base, text, new_task: startNewService};
      this.lastAttempt = {url: `/api/agent/sessions/${this.session.session_id}/${decision ? 'confirm' : 'chat'}`,
                          body, session: this.session, completed: false};
      this.write(ATTEMPT_KEY, this.lastAttempt);
    }
    const attempt = this.lastAttempt;
    const response = await this.fetch(attempt.url, {method: 'POST', headers: this.headers(attempt.session),
      body: JSON.stringify(attempt.body), signal});
    if (response.ok) {
      const data = await response.clone().json();
      this.pending = data.pending || null;
      this.lastAttempt.completed = true;
      this.write(ATTEMPT_KEY, this.lastAttempt);
      this.onState(data);
    }
    // On timeout/non-2xx retain the exact request ID, endpoint, token and body.
    // No fallback to /api/chat; a timed-out confirmation may have committed.
    return response;
  }
  reset() {
    if (this.pending || this.lastAttempt && !this.lastAttempt.completed) {
      throw new Error('请先确认、取消或重试核实当前任务，再新建会话。');
    }
    this.epoch += 1;
    this.session = this.lastAttempt = this.pending = null;
    this.write(SESSION_KEY, null);
    this.write(ATTEMPT_KEY, null);
  }
}

let client;
function transport() {
  if (!client) {
    let storage = null;
    try { storage = window.sessionStorage; } catch { /* restricted storage */ }
    client = new AgentTransport({storage});
  }
  return client;
}

export async function agentChatTransport(payload, options = {}) {
  if (!isAgentMode()) return fetch('/api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'},
    signal: options.signal, body: JSON.stringify(payload)});
  return transport().post(payload, options);
}

export function agentFailureHint() {
  return isAgentMode() ? '处理结果暂时未知。请点击“重新尝试”核实同一请求，不要重复新建预约。' : '服务连接失败，文字内容未提交。';
}

export function installAgentControls({onRestore = () => {}, onReset = () => {}, onRetryAvailable = () => {}} = {}) {
  if (typeof document === 'undefined') return;
  const host = document.getElementById('help-dialog');
  if (!host || document.getElementById('agent-controls')) return;
  const section = document.createElement('section');
  section.id = 'agent-controls';
  const heading = document.createElement('h3');
  heading.textContent = 'Agent 对话、资料与业务演示';
  const link = document.createElement('a');
  const url = new URL(window.location.href);
  if (isAgentMode()) url.searchParams.delete('agent'); else url.searchParams.set('agent', '1');
  link.href = url.href;
  link.textContent = isAgentMode() ? '切换回原规则模式' : '打开 Agent 模式';
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.textContent = isAgentMode() ? '正在读取 Agent 状态……' : '原规则模式保持不变。Agent 只使用虚构演示数据。';
  section.append(heading, link, status);
  host.append(section);
  if (!isAgentMode()) return;
  const modeBadge = document.createElement('p');
  modeBadge.textContent = '当前为 Agent 模式：请在“帮助与设置”查看执行方式。';
  modeBadge.setAttribute('role', 'status');
  const dock = document.querySelector('.interaction-dock');
  if (dock) dock.append(modeBadge);
  const sourcePanel = document.createElement('details');
  sourcePanel.id = 'agent-source-evidence';
  sourcePanel.hidden = true;
  sourcePanel.style.whiteSpace = 'pre-wrap';
  (dock || section).append(sourcePanel);
  const reset = document.createElement('button');
  reset.type = 'button';
  reset.textContent = '新建 Agent 会话';
  reset.addEventListener('click', () => {
    try { transport().reset(); onReset(); status.textContent = '已结束当前会话，下次输入时创建新会话。'; }
    catch (error) { status.textContent = error.message; }
  });
  section.append(reset);
  transport().onState = data => {
    data = data.last_response || data;
    if (!data.mode) return;
    renderAgentSources(sourcePanel, data.sources || []);
    const modes = {
      pending_confirmation: '等待明确确认：未调用模型', local_control: '本地流程控制：未调用模型',
      llm_chat: '普通聊天：大模型生成回复', chat_fallback: '普通聊天暂不可用：本地提示',
      llm_knowledge: '服务咨询：资料检索＋模型回答', knowledge_extract: '服务咨询：本地原文摘录',
      knowledge_fallback: '服务咨询：生成未完成，可展开查看原文', knowledge_no_evidence: '服务咨询：缺少资料依据',
      capability_boundary: '当前未接入相应外部工具',
      rules_demo: '未调用大模型：本地规则演示', rules_fallback: '本轮未取得有效模型工具结果：已回退本地规则',
      llm_tools: '大模型工具调用', llm_partial: '模型调用未全部完成：显示已有查询结果',
      explicit_selection: '用户明确选择', confirmed_action: '用户确认后的受控执行', safety_boundary: '安全边界响应', recovered_result: '恢复的任务处理结果'};
    // RUNTIME_DIAGNOSTICS_V1_1. Only safe enum/count/timing summaries are shown.
    const reasons = {
      reply_rejected: '回复未通过输出检查', invalid_grounding: '引用或答案未通过校验',
      no_evidence: '没有检索到足够依据', insufficient_evidence: '模型表示资料不足',
      not_configured: '模型配置不可用', external_tool_missing: '没有对应的实时查询或发送工具',
      no_tool_call_before_evidence: '模型本轮未请求工具', database_unavailable: '业务数据库工具失败',
      invalid_arguments: '工具参数未通过校验', department_required: '科室名称或编号不匹配',
      date_out_of_range: '日期超出可查询范围', invalid_date: '日期无效',
      read_timeout: '模型读取超时', connect_timeout: '模型连接超时', connect_error: '模型连接失败',
      write_timeout: '模型发送超时', pool_timeout: '连接池等待超时', timeout: '模型请求超时',
      proxy_error: '代理连接错误', network_error: '网络错误', protocol_error: '网络协议错误',
      http_error: '模型接口返回HTTP错误', incomplete: '模型输出未完整结束',
      response_not_json: '模型响应不是JSON', response_shape: '模型响应结构不兼容',
      invalid_call: '工具调用结构错误', invalid_tool_calls: '工具调用列表错误',
      budget_exceeded: '本轮模型预算耗尽', turn_budget_exceeded: '本轮模型预算耗尽',
      response_limit: '响应大小或耗时超过边界', round_limit: '工具循环达到轮数限制',
      call_limit: '工具调用达到次数限制', unknown_tool: '模型选择了未开放的工具',
      unobserved_slot: '未先查询候选号源', slot_unavailable: '号源已变化',
    };
    const label = modes[data.mode] || data.mode;
    const reason = data.diagnostics?.reason;
    const detail = reason && reason !== 'completed' ? (reasons[reason] || reason) : '';
    modeBadge.textContent = detail ? `${label}（${detail}）` : label;
    const tools = (data.trace || []).map(t => `${t.origin === 'rules' ? '规则/' : t.origin === 'llm' ? '模型/' : ''}${t.tool}:${t.ok ? '成功' : '失败'}${t.error ? '(' + t.error + ')' : ''}`).join(' → ');
    const sources = (data.sources || []).map(s => s.source_id).join('，');
    const routeNames = {chat: '普通聊天', knowledge: '服务咨询', business: '业务办理', capability: '能力边界', boundary: '安全边界'};
    const route = routeNames[data.route] || '业务办理';
    status.textContent = `路径：${route}；${label}；引擎 ${data.engine || '未知'}。${detail ? '\n本轮原因：' + detail : ''}${tools ? '\n工具轨迹：' + tools : ''}${sources ? '\n资料来源：' + sources : ''}${data.diagnostics ? '\n脱敏诊断：' + JSON.stringify(data.diagnostics) : ''}`;
  };
  fetch('/api/agent/status', {cache: 'no-store'}).then(async response => {
    if (!response.ok) throw new Error('Agent状态读取失败，请检查后端及依赖。');
    const data = await response.json();
    status.textContent = `${data.engine}；${data.llm_configured ? '模型配置完整，尚不代表连通性已验证' : '没有模型配置，使用本地规则演示'}。仅使用虚构数据。`;
    modeBadge.textContent = data.llm_configured ? 'Agent：普通聊天 / 服务咨询 / 业务办理已启用' : 'Agent：未配置模型，保留规则与资料摘录';
  }).catch(error => { status.textContent = error.message; modeBadge.textContent = 'Agent 暂不可用，原规则模式可独立使用'; });
  transport().restore().then(data => {
    if (data?.pending || data?.last_response) onRestore(data);
    if (transport().lastAttempt && !transport().lastAttempt.completed) {
      onRetryAvailable(transport().lastAttempt.body.text || '确认模拟预约');
    }
  })
    .catch(() => { status.textContent = '会话恢复未完成。确认操作不要重新新建，请重试核实。'; });
}
