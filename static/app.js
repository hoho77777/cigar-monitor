// 雪茄库存监控前端逻辑
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const STATUS_LABEL = { in_stock: "有货", out_of_stock: "缺货", unknown: "未知" };

let products = [];
let settings = {};
let filterState = { keyword: "", tag: "", inStockOnly: false };

// ---------------- 通用提示 ----------------
function showToast(text, ms = 2600) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => t.classList.remove("show"), ms);
}

function setHint(id, text, ok = true) {
  const el = $(id);
  el.textContent = text;
  el.className = "hint " + (ok ? "ok" : "err");
}

async function api(url, options = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await resp.json();
  if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

// ---------------- 版本号 ----------------
async function loadVersion() {
  try {
    const data = await api("/api/version");
    $("#app-version").textContent = "v" + data.version;
  } catch (e) {}
}

// ---------------- 概览 ----------------
function renderOverview() {
  const total = products.length;
  const enabled = products.filter((p) => p.enabled).length;
  const inStock = products.filter((p) => p.status === "in_stock").length;
  const outStock = products.filter((p) => p.status === "out_of_stock").length;
  const unknown = products.filter((p) => p.status === "unknown").length;
  $("#st-total").textContent = total;
  $("#st-enabled").textContent = enabled;
  $("#st-in").textContent = inStock;
  $("#st-out").textContent = outStock;
  $("#st-unknown").textContent = unknown;
}

// ---------------- 筛选 ----------------
function buildTagFilter() {
  const tags = new Set();
  products.forEach((p) => {
    (p.tags || []).forEach((t) => tags.add(t));
  });
  const wrap = $("#tag-filter");
  wrap.innerHTML = "";
  Array.from(tags).sort().forEach((t) => {
    const chip = document.createElement("button");
    chip.className = "tag-chip" + (filterState.tag === t ? " active" : "");
    chip.textContent = t;
    chip.onclick = () => {
      filterState.tag = filterState.tag === t ? "" : t;
      renderProducts();
    };
    wrap.appendChild(chip);
  });
}

function filteredProducts() {
  const kw = filterState.keyword.trim().toLowerCase();
  return products.filter((p) => {
    if (filterState.inStockOnly && p.status !== "in_stock") return false;
    if (filterState.tag && !(p.tags || []).includes(filterState.tag)) return false;
    if (kw) {
      const hay = `${p.name} ${p.url}`.toLowerCase();
      if (!hay.includes(kw)) return false;
    }
    return true;
  });
}

// ---------------- 商品列表 ----------------
const grid = $("#monitor-grid");
const highlight = $("#hover-highlight");

function moveHighlight(row) {
  const g = grid.getBoundingClientRect();
  const r = row.getBoundingClientRect();
  highlight.style.top = (r.top - g.top) + "px";
  highlight.style.height = r.height + "px";
  highlight.classList.add("on");
}

function hideHighlight() {
  highlight.classList.remove("on");
}

function renderProducts() {
  hideHighlight();
  buildTagFilter();
  const list = $("#product-list");
  list.innerHTML = "";
  const shown = filteredProducts();

  shown.forEach((p) => {
    const row = document.createElement("div");
    row.className = "prod-row";
    row.dataset.id = p.id;

    const badge = `<span class="badge ${p.status}">${STATUS_LABEL[p.status] || "未知"}</span>`;
    const detail = p.status_text ? `<span class="status-detail">${p.status_text}</span>` : "";

    row.innerHTML = `
      <div class="cell cell-first">
        <div class="prod-name">${p.name}</div>
        <a class="prod-url" href="${p.url}" target="_blank" rel="noopener">${p.url}</a>
      </div>
      <div class="cell">${badge}${detail}</div>
      <div class="cell">${p.last_checked || "-"}</div>
      <div class="cell">${p.last_notified || "-"}</div>
      <div class="cell cell-center">
        <label class="switch">
          <input type="checkbox" data-toggle="${p.id}" ${p.enabled ? "checked" : ""}>
          <span class="slider"></span>
        </label>
      </div>
      <div class="cell cell-last">
        <button class="icon-btn" data-check="${p.id}" title="立即检查">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
        </button>
        <button class="icon-btn danger" data-del="${p.id}" title="删除">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
        </button>
      </div>`;
    list.appendChild(row);
  });

  $("#filter-meta").textContent = `共 ${products.length} 项，当前显示 ${shown.length} 项`;
  renderOverview();
}

// 事件委托：行悬停（单一连续背景）
grid.addEventListener("mouseover", (e) => {
  const row = e.target.closest(".prod-row");
  if (row && grid.contains(row)) moveHighlight(row);
});
grid.addEventListener("mouseout", (e) => {
  const row = e.target.closest(".prod-row");
  if (row && !row.contains(e.relatedTarget)) hideHighlight();
});
window.addEventListener("scroll", hideHighlight, true);
window.addEventListener("resize", hideHighlight);

// ---------------- 数据加载 ----------------
async function loadProducts() {
  products = await api("/api/products");
  renderProducts();
}

// ---------------- 添加 ----------------
$("#btn-add").onclick = async () => {
  const url = $("#add-url").value.trim();
  if (!url) return setHint("#add-msg", "请先粘贴商品网址", false);
  setHint("#add-msg", "正在添加并检查，请稍候...");
  try {
    const r = await api("/api/products", { method: "POST", body: JSON.stringify({ url }) });
    $("#add-url").value = "";
    setHint("#add-msg", `已添加：${r.name}，当前状态：${STATUS_LABEL[r.status] || r.status}`);
    await loadProducts();
  } catch (e) {
    setHint("#add-msg", e.message, false);
  }
};

// ---------------- 列表操作（事件委托） ----------------
$("#product-list").addEventListener("click", async (e) => {
  const checkBtn = e.target.closest("[data-check]");
  const delBtn = e.target.closest("[data-del]");
  if (checkBtn) {
    const id = checkBtn.dataset.check;
    showToast("正在检查...");
    try {
      const r = await api(`/api/products/${id}/check`, { method: "POST" });
      showToast(`${r.name}：${STATUS_LABEL[r.status] || r.status}`);
      await loadProducts();
    } catch (err) {
      showToast(err.message);
    }
  } else if (delBtn) {
    const id = delBtn.dataset.del;
    if (!confirm("确定删除该监控项及其日志？")) return;
    try {
      await api(`/api/products/${id}`, { method: "DELETE" });
      await loadProducts();
      showToast("已删除");
    } catch (err) {
      showToast(err.message);
    }
  }
});

// 启用开关
$("#product-list").addEventListener("change", async (e) => {
  const toggle = e.target.closest("[data-toggle]");
  if (!toggle) return;
  const id = toggle.dataset.toggle;
  try {
    await api(`/api/products/${id}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: toggle.checked ? 1 : 0 }),
    });
    await loadProducts();
  } catch (err) {
    showToast(err.message);
  }
});

// ---------------- 全部检查 ----------------
$("#btn-check-all").onclick = async () => {
  showToast("正在检查全部监控项...");
  try {
    const r = await api("/api/check-all", { method: "POST" });
    showToast(`检查完成：${r.checked} 项，有货 ${r.in_stock} 项`);
    await loadProducts();
  } catch (e) {
    showToast(e.message);
  }
};

// ---------------- 筛选面板 ----------------
$("#btn-filter").onclick = () => {
  $("#filter-panel").classList.toggle("open");
};

$("#filter-search").addEventListener("input", (e) => {
  filterState.keyword = e.target.value;
  renderProducts();
});

$("#filter-search-btn").onclick = () => {
  showToast(filterState.keyword ? `搜索：${filterState.keyword}` : "请输入关键词");
};

$("#stock-only").addEventListener("change", (e) => {
  filterState.inStockOnly = e.target.checked;
  renderProducts();
});

// ---------------- 检查更新 ----------------
$("#btn-check-update").onclick = async () => {
  showToast("正在检查更新...");
  try {
    const r = await api("/api/check-update", { method: "POST" });
    if (!r.update) {
      showToast("当前已是最新版本");
      return;
    }
    const u = r.update;
    const notes = u.notes ? `\n更新说明：${u.notes}` : "";
    const ok = confirm(`发现新版本 v${u.latest}\n当前版本：v${u.current}${notes}\n\n是否立即下载并自动更新？`);
    if (!ok) return;
    showToast("正在下载更新，完成后将自动重启...");
    const res = await api("/api/apply-update", {
      method: "POST",
      body: JSON.stringify({ download_url: u.download_url }),
    });
    showToast(res.message || "更新已启动");
  } catch (e) {
    showToast("更新失败：" + e.message);
  }
};

// ---------------- 设置 ----------------
function fillPresetSelect() {
  const sel = $("#set-preset");
  sel.innerHTML = "";
  Object.entries(window.SMTP_PRESETS || {}).forEach(([key, p]) => {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = p.label;
    sel.appendChild(opt);
  });
}

async function loadSettings() {
  settings = await api("/api/settings");
  const presets = await api("/api/settings/presets");
  window.SMTP_PRESETS = presets;
  fillPresetSelect();
  $("#set-preset").value = settings.smtp_preset;
  $("#set-host").value = settings.smtp_host;
  $("#set-port").value = settings.smtp_port;
  $("#set-security").value = settings.smtp_security;
  $("#set-user").value = settings.smtp_user;
  $("#set-pass").value = settings.smtp_pass;
  $("#set-to").value = settings.mail_to;
  $("#set-from-name").value = settings.mail_from_name;
  $("#set-interval").value = settings.check_interval;
  $("#set-notify-mode").value = settings.notify_mode;
}

$("#set-preset").onchange = (e) => {
  const p = window.SMTP_PRESETS[e.target.value];
  if (!p) return;
  $("#set-host").value = p.host;
  $("#set-port").value = p.port;
  $("#set-security").value = p.security;
};

function collectSettings() {
  return {
    smtp_preset: $("#set-preset").value,
    smtp_host: $("#set-host").value,
    smtp_port: $("#set-port").value,
    smtp_security: $("#set-security").value,
    smtp_user: $("#set-user").value,
    smtp_pass: $("#set-pass").value,
    mail_to: $("#set-to").value,
    mail_from_name: $("#set-from-name").value,
    check_interval: $("#set-interval").value,
    notify_mode: $("#set-notify-mode").value,
  };
}

$("#btn-save-settings").onclick = async () => {
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(collectSettings()) });
    setHint("#settings-msg", "设置已保存");
    await loadSettings();
    await loadProducts();
  } catch (e) {
    setHint("#settings-msg", e.message, false);
  }
};

$("#btn-test-email").onclick = async () => {
  setHint("#settings-msg", "正在发送测试邮件...");
  try {
    const r = await api("/api/test-email", { method: "POST" });
    setHint("#settings-msg", `测试邮件已发送至 ${r.sent_to.join(", ")}`);
  } catch (e) {
    setHint("#settings-msg", e.message, false);
  }
};

// ---------------- 日志 ----------------
async function loadLogs() {
  const logs = await api("/api/logs?limit=50");
  const nameMap = Object.fromEntries(products.map((p) => [p.id, p.name]));
  $("#log-rows").innerHTML = logs
    .map((l) => {
      const label = STATUS_LABEL[l.status] || l.status;
      return `<tr><td>${l.checked_at}</td><td>${nameMap[l.product_id] || "#" + l.product_id}</td>
      <td><span class="badge ${l.status}">${label}</span></td><td>${l.http_code || "-"}</td>
      <td>${l.detail || ""}</td></tr>`;
    })
    .join("");
}

$("#btn-refresh-logs").onclick = async () => {
  await loadLogs();
  showToast("日志已刷新");
};

// ---------------- 英文地址 ----------------
let addressData = {};

async function openAddressModal() {
  try {
    addressData = await api("/api/address");
  } catch (e) {
    addressData = {};
  }
  $("#addr-line1").value = addressData.line1 || "";
  $("#addr-line2").value = addressData.line2 || "";
  $("#addr-country").value = addressData.country || "";
  $("#addr-state").value = addressData.state || "";
  $("#addr-city").value = addressData.city || "";
  $("#addr-zip").value = addressData.zip || "";
  const modal = $("#address-modal");
  modal.classList.add("show");
  modal.setAttribute("aria-hidden", "false");
}

function closeAddressModal() {
  const modal = $("#address-modal");
  modal.classList.remove("show");
  modal.setAttribute("aria-hidden", "true");
}

$("#btn-address").onclick = openAddressModal;
$("#addr-close").onclick = closeAddressModal;
$("#addr-cancel").onclick = closeAddressModal;

$("#addr-save").onclick = async () => {
  const payload = {
    line1: $("#addr-line1").value,
    line2: $("#addr-line2").value,
    country: $("#addr-country").value,
    state: $("#addr-state").value,
    city: $("#addr-city").value,
    zip: $("#addr-zip").value,
  };
  try {
    await api("/api/address", { method: "POST", body: JSON.stringify(payload) });
    closeAddressModal();
    showToast("英文地址已保存");
  } catch (e) {
    showToast("保存失败：" + e.message);
  }
};

// 点击遮罩关闭
$("#address-modal").addEventListener("click", (e) => {
  if (e.target === $("#address-modal")) closeAddressModal();
});

// ---------------- 折叠面板（邮箱/日志） ----------------
function initCollapsible(cardId) {
  const card = $(cardId);
  const head = card.querySelector(".collapsible-head");
  head.onclick = (e) => {
    if (e.target.closest("button")) return; // 不拦截头部按钮
    card.classList.toggle("collapsed");
  };
}

// 邮箱图标快捷打开设置卡片
$("#btn-email").onclick = () => {
  $("#card-settings").classList.remove("collapsed");
  $("#card-settings").scrollIntoView({ behavior: "smooth" });
};

// ---------------- 下次检查倒计时 ----------------
function tickNextRun() {
  const el = $("#next-run");
  if (!window._schedulerInfo) return;
  const interval = window._schedulerInfo.interval || 300;
  if (window._nextAt == null) window._nextAt = Date.now() + interval * 1000;
  const left = Math.max(0, Math.round((window._nextAt - Date.now()) / 1000));
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  el.textContent = `下次检查：${mm}:${ss}`;
}
setInterval(tickNextRun, 1000);

// ---------------- 初始化 ----------------
(async function init() {
  initCollapsible("#card-settings");
  initCollapsible("#card-logs");
  await loadVersion();
  await loadProducts();
  await loadSettings();
  await loadLogs();
  window._schedulerInfo = { interval: settings.check_interval };
  tickNextRun();
})();
