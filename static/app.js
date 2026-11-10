/* 雪茄库存监控前端逻辑（原生 JS，无外部依赖） */
const STATUS_LABEL = { in_stock: "有货", out_of_stock: "缺货", unknown: "未知" };
const CAT_NAMES = { brand: "品牌", line: "型号" };
let productCache = [];
const filterState = { q: "", status: "all", tags: new Set() };

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(url, opts = {}) {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `请求失败 (${r.status})`);
  return data;
}

function toast(msg, isErr = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.className = "toast"), 3200);
}

/* ---------------- 时段问候语 ---------------- */
function setGreeting() {
  const h = new Date().getHours();
  let g;
  if (h >= 5 && h < 11) g = "早上好";
  else if (h >= 11 && h < 14) g = "中午好";
  else if (h >= 14 && h < 18) g = "下午好";
  else if (h >= 18 && h < 22) g = "晚上好";
  else g = "夜深了";
  $("greeting").textContent = g;
}

/* ---------------- 概览 ---------------- */
async function loadOverview() {
  try {
    const o = await api("/api/overview");
    $("st-total").textContent = o.total;
    $("st-enabled").textContent = o.enabled;
    $("st-in").textContent = o.in_stock;
    $("st-out").textContent = o.out_of_stock;
    $("st-unknown").textContent = o.unknown;
    $("next-run").textContent = "下次检查：" + (o.next_run || "-");
  } catch (e) { /* ignore */ }
}

/* ---------------- 线性图标 ---------------- */
const ICONS = {
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>`,
  delete: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>`,
};

function fmtTime(s) {
  if (!s) return "-";
  const m = String(s).match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : s;
}

/* ---------------- 平铺商品行 ---------------- */
function prodRow(p) {
  return `
  <div class="prod-row" data-pid="${p.id}">
    <div class="cell c-prod">
      <div class="prod-text">
        <span class="prod-name" title="${esc(p.name)}">${esc(p.name)}</span>
        <a class="prod-url" href="${esc(p.url)}" target="_blank" title="${esc(p.url)}">${esc(p.url)}</a>
      </div>
    </div>
    <div class="cell c-status">
      <span class="badge ${p.status}">${STATUS_LABEL[p.status] || "未知"}</span>
      <span class="status-detail" title="${esc(p.status_text || "")}">${esc(p.status_text || "")}</span>
    </div>
    <div class="cell c-time">${esc(fmtTime(p.last_checked))}</div>
    <div class="cell c-time">${esc(fmtTime(p.last_notified))}</div>
    <div class="cell c-switch">
      <label class="switch">
        <input type="checkbox" class="sw-enabled" data-id="${p.id}" ${p.enabled ? "checked" : ""}>
        <span class="slider-sw"></span>
      </label>
    </div>
    <div class="cell c-ops">
      <button class="icon-btn" data-action="check" data-id="${p.id}" title="立即检查" aria-label="立即检查">${ICONS.check}</button>
      <button class="icon-btn danger" data-action="delete" data-id="${p.id}" title="删除" aria-label="删除">${ICONS.delete}</button>
    </div>
  </div>`;
}

/* ---------------- 筛选 ---------------- */
function filtered() {
  const q = filterState.q.trim().toLowerCase();
  return productCache.filter((p) => {
    if (q && !`${p.name} ${p.url}`.toLowerCase().includes(q)) return false;
    if (filterState.status !== "all" && p.status !== filterState.status) return false;
    if (filterState.tags.size && !p.tags.some((t) => filterState.tags.has(t))) return false;
    return true;
  });
}

function renderProducts() {
  const list = filtered();
  const root = $("product-list");
  root.innerHTML = list.length
    ? list.map(prodRow).join("")
    : `<div class="empty-hint">${productCache.length ? "没有符合筛选条件的监控项" : "暂无监控项，添加一个雪茄商品网址开始监控"}</div>`;
  const active = filterState.q.trim() || filterState.status !== "all" || filterState.tags.size;
  $("filter-meta").textContent = active ? `筛选结果：${list.length} / ${productCache.length} 项` : "";
  hideHighlight();
}

function buildTagFilter() {
  const counts = {};
  for (const p of productCache)
    for (const t of p.tags) counts[t] = (counts[t] || 0) + 1;
  const tags = [...new Set(productCache.flatMap((p) => p.tag_buckets.brand || []))].sort();
  $("tag-filter").innerHTML = tags.map((t) =>
    `<button class="chip ${filterState.tags.has(t) ? "active" : ""}" data-tag="${esc(t)}">${esc(t)}<span class="chip-n">${counts[t]}</span></button>`).join("");
}

async function loadProducts() {
  productCache = await api("/api/products");
  buildTagFilter();
  renderProducts();
}

/* ---------------- 列表事件 ---------------- */
$("product-list").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const id = btn.dataset.id;
  try {
    if (btn.dataset.action === "delete") {
      if (!confirm("确定删除该监控项及其日志？")) return;
      await api(`/api/products/${id}`, { method: "DELETE" });
      toast("已删除");
      refreshAll();
    } else if (btn.dataset.action === "check") {
      btn.disabled = true;
      const r = await api(`/api/products/${id}/check`, { method: "POST" });
      toast(r.notified ? "检查完成，已发送有货通知邮件" : `检查完成：${STATUS_LABEL[r.status]}`);
      refreshAll();
    }
  } catch (err) { toast(err.message, true); }
});

$("product-list").addEventListener("change", async (e) => {
  if (!e.target.classList.contains("sw-enabled")) return;
  try {
    await api(`/api/products/${e.target.dataset.id}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: e.target.checked }),
    });
    loadOverview();
  } catch (err) { toast(err.message, true); }
});

/* 行 hover：用单一连续背景层定位，避免多单元格拼接出现缝隙 */
let hoveredRow = null;
function moveHighlight(row) {
  const hl = $("hover-highlight");
  const gridRect = $("monitor-grid").getBoundingClientRect();
  const cellRect = row.querySelector(".cell").getBoundingClientRect();
  hl.style.top = (cellRect.top - gridRect.top) + "px";
  hl.style.height = cellRect.height + "px";
  hl.classList.add("on");
}
function hideHighlight() {
  hoveredRow = null;
  $("hover-highlight").classList.remove("on");
}
$("product-list").addEventListener("mouseover", (e) => {
  const row = e.target.closest(".prod-row");
  if (!row) return;
  if (row !== hoveredRow) { hoveredRow = row; moveHighlight(row); }
});
$("product-list").addEventListener("mouseout", (e) => {
  const row = e.target.closest(".prod-row");
  if (row && !row.contains(e.relatedTarget)) hideHighlight();
});
window.addEventListener("resize", () => { if (hoveredRow) moveHighlight(hoveredRow); });
window.addEventListener("scroll", () => { if (hoveredRow) moveHighlight(hoveredRow); }, true);

/* ---------------- 筛选事件 ---------------- */
$("filter-search").addEventListener("input", (e) => {
  filterState.q = e.target.value;
  renderProducts();
});

$("filter-search-btn").addEventListener("click", () => $("filter-search").focus());

/* 筛选面板展开/收起 */
$("btn-filter").addEventListener("click", () => {
  const panel = $("filter-panel");
  const open = panel.classList.toggle("open");
  $("btn-filter").classList.toggle("active", open);
});

/* 铃铛：展开邮箱设置并滚动过去 */
$("btn-email").addEventListener("click", () => {
  const card = $("card-settings");
  card.classList.remove("collapsed");
  card.scrollIntoView({ behavior: "smooth", block: "start" });
});

$("stock-only").addEventListener("change", (e) => {
  filterState.status = e.target.checked ? "in_stock" : "all";
  renderProducts();
});

$("tag-filter").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  const tag = chip.dataset.tag;
  if (filterState.tags.has(tag)) filterState.tags.delete(tag);
  else filterState.tags.add(tag);
  chip.classList.toggle("active");
  renderProducts();
});

/* ---------------- 卡片折叠（邮箱/日志） ---------------- */
document.addEventListener("click", (e) => {
  const head = e.target.closest(".collapsible-head");
  if (!head || e.target.closest("button")) return;
  head.parentElement.classList.toggle("collapsed");
});

/* ---------------- 英文地址弹窗 ---------------- */
const ADDR_FIELDS = ["line1", "line2", "country", "state", "city", "zip"];

async function openAddressModal() {
  const addr = await api("/api/address");
  for (const f of ADDR_FIELDS) $("addr-" + f).value = addr[f] || "";
  const m = $("address-modal");
  m.classList.add("show");
  m.setAttribute("aria-hidden", "false");
}

function closeAddressModal() {
  const m = $("address-modal");
  m.classList.remove("show");
  m.setAttribute("aria-hidden", "true");
}

$("btn-address").addEventListener("click", openAddressModal);
$("addr-close").addEventListener("click", closeAddressModal);
$("addr-cancel").addEventListener("click", closeAddressModal);
$("address-modal").addEventListener("click", (e) => {
  if (e.target.id === "address-modal") closeAddressModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeAddressModal();
});

$("addr-save").addEventListener("click", async () => {
  const body = {};
  for (const f of ADDR_FIELDS) body[f] = $("addr-" + f).value;
  try {
    await api("/api/address", { method: "POST", body: JSON.stringify(body) });
    toast("英文地址已保存");
    closeAddressModal();
  } catch (err) {
    toast(err.message, true);
  }
});

/* ---------------- 添加 ---------------- */
$("btn-add").addEventListener("click", async () => {
  const url = $("add-url").value.trim();
  const msg = $("add-msg");
  if (!url) { msg.textContent = "请输入网址"; msg.className = "hint error"; return; }
  $("btn-add").disabled = true;
  msg.textContent = "正在抓取并检查，请稍候..."; msg.className = "hint";
  try {
    await api("/api/products", { method: "POST", body: JSON.stringify({ url }) });
    $("add-url").value = "";
    msg.textContent = "添加成功，已完成首次检查"; msg.className = "hint ok";
    refreshAll();
  } catch (err) { msg.textContent = err.message; msg.className = "hint error"; }
  $("btn-add").disabled = false;
});

/* ---------------- 设置 ---------------- */
async function loadSettings() {
  const { settings, presets } = await api("/api/settings");
  const presetSel = $("set-preset");
  presetSel.innerHTML = Object.entries(presets)
    .map(([k, v]) => `<option value="${k}" ${k === settings.smtp_preset ? "selected" : ""}>${v.label}</option>`)
    .join("");
  $("set-host").value = settings.smtp_host;
  $("set-port").value = settings.smtp_port;
  $("set-security").value = settings.smtp_security;
  $("set-user").value = settings.smtp_user;
  $("set-pass").value = settings.smtp_pass;
  $("set-to").value = settings.mail_to;
  $("set-from-name").value = settings.mail_from_name;
  $("set-interval").value = settings.check_interval;
  $("set-notify-mode").value = settings.notify_mode;
}

$("set-preset").addEventListener("change", async () => {
  const key = $("set-preset").value;
  const { presets } = await api("/api/settings");
  const p = presets[key];
  if (!p || key === "custom") return;
  $("set-host").value = p.host;
  $("set-port").value = p.port;
  $("set-security").value = p.security;
});

function collectSettings() {
  return {
    smtp_preset: $("set-preset").value,
    smtp_host: $("set-host").value.trim(),
    smtp_port: $("set-port").value.trim(),
    smtp_security: $("set-security").value,
    smtp_user: $("set-user").value.trim(),
    smtp_pass: $("set-pass").value,
    mail_to: $("set-to").value.trim(),
    mail_from_name: $("set-from-name").value.trim(),
    check_interval: $("set-interval").value,
    notify_mode: $("set-notify-mode").value,
  };
}

$("btn-save-settings").addEventListener("click", async () => {
  const msg = $("settings-msg");
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(collectSettings()) });
    msg.textContent = "设置已保存，调度已更新"; msg.className = "hint ok";
    loadOverview();
  } catch (err) { msg.textContent = err.message; msg.className = "hint error"; }
});

$("btn-test-email").addEventListener("click", async () => {
  const msg = $("settings-msg");
  msg.textContent = "正在发送测试邮件..."; msg.className = "hint";
  try {
    await api("/api/test-email", { method: "POST" });
    msg.textContent = "测试邮件已发送，请查收"; msg.className = "hint ok";
  } catch (err) { msg.textContent = err.message; msg.className = "hint error"; }
});

/* ---------------- 日志 ---------------- */
async function loadLogs() {
  const logs = await api("/api/logs?limit=50");
  const nameMap = Object.fromEntries(productCache.map((p) => [p.id, p.name]));
  const tbody = $("log-rows");
  if (!logs.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="hint" style="text-align:center;padding:20px">暂无日志</td></tr>`;
    return;
  }
  tbody.innerHTML = logs.map((l) => `
    <tr>
      <td style="white-space:nowrap">${esc(l.checked_at)}</td>
      <td>${esc(nameMap[l.product_id] || `#${l.product_id}`)}</td>
      <td><span class="badge ${l.status}">${STATUS_LABEL[l.status] || "未知"}</span></td>
      <td>${esc(l.http_code ?? "-")}</td>
      <td class="hint">${esc(l.detail || "")}</td>
    </tr>`).join("");
}

$("btn-refresh-logs").addEventListener("click", () => loadLogs());

$("btn-check-all").addEventListener("click", async () => {
  $("btn-check-all").disabled = true;
  try {
    await api("/api/check-all", { method: "POST" });
    toast("全部检查完成");
    refreshAll();
  } catch (err) { toast(err.message, true); }
  $("btn-check-all").disabled = false;
});

/* ---------------- 版本与更新 ---------------- */
async function loadVersion() {
  try {
    const data = await api("/api/version");
    $("app-version").textContent = "v" + data.version;
  } catch (err) {
    $("app-version").textContent = "";
  }
}

$("btn-check-update").addEventListener("click", async () => {
  const btn = $("btn-check-update");
  const oldText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "检查中...";
  try {
    const res = await api("/api/check-update", { method: "POST" });
    if (!res.update) {
      toast(`当前已是最新版本 v${res.current}`);
    } else {
      const info = res.update;
      const notes = info.notes ? `\n\n更新说明：\n${info.notes}` : "";
      const go = confirm(
        `发现新版本 v${info.latest}（当前 v${info.current}）。\n` +
        `点击“确定”立即下载并自动重启更新。${notes}`);
      if (go) {
        btn.textContent = "准备更新...";
        try {
          await api("/api/apply-update", { method: "POST" });
        } catch (err) {
          toast(err.message, true);
        }
      }
    }
  } catch (err) {
    toast(err.message, true);
  }
  btn.disabled = false;
  btn.textContent = oldText;
});

/* ---------------- 自动刷新 ---------------- */
async function refreshAll() {
  await loadOverview();
  await loadProducts();
  await loadLogs();
}

async function init() {
  setGreeting();
  await loadVersion();
  await loadSettings();
  await refreshAll();
  setInterval(loadOverview, 15000);
  setInterval(refreshAll, 30000);
}
init();
