const $ = (id) => document.getElementById(id);

function el(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

function table(columns, rows) {
  if (!rows.length) return el("p", "暂无记录。", "empty");
  const host = el("table", "", "ledger");
  const head = host.createTHead().insertRow();
  for (const column of columns) {
    const th = el("th", column.label, column.numeric ? "num" : "");
    th.scope = "col";
    head.append(th);
  }
  const body = host.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    for (const column of columns) {
      const value = column.read(row);
      const td = tr.insertCell();
      if (column.numeric) td.className = "num";
      if (value && typeof value === "object" && value.level) {
        td.append(el("i", "", `lamp ${value.level}`), value.text);
      } else {
        td.textContent = value ?? "—";
        td.title = String(value ?? "");
      }
    }
  }
  return host;
}

const stateStyle = (state) => ({
  ONLINE: {text: "在线", level: "ok"},
  FROZEN: {text: "已封冻", level: "warn"},
  PURGED: {text: "已清理", level: "bad"},
  RESTORED: {text: "已恢复", level: "ok"},
}[state] ?? {text: state, level: "warn"});

async function call(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"}, ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload.error ?? {code: "HTTP_ERROR", message: response.statusText};
    throw Object.assign(new Error(error.message), {payload: error, status: response.status});
  }
  return payload;
}

function flash(host, error) {
  const detail = error.payload?.detail ? ` · ${JSON.stringify(error.payload.detail)}` : "";
  host.replaceChildren(el("p", `${error.payload?.code ?? "ERROR"} · ${error.message}${detail}`, "error-banner"));
}

async function loadLedger() {
  const host = $("ledger-output");
  try {
    const {batches} = await call("/api/archive/ledger");
    host.replaceChildren(table([
      {label: "批次（前 12 位）", read: (r) => r.run_id.slice(0, 12)},
      {label: "状态", read: (r) => stateStyle(r.state)},
      {label: "数据源", read: (r) => r.sample},
      {label: "车次", read: (r) => r.train_count, numeric: true},
      {label: "待复秤", read: (r) => r.review_count, numeric: true},
      {label: "在线字节", read: (r) => r.online_bytes, numeric: true},
      {label: "已回收", read: (r) => r.reclaim_bytes, numeric: true},
      {label: "恢复次数", read: (r) => r.restore_count, numeric: true},
      {label: "Merkle 根（前 12 位）", read: (r) => r.merkle_root.slice(0, 12)},
    ], batches));
    host.querySelectorAll("tbody tr").forEach((tr, index) => {
      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => { $("run-id").value = batches[index].run_id; });
    });
  } catch (error) { flash(host, error); }
}

async function plan() {
  const host = $("plan-output");
  const need = Number($("need-bytes").value);
  try {
    const result = await call(`/api/archive/plan?need_bytes=${need}`);
    $("plan-verdict").textContent =
      `${result.satisfiable ? "可满足" : "容量不足"} · 计划回收 ${result.planned_reclaim_bytes} 字节` +
      ` · 可转 ${result.planned.length} 批 · 阻塞 ${result.blocked.length} 批`;
    const wrap = el("div", "", "split");
    wrap.append(
      el("h3", `建议先转冷（${result.planned.length}）`),
      table([
        {label: "批次", read: (r) => r.run_id.slice(0, 12)},
        {label: "数据源", read: (r) => r.sample},
        {label: "车次", read: (r) => r.train_count, numeric: true},
        {label: "待复秤", read: (r) => r.review_count, numeric: true},
        {label: "可回收字节", read: (r) => r.reclaim_bytes, numeric: true},
      ], result.planned),
      el("h3", `阻塞批次（${result.blocked.length}）`),
      table([
        {label: "批次", read: (r) => r.run_id.slice(0, 12)},
        {label: "阻塞原因", read: (r) => r.blocking_codes.join(" / ")},
        {label: "保留单数", read: (r) => r.holds.length, numeric: true},
        {label: "待复秤", read: (r) => r.review_count, numeric: true},
      ], result.blocked),
    );
    host.replaceChildren(wrap);
  } catch (error) { flash(host, error); }
}

const ACTIONS = {
  eligibility: (id) => call(`/api/archive/eligibility/${id}`),
  freeze: (id) => call("/api/archive/freeze", {method: "POST", body: JSON.stringify({run_id: id})}),
  seal: (id) => call(`/api/archive/seal/${id}`),
  purge: (id) => call("/api/archive/purge", {method: "POST", body: JSON.stringify({run_id: id})}),
  restore: (id) => call("/api/archive/restore", {method: "POST", body: JSON.stringify({run_id: id})}),
  "dry-restore": (id) => call(
    `/api/archive/restore?dry_run=true`, {method: "POST", body: JSON.stringify({run_id: id})}),
  readback: (id) => {
    const pass = $("pass-id").value.trim();
    return call(`/api/archive/readback/${id}${pass ? `?pass_id=${encodeURIComponent(pass)}` : ""}`);
  },
  hold: (id) => call("/api/archive/holds", {
    method: "POST",
    body: JSON.stringify({
      run_id: id, subject: $("hold-subject").value.trim() || "未命名抽查",
      reason: $("hold-reason").value.trim() || "审计回读",
    }),
  }),
};

async function runAction(action) {
  const host = $("action-output");
  const id = $("run-id").value.trim();
  if (!id) { host.replaceChildren(el("p", "请先选择或输入 run_id。", "error-banner")); return; }
  try {
    const payload = await ACTIONS[action](id);
    const pre = el("pre", JSON.stringify(payload, null, 2), "json-view");
    host.replaceChildren(pre);
    await loadLedger();
  } catch (error) { flash(host, error); }
}

async function loadHolds() {
  const host = $("holds-output");
  try {
    const {holds} = await call("/api/archive/holds");
    host.replaceChildren(table([
      {label: "保留单", read: (r) => r.hold_id},
      {label: "批次", read: (r) => r.run_id.slice(0, 12)},
      {label: "主题", read: (r) => r.subject},
      {label: "原因", read: (r) => r.reason},
      {label: "生效时间", read: (r) => r.created_at},
    ], holds));
  } catch (error) { flash(host, error); }
}

async function loadEvents() {
  const host = $("events-output");
  try {
    const {events} = await call("/api/archive/events?limit=250");
    host.replaceChildren(table([
      {label: "序号", read: (r) => r.seq, numeric: true},
      {label: "批次", read: (r) => r.run_id.slice(0, 12)},
      {label: "级别", read: (r) => r.level},
      {label: "事件", read: (r) => r.code},
      {label: "说明", read: (r) => r.message},
      {label: "时间", read: (r) => r.time},
    ], events));
  } catch (error) { flash(host, error); }
}

async function health() {
  try {
    const data = await call("/api/health");
    $("service-lamp").className = "lamp ok";
    $("service-state").textContent = "服务就绪";
    $("rule-version").textContent = data.rules;
  } catch {
    $("service-lamp").className = "lamp bad";
    $("service-state").textContent = "连接失败";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("plan-button").addEventListener("click", plan);
  $("refresh-ledger").addEventListener("click", loadLedger);
  $("refresh-holds").addEventListener("click", loadHolds);
  $("refresh-events").addEventListener("click", loadEvents);
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button.dataset.action));
  });
  health();
  loadLedger();
  loadHolds();
  loadEvents();
});
