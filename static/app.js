/* 雪茄库存监控前端逻辑（原生 JS，无外部依赖） */
const STATUS_LABEL = { in_stock: "有货", out_of_stock: "缺货", unknown: "未知" };
const CAT_NAMES = { brand: "品牌", line: "型号" };
let productCache = [];
let brandMap = {}; // 规范英文名 -> {en, short(中文简称), full(中文全称)}
const filterState = { q: "", status: "all", tags: new Set() };

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(url, opts = {}) {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(data.error || `请求失败 (${r.status})`);
    e.data = data;
    throw e;
  }
  return data;
}

function toast(msg, isErr = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.className = "toast"), 3200);
}

/* ---------------- 统一确认 / 提示弹窗 ----------------
   浏览器原生 alert/confirm 在 WebView 里标题会显示「127.0.0.1:5050 显示」，
   而且是系统深色方角、靠上显示，无法改样式。这里与地址 / 计算器弹窗共用
   .modal-mask（居中 + 半透明遮罩 + 背景模糊 + 圆角），标题固定显示软件名。
   DOM 由 JS 注入：模板改动需重启 Flask 才生效，静态资源强刷即可。 */
const APP_NAME = document.title || "雪茄库存监控";
const APP_DIALOG_HTML = `
  <div class="modal-mask" id="app-dialog" aria-hidden="true">
    <div class="modal app-dialog" role="dialog" aria-modal="true" aria-labelledby="app-dialog-name" tabindex="-1">
      <div class="modal-head">
        <h3 id="app-dialog-name"><span class="app-dialog-mark"></span><span id="app-dialog-app"></span></h3>
        <button class="modal-close" id="app-dialog-x" aria-label="关闭">×</button>
      </div>
      <div class="modal-body app-dialog-body">
        <p class="app-dialog-title" id="app-dialog-subject"></p>
        <p class="app-dialog-text" id="app-dialog-text"></p>
      </div>
      <div class="modal-foot">
        <button class="btn ghost" id="app-dialog-cancel">取消</button>
        <button class="btn primary" id="app-dialog-ok">确定</button>
      </div>
    </div>
  </div>`;

if (!$("app-dialog")) document.body.insertAdjacentHTML("beforeend", APP_DIALOG_HTML);
$("app-dialog-app").textContent = APP_NAME;

let appDialogResolve = null;
let appDialogPrevFocus = null;

function closeAppDialog(result) {
  const mask = $("app-dialog");
  if (!mask.classList.contains("show")) return;
  mask.classList.remove("show");
  mask.setAttribute("aria-hidden", "true");
  document.removeEventListener("keydown", onAppDialogKey, true);
  const resolve = appDialogResolve;
  appDialogResolve = null;
  if (appDialogPrevFocus && document.contains(appDialogPrevFocus)) appDialogPrevFocus.focus();
  appDialogPrevFocus = null;
  if (resolve) resolve(result);
}

function onAppDialogKey(e) {
  if (e.key === "Escape") {
    e.preventDefault(); e.stopPropagation(); closeAppDialog(false);
  } else if (e.key === "Enter") {
    e.preventDefault(); e.stopPropagation();
    // 焦点在「取消」上时回车应取消，避免键盘误触发危险操作
    closeAppDialog(document.activeElement !== $("app-dialog-cancel"));
  }
}

/* 返回 Promise<boolean>；alertOnly 时只保留一个「知道了」按钮 */
function appDialog({ subject = "", text = "", confirmText = "确定",
                     cancelText = "取消", danger = false, alertOnly = false } = {}) {
  if (appDialogResolve) closeAppDialog(false);
  appDialogPrevFocus = document.activeElement;
  $("app-dialog-subject").textContent = subject;
  $("app-dialog-text").textContent = text;
  const ok = $("app-dialog-ok"), cancel = $("app-dialog-cancel"), x = $("app-dialog-x");
  ok.textContent = confirmText;
  ok.className = "btn " + (danger ? "danger" : "primary");
  cancel.textContent = cancelText;
  cancel.style.display = alertOnly ? "none" : "";
  x.style.display = alertOnly ? "none" : "";
  const mask = $("app-dialog");
  mask.classList.add("show");
  mask.setAttribute("aria-hidden", "false");
  document.addEventListener("keydown", onAppDialogKey, true);
  // 焦点落在弹窗容器而非按钮，避免出现一圈默认焦点黑框；键盘仍可 Tab / Enter / Esc
  mask.querySelector(".modal").focus();
  return new Promise((resolve) => { appDialogResolve = resolve; });
}

const confirmDialog = (subject, text, opts = {}) => appDialog({ subject, text, ...opts });
const alertDialog = (text) => appDialog({ subject: "提示", text, confirmText: "知道了", alertOnly: true });

$("app-dialog-ok").addEventListener("click", () => closeAppDialog(true));
$("app-dialog-cancel").addEventListener("click", () => closeAppDialog(false));
$("app-dialog-x").addEventListener("click", () => closeAppDialog(false));
$("app-dialog").addEventListener("click", (e) => {
  if (e.target.id === "app-dialog") closeAppDialog(false);
});

/* 兜底：以后任何代码再调原生 alert，也不会弹出「127.0.0.1:5050 显示」。
   confirm 是同步 API，不能安全替换成 Promise，因此项目内已全部改用 await confirmDialog。 */
window.alert = (msg) => { alertDialog(String(msg ?? "")); };

/* Flask 生产模式会缓存模板：刷新页面时把已下线的 ClawBot 维护提示截掉，
   无需为一句文案重启软件。模板源码已同步，程序下次重启后本分支不再命中。 */
const clawbotNote = document.querySelector(".clawbot-note");
if (clawbotNote && clawbotNote.textContent.includes("注意：")) {
  clawbotNote.textContent = clawbotNote.textContent.split("注意：")[0].trim();
}

/* 行内提示：结果类提示几秒后自动收起，避免「添加成功」一直挂在页面上。
   sticky=true 用于「正在…」这类进度提示（随后会被结果覆盖）。 */
const HINT_MS = 7000;
const hintTimers = new WeakMap();
function hint(node, text, kind = "", sticky = false) {
  const el = typeof node === "string" ? $(node) : node;
  if (!el) return;
  const prev = hintTimers.get(el);
  if (prev) { clearTimeout(prev); hintTimers.delete(el); }
  el.textContent = text;
  el.title = text || "";   // 槽位单行省略时，悬停仍可看完整提示
  el.className = "hint" + (kind ? " " + kind : "");
  if (text && !sticky) {
    const timer = setTimeout(() => {
      el.textContent = "";
      el.title = "";
      el.className = "hint";
      hintTimers.delete(el);
    }, HINT_MS);
    hintTimers.set(el, timer);
  }
}

/* 固定槽位文字：写入同时留 title，单行省略后仍可悬停查看完整内容 */
function setSlotText(id, text) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.title = text || "";
}

/* ---------------- 时段问候语 ---------------- */
function greetingWord(h) {
  if (h >= 5 && h < 11) return "早上好";
  if (h >= 11 && h < 14) return "中午好";
  if (h >= 14 && h < 18) return "下午好";
  if (h >= 18 && h < 22) return "晚上好";
  return "夜深了";
}

function setGreeting() {
  const h = new Date().getHours();
  const night = h < 5 || h >= 22;
  const word = greetingWord(h);
  const inStock = productCache.filter((p) => p.status === "in_stock");
  let g;
  if (inStock.length === 0) {
    g = night ? "夜深了，早点休息~ 目前雪茄均没货"
              : `${word}，目前雪茄均没货`;
  } else if (inStock.length === 1) {
    const brand = inStock[0].tag_buckets?.brand?.[0];
    if (night) {
      g = brand ? `夜深了，${brand}雪茄有货，抢完再睡！`
                : "夜深了，有一款雪茄有货，抢完再睡！";
    } else {
      g = brand ? `${word}，${brand}雪茄有货，抓紧抢购！`
                : `${word}，有一款雪茄有货，抓紧抢购！`;
    }
  } else {
    g = night ? `夜深了，${inStock.length}款雪茄有货，抢完再睡！`
              : `${word}，${inStock.length}款雪茄有货，抓紧抢购！`;
  }
  const el = $("greeting");
  if (el.textContent !== g) el.textContent = g;
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
function searchableText(p) {
  // 商品名、网址之外，把品牌的英文、中文简称、中文全称都纳入搜索
  const brands = (p.tag_buckets?.brand || []).map((en) => {
    const z = brandMap[en];
    return z ? `${en} ${z.short} ${z.full}` : en;
  }).join(" ");
  return `${p.name} ${p.url} ${brands}`.toLowerCase();
}

function filtered() {
  const q = filterState.q.trim().toLowerCase();
  return productCache.filter((p) => {
    if (q && !searchableText(p).includes(q)) return false;
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
  setSlotText("filter-meta", active ? `筛选结果：${list.length} / ${productCache.length} 项` : "");
  hideHighlight();
  setGreeting();
}

function buildTagFilter() {
  const counts = {};
  for (const p of productCache)
    for (const t of p.tags) counts[t] = (counts[t] || 0) + 1;
  const tags = [...new Set(productCache.flatMap((p) => p.tag_buckets.brand || []))].sort();
  $("tag-filter").innerHTML = tags.map((t) => {
    const zh = brandMap[t]?.short;          // 标签只附中文简称
    const label = zh ? `${t} ${zh}` : t;
    return `<button class="chip ${filterState.tags.has(t) ? "active" : ""}" data-tag="${esc(t)}">${esc(label)}<span class="chip-n">${counts[t]}</span></button>`;
  }).join("");
}

async function loadBrands() {
  try {
    const rows = await api("/api/brands");
    brandMap = Object.fromEntries(rows.map((r) => [r.en, r]));
  } catch (e) {
    brandMap = {};
  }
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
      const ok = await confirmDialog("删除监控项", "确定删除该监控项及其日志？此操作不可撤销。", {
        confirmText: "删除", danger: true,
      });
      if (!ok) return;
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

/* 邮箱设置入口：展开「发信邮箱与监控设置」并滚动过去 */
function openMailSettings() {
  const card = $("card-settings");
  card.classList.remove("collapsed");
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}
$("btn-email").addEventListener("click", openMailSettings);

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
  if (!url) { hint(msg, "请输入网址", "error"); return; }
  $("btn-add").disabled = true;
  hint(msg, "正在抓取并检查，请稍候...", "", true);
  try {
    await api("/api/products", { method: "POST", body: JSON.stringify({ url }) });
    $("add-url").value = "";
    hint(msg, "添加成功，已完成首次检查", "ok");
    refreshAll();
  } catch (err) { hint(msg, err.message, "error"); }
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
    hint(msg, "设置已保存，调度已更新", "ok");
    loadOverview();
  } catch (err) { hint(msg, err.message, "error"); }
});

$("btn-test-email").addEventListener("click", async () => {
  const msg = $("settings-msg");
  hint(msg, "正在发送测试邮件...", "", true);
  try {
    await api("/api/test-email", { method: "POST" });
    hint(msg, "测试邮件已发送，请查收", "ok");
  } catch (err) { hint(msg, err.message, "error"); }
});

/* ---------------- 微信 ClawBot ---------------- */
let qrSession = null;
let qrTimer = null;
let qrRenderedUrl = "";
let activationTimer = null;

/* 已绑定但还没收到用户消息时，自动盯着状态：用户在微信里发一条消息后，
   后台长轮询会拿到 context_token，界面随即自动变为「通道就绪」。 */
function startActivationWatch() {
  if (activationTimer) return;
  let ticks = 0;
  activationTimer = setInterval(async () => {
    ticks += 1;
    // 最多盯 10 分钟，避免页面长时间开着时无谓地每 3 秒刷一次
    if (ticks > 200) {
      clearInterval(activationTimer);
      activationTimer = null;
      return;
    }
    try {
      const s = await api("/api/clawbot/status");
      if (s.ready || !s.bound) {
        clearInterval(activationTimer);
        activationTimer = null;
        // 状态卡片本身会变绿并显示「通道就绪」，不再重复写一条常驻引导
      }
      await loadClawbotStatus();
    } catch (err) { /* 瞬时失败，下一轮再试 */ }
  }, 3000);
}

function clawbotMsg(text, kind = "") {
  hint($("clawbot-msg"), text, kind);
}

async function loadClawbotStatus() {
  try {
    const s = await api("/api/clawbot/status");
    $("clawbot-dot").className = "clawbot-dot " + (s.bound ? (s.ready ? "on" : "warn") : "off");
    $("clawbot-state-text").textContent = s.bound
      ? "已绑定微信 ClawBot（" + esc(s.account_id || "") + "）"
      : "未绑定微信 ClawBot";
    let tip = s.bound ? s.tip : "点「扫码绑定微信」，手机微信扫一次即可，无需账号或 API Key";
    if (s.bound && s.last_token_at) tip += " · 最近会话 " + esc(s.last_token_at);
    setSlotText("clawbot-state-tip", tip);
    $("btn-clawbot-unbind").disabled = !s.bound;
    $("btn-clawbot-test").disabled = !s.bound;
    // 已绑定时不再显示「扫码绑定微信」主按钮；解绑或凭证失效后会自动恢复
    $("btn-clawbot-bind").style.display = s.bound ? "none" : "";
    if (s.bound && !s.ready) startActivationWatch();
    if (!s.bound && activationTimer) {
      clearInterval(activationTimer);
      activationTimer = null;
    }
  } catch (err) {
    $("clawbot-state-text").textContent = "状态读取失败";
    setSlotText("clawbot-state-tip", err.message);
  }
}

function renderQr(url) {
  if (!url || url === qrRenderedUrl) return;
  qrRenderedUrl = url;
  const box = $("clawbot-qr");
  box.innerHTML = "";
  new QRCode(box, {
    text: url, width: 172, height: 172,
    colorDark: "#1d1d1f", colorLight: "#ffffff",
    correctLevel: QRCode.CorrectLevel.M,
  });
  $("clawbot-qr-link").href = url;
}

function stopQrPoll() {
  if (qrTimer) { clearInterval(qrTimer); qrTimer = null; }
}

async function pollQr() {
  if (!qrSession) return;
  try {
    const s = await api("/api/clawbot/qr/status?session=" + encodeURIComponent(qrSession));
    renderQr(s.qr_url);
    setSlotText("clawbot-qr-msg", s.message || "等待扫码...");
    $("clawbot-verify").hidden = s.status !== "need_verifycode";
    if (s.status === "confirmed") {
      stopQrPoll();
      qrSession = null;
      $("clawbot-qr-box").hidden = true;
      clawbotMsg("绑定成功！请在微信里给 ClawBot 发任意一条消息，界面会自动变为「通道就绪」", "warn");
      toast("微信 ClawBot 绑定成功");
      await loadClawbotStatus();
    } else if (["timeout", "error"].includes(s.status) || s.expired) {
      stopQrPoll();
      qrSession = null;
      clawbotMsg(s.message || "二维码已过期，请重新扫码");
    }
  } catch (err) {
    stopQrPoll();
    qrSession = null;
    clawbotMsg(err.message);
  }
}

$("btn-clawbot-bind").addEventListener("click", async () => {
  const btn = $("btn-clawbot-bind");
  btn.disabled = true;
  clawbotMsg("正在获取二维码...");
  try {
    const r = await api("/api/clawbot/qr/start", { method: "POST" });
    qrSession = r.session;
    qrRenderedUrl = "";
    $("clawbot-qr-box").hidden = false;
    $("clawbot-verify").hidden = true;
    renderQr(r.qr_url);
    setSlotText("clawbot-qr-msg", r.message || "请用手机微信扫描二维码");
    clawbotMsg("等待扫码，二维码 5 分钟内有效");
    stopQrPoll();
    qrTimer = setInterval(pollQr, 1500);
  } catch (err) {
    clawbotMsg(err.message);
    toast(err.message, true);
  }
  btn.disabled = false;
});

$("btn-clawbot-verify").addEventListener("click", async () => {
  const code = $("clawbot-verify-code").value.trim();
  if (!code || !qrSession) return;
  try {
    await api("/api/clawbot/qr/verify", {
      method: "POST", body: JSON.stringify({ session: qrSession, code }),
    });
    clawbotMsg("配对码已提交，正在验证...");
  } catch (err) { clawbotMsg(err.message); }
});

$("btn-clawbot-test").addEventListener("click", async () => {
  clawbotMsg("正在检查微信通道...");
  try {
    await api("/api/clawbot/test", { method: "POST" });
    clawbotMsg("测试微信已发送，请查看微信 ClawBot 对话", "ok");
  } catch (err) {
    const needActivation = err.data && err.data.need_activation;
    clawbotMsg(err.message, needActivation ? "warn" : "error");
  }
  await loadClawbotStatus();
});

$("btn-clawbot-unbind").addEventListener("click", async () => {
  const ok = await confirmDialog("解绑微信 ClawBot", "解绑后将不再推送微信通知，需要重新扫码才能再次绑定。", {
    confirmText: "解绑", danger: true,
  });
  if (!ok) return;
  try {
    await api("/api/clawbot/unbind", { method: "POST" });
    clawbotMsg("已解绑", "ok");
    await loadClawbotStatus();
  } catch (err) { clawbotMsg(err.message); }
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
      btn.textContent = oldText; // 等用户确认期间不要一直显示「检查中...」
      const go = await confirmDialog(
        `发现新版本 v${info.latest}`,
        `当前版本 v${info.current}，立即下载并自动重启更新。${notes}`,
        { confirmText: "立即更新" });
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
  await loadClawbotStatus();
  await loadBrands();
  await refreshAll();
  setInterval(loadOverview, 15000);
  setInterval(refreshAll, 30000);
  setInterval(setGreeting, 60000);
}
init();
