/* 雪茄到手计算器：本地即时计算，不依赖外部网站。
   汇率来自 /api/calculator/rates（实时市场汇率 + 海关计征汇率），公式与后端一致。 */
let calcData = null;
let calcCurrency = "EUR";

const c$ = (id) => document.getElementById(id);
const round2 = (n) => Math.round((Number(n) + Number.EPSILON) * 100) / 100;

function cMoney(n) {
  return "¥" + Number(n || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

/* 单值或区间（low===high 显示单值，否则显示 low – high） */
function cRange(low, high) {
  return low === high ? cMoney(low) : cMoney(low) + " – " + cMoney(high);
}

async function loadCalcRates() {
  try {
    calcData = await api("/api/calculator/rates");
    buildPeriod();
    buildDropdown();
    updateTrigger();
    renderCalc();
  } catch (e) {
    c$("calc-period").textContent = "汇率加载失败";
  }
}

function buildPeriod() {
  const customs = calcData.customs;
  c$("calc-period").textContent =
    `海关 ${customs.period} 计征汇率 · 基准日 ${customs.actual_date || "-"} · ${customs.source}`;
}

function liveRate4(code) {
  return Number(calcData.live.rates[code]).toFixed(4);
}

/* ---------------- 自定义币种下拉 ---------------- */
function buildDropdown() {
  const panel = c$("calc-dd-panel");
  panel.innerHTML = calcData.currencies
    .map((c) => `
      <button type="button" class="cd-row ${c.code === calcCurrency ? "sel" : ""}" data-code="${c.code}">
        <span class="cd-left">
          <span class="cd-flag">${c.flag}</span>
          <span class="cd-name">${c.code} · ${c.cname}</span>
        </span>
        <span class="cd-row-rate">¥${liveRate4(c.code)}</span>
      </button>`)
    .join("");
  panel.querySelectorAll(".cd-row").forEach((row) => {
    row.addEventListener("click", () => selectCurrency(row.dataset.code));
  });
}

function selectCurrency(code) {
  calcCurrency = code;
  closeDropdown();
  buildDropdown();
  updateTrigger();
  renderCalc();
}

function updateTrigger() {
  const c = calcData.currencies.find((x) => x.code === calcCurrency);
  c$("cd-flag").textContent = c.flag;
  c$("cd-name").textContent = `${c.code} · ${c.cname}`;
  c$("cd-rate").textContent = `1 ${c.code} = ¥${liveRate4(c.code)}`;
  updatePrefixes();
}

function updatePrefixes() {
  const c = calcData.currencies.find((x) => x.code === calcCurrency);
  c$("price-prefix").textContent = c.symbol;
  c$("ship-prefix").textContent = c.symbol;
}

function openDropdown() { c$("calc-dropdown").classList.add("open"); }
function closeDropdown() { c$("calc-dropdown").classList.remove("open"); }

function calcCompute() {
  const code = calcCurrency;
  const price = parseFloat(c$("calc-price").value) || 0;
  const count = Math.max(1, parseInt(c$("calc-count").value, 10) || 1);
  const shipping = parseFloat(c$("calc-shipping").value) || 0;

  const liveRate = calcData.live.rates[code];
  const customsRate = calcData.customs.rates[code];

  const goods = round2(price * liveRate);                 // 商品人民币价
  const shipCny = round2(shipping * liveRate);           // 人民币运费
  const taxableRaw = price * customsRate;
  const taxable = round2(taxableRaw);                    // 海关计税价格
  const preTax = round2(taxableRaw * 0.5);               // 免征前完整税额 50%

  const maybeExempt = preTax <= 50;                      // 税额 ≤50 可能免征
  const taxLow = maybeExempt ? 0 : preTax;
  const taxHigh = preTax;

  const totalLow = round2(goods + shipCny + taxLow);
  const totalHigh = round2(goods + shipCny + taxHigh);

  return {
    code, price, count, shipping, liveRate, customsRate,
    goods, shipCny, taxable, preTax, maybeExempt, taxLow, taxHigh,
    totalLow, totalHigh,
    unitLow: round2(totalLow / count), unitHigh: round2(totalHigh / count),
    overLimit: taxable > 2000,
    stale: Boolean(calcData.live.stale || calcData.customs.stale),
    liveSource: calcData.live.source,
    customsSource: calcData.customs.source,
    customsPeriod: calcData.customs.period,
    customsDate: calcData.customs.actual_date,
  };
}

function renderCalc() {
  const root = c$("calc-result");
  if (!calcData) return;

  const price = parseFloat(c$("calc-price").value) || 0;
  const shipping = parseFloat(c$("calc-shipping").value) || 0;
  if (price <= 0 && shipping <= 0) {
    root.innerHTML = `<div class="calc-empty">填写左侧金额，自动估算到手价</div>`;
    return;
  }

  const r = calcCompute();
  const exempt = r.maybeExempt;

  const taxBadge = exempt
    ? `<span class="crf-badge">免</span>`
    : `<span class="crf-badge tax">税</span>`;
  const taxVal = exempt ? cMoney(0) : cMoney(r.preTax);
  const grand = exempt ? cMoney(r.totalLow) : cMoney(r.totalHigh);
  const unit = exempt ? cMoney(r.unitLow) : cMoney(r.unitHigh);

  const notes = [];
  if (exempt) {
    notes.push(`<p class="cr-note">若该笔未享免征，到手价约 ${cMoney(r.totalHigh)}（单支 ${cMoney(r.unitHigh)}）。</p>`);
  }
  if (r.stale) {
    notes.push(`<p class="cr-note">当前汇率为缓存/内置参考值，联网后自动刷新。</p>`);
  }

  const risk = r.overLimit
    ? `<p class="cr-risk">海关计税价 ${cMoney(r.taxable)} 超过 2000 元寄递限值，可能退运或按货物办理，最终以海关审核为准。</p>`
    : "";

  const detailRows = [
    `<div class="drow"><span>海关计税价格</span><b>${cMoney(r.taxable)}</b></div>`,
    `<div class="drow"><span>免征前估算税额（50%）</span><b>${cMoney(r.preTax)}</b></div>`,
  ];
  if (exempt) {
    detailRows.push(`<div class="drow"><span>若全额征税·到手总价</span><b>${cMoney(r.totalHigh)}</b></div>`);
  }
  detailRows.push(
    `<div class="drow"><span>市场汇率（1 ${r.code}）</span><b>${r.liveRate.toFixed(4)}</b></div>`,
    `<div class="drow"><span>海关汇率（1 ${r.code}）</span><b>${r.customsRate.toFixed(4)}</b></div>`,
    `<div class="drow"><span>汇率来源</span><b>${r.liveSource} / ${r.customsSource}</b></div>`
  );

  root.innerHTML = `
    <p class="cr-title">计算结果</p>
    <div class="cr-formula">
      <div class="crf-item">
        <p class="crf-label">商品总价</p>
        <b class="crf-val">${cMoney(r.goods)}</b>
      </div>
      <span class="crf-plus">+</span>
      <div class="crf-item">
        <p class="crf-label">税费 ${taxBadge}</p>
        <b class="crf-val">${taxVal}</b>
      </div>
      <span class="crf-plus">+</span>
      <div class="crf-item">
        <p class="crf-label">运费</p>
        <b class="crf-val">${cMoney(r.shipCny)}</b>
      </div>
    </div>
    <div class="cr-total"><span>到手总价</span><b>${grand}</b></div>
    <div class="cr-unit"><span>到手单价（${r.count} 支）</span><b>${unit} /支</b></div>
    ${risk}
    ${notes.join("")}
    <button class="cr-detail-toggle" id="cr-detail-toggle" type="button">
      计算明细
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
    </button>
    <div class="cr-detail" id="cr-detail" hidden>${detailRows.join("")}</div>
    <ul class="cr-rules">
      <li>商品价格 × 海关汇率 ≤ 100 元人民币：免税</li>
      <li>商品价格 × 海关汇率 &gt; 100 元人民币：征收 50% 税</li>
      <li>商品总价、运费按实时汇率折算，税费按海关汇率计算</li>
    </ul>`;

  c$("cr-detail-toggle").addEventListener("click", () => {
    const d = c$("cr-detail");
    d.hidden = !d.hidden;
    c$("cr-detail-toggle").classList.toggle("open", !d.hidden);
  });
}

["calc-price", "calc-count", "calc-shipping"].forEach((id) => {
  c$(id).addEventListener("input", renderCalc);
  c$(id).addEventListener("change", renderCalc);
});

/* ---------------- 弹窗打开/关闭 ---------------- */
function openCalcModal() {
  if (!calcData) loadCalcRates();
  const m = c$("calculator-modal");
  m.classList.add("show");
  m.setAttribute("aria-hidden", "false");
  renderCalc();
}
function closeCalcModal() {
  closeDropdown();
  const m = c$("calculator-modal");
  m.classList.remove("show");
  m.setAttribute("aria-hidden", "true");
}

c$("btn-calculator").addEventListener("click", openCalcModal);
c$("calc-modal-close").addEventListener("click", closeCalcModal);
c$("calculator-modal").addEventListener("click", (e) => {
  if (e.target.id === "calculator-modal") closeCalcModal();
});

/* 下拉触发与外部点击关闭 */
c$("calc-dd-trigger").addEventListener("click", (e) => {
  e.stopPropagation();
  c$("calc-dropdown").classList.toggle("open");
});
document.addEventListener("click", (e) => {
  if (!c$("calc-dropdown").contains(e.target)) closeDropdown();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeDropdown();
    closeCalcModal();
  }
});

loadCalcRates();
