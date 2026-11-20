"use strict";

const $ = (id) => document.getElementById(id);
const state = { fonts: [], defaults: null, result: null };

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function fmtBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return n + " B";
  return (n / 1024).toFixed(1) + " KB";
}

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// ---------- 初始化 ----------
async function init() {
  const [fontsResp, defaults] = await Promise.all([
    api("/api/fonts"), api("/api/defaults"),
  ]);
  state.fonts = fontsResp.fonts;
  state.defaults = defaults;

  const sel = $("font-select");
  sel.innerHTML = state.fonts.map((f) =>
    `<option value="${esc(f.id)}">${esc(f.family)} ${esc(f.style)}（${f.glyph_count} 字形）</option>`
  ).join("");
  sel.addEventListener("change", onFontChange);
  onFontChange();

  $("corpus").value = defaults.corpus.map((s) => s.text).join("\n");
  $("heldout").value = defaults.heldout.map((s) => s.text).join("\n");
  $("corpus-notes").innerHTML = defaults.corpus.map((s) =>
    `<li><b>${esc(s.text)}</b> — ${esc(s.note)}</li>`).join("");
  $("heldout-notes").innerHTML = defaults.heldout.map((s) =>
    `<li><b>${esc(s.text)}</b> — ${esc(s.note)}</li>`).join("");
  $("build-btn").addEventListener("click", onBuild);
}

function onFontChange() {
  const font = state.fonts.find((f) => f.id === $("font-select").value);
  if (!font) return;
  $("font-meta").textContent = `许可：${font.license}`;
  const defaults = new Set(state.defaults.features);
  const renderChecks = (tags) => tags.map((t) =>
    `<label title="${t}"><input type="checkbox" value="${esc(t)}"${
      defaults.has(t) ? " checked" : ""}> ${esc(t)}</label>`).join("");
  $("gsub-features").innerHTML = renderChecks(font.gsub_features);
  $("gpos-features").innerHTML = renderChecks(font.gpos_features);
}

function selectedFeatures() {
  return [...document.querySelectorAll(
    "#gsub-features input:checked, #gpos-features input:checked")]
    .map((el) => el.value);
}

// ---------- 构建 ----------
async function onBuild() {
  const btn = $("build-btn");
  btn.disabled = true;
  $("build-status").textContent = "构建中……";
  try {
    const body = {
      font_id: $("font-select").value,
      features: selectedFeatures(),
      direction: $("direction").value,
      corpus: $("corpus").value.split("\n").map((s) => s.trim()).filter(Boolean),
      heldout: $("heldout").value.split("\n").map((s) => s.trim()).filter(Boolean),
      size_limit_kb: parseInt($("size-limit").value || "0", 10),
    };
    const result = await api("/api/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.result = result;
    renderResult(result);
    $("build-status").textContent = `构建完成：${result.build_id}`;
  } catch (err) {
    $("build-status").textContent = "失败：" + err.message;
  } finally {
    btn.disabled = false;
  }
}

// ---------- 渲染结果 ----------
function renderResult(r) {
  renderConflict(r);
  renderWarnings(r);
  renderOverview(r);
  renderSamples(r);
  renderVerify(r);
  renderInventories(r);
  $("results").classList.remove("hidden");
}

function renderWarnings(r) {
  const box = $("warnings");
  if (!r.warnings || !r.warnings.length) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = r.warnings.map((w) => `<div>[注意] ${esc(w)}</div>`).join("");
}

function renderConflict(r) {
  const box = $("conflict");
  if (!r.conflict) {
    box.classList.add("hidden");
    return;
  }
  const c = r.conflict;
  const rows = Object.entries(c.savings)
    .sort((a, b) => b[1] - a[1])
    .map(([f, s]) =>
      `<tr><td>${esc(f)}</td><td>${fmtBytes(s)}</td></tr>`).join("");
  box.classList.remove("hidden");
  box.innerHTML = `
    <h2>体积限制与排版行为无法兼得</h2>
    <p>闭包子集需要 <b>${fmtBytes(c.size_all)}</b>，超出限制
       <b>${fmtBytes(c.limit)}</b>。</p>
    <p>首个冲突词：<b>「${esc(c.word ?? "（无样本依赖该特性）")}」</b>
       —— 依赖特性 <b>${esc(c.feature)}</b>。
       去掉 ${esc(c.feature)} 后为 ${fmtBytes(c.size_without_feature)}，
       ${c.fits_without_feature ? "可以达标" : "仍然超限"}。</p>
    <p>请修改功能集合后重新出包。各特性的体积贡献：</p>
    <table class="savings-table">
      <thead><tr><th>特性</th><th>去掉可省</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderOverview(r) {
  const A = r.strategies.shaped, B = r.strategies.closure;
  $("ov-a-name").textContent = "方案 A：" + A.label;
  $("ov-b-name").textContent = "方案 B：" + B.label;
  $("ov-orig-glyphs").textContent = r.original.glyph_count;
  $("ov-a-glyphs").textContent = A.glyph_count;
  $("ov-b-glyphs").textContent = B.glyph_count;
  $("ov-orig-size").textContent = fmtBytes(r.original.size);
  $("ov-a-size").textContent = fmtBytes(A.size_ttf);
  $("ov-b-size").textContent = fmtBytes(B.size_ttf);
  $("ov-a-woff2").textContent = fmtBytes(A.size_woff2);
  $("ov-b-woff2").textContent = fmtBytes(B.size_woff2);
  const match = (s) => {
    const ok = s.verify.sample_checks.filter((c) => c.equal).length;
    return `${ok} / ${s.verify.sample_checks.length}`;
  };
  $("ov-a-match").textContent = match(A);
  $("ov-b-match").textContent = match(B);
  const dl = (s) =>
    `<a class="dl" href="${s.download.ttf}">TTF</a> · ` +
    `<a class="dl" href="${s.download.woff2}">WOFF2</a>`;
  $("ov-a-dl").innerHTML = dl(A);
  $("ov-b-dl").innerHTML = dl(B);
}

function renderSamples(r) {
  const A = r.strategies.shaped, B = r.strategies.closure;
  const checksOf = (s) => Object.fromEntries(
    s.verify.sample_checks.map((c) => [c.text, c]));
  const ca = checksOf(A), cb = checksOf(B);
  $("sample-rows").innerHTML = r.samples.map((s, i) => {
    const orig = r.original.samples[i], sa = A.samples[i], sb = B.samples[i];
    const badge = (c) => c.equal
      ? '<span class="badge ok">与原版一致</span>'
      : `<span class="badge bad">有差异</span>` +
        `<div class="diff-detail">${esc(c.diffs.join("\n"))}</div>`;
    return `<div class="sample-row${s.held_out ? " heldout" : ""}">
      <div class="sample-text">${esc(s.text)}${
        s.held_out ? '<span class="tag">预留组合</span>' : ""}</div>
      <div class="render-cell">${orig.svg}</div>
      <div class="render-cell">${sa.svg}${badge(ca[s.text])}</div>
      <div class="render-cell">${sb.svg}${badge(cb[s.text])}</div>
    </div>`;
  }).join("");
}

function renderVerify(r) {
  const render1 = (elId, s, title) => {
    const v = s.verify;
    const mapRows = v.mapping.slice(0, 60).map((m) =>
      `<tr><td>${m.new_gid}</td><td>${esc(m.name)}</td><td>${
        m.old_gid ?? "—"}</td></tr>`).join("");
    const more = v.mapping.length > 60
      ? `<tr><td colspan="3">…… 共 ${v.mapping.length} 条</td></tr>` : "";
    const ok = (b, text) => b
      ? `<span class="verify-ok">✓ ${text}</span>`
      : `<span class="verify-bad">✗ ${text}</span>`;
    $(elId).innerHTML = `
      <h3>${esc(title)}</h3>
      <p>${ok(v.mapping_ok, "轮廓来源映射：新 gid → 原版 gid 一一对应")}</p>
      <p>${ok(v.outline_mismatches.length === 0,
        `轮廓一致（${v.outline_mismatches.length} 处不一致）`)}</p>
      <p>${ok(v.metric_mismatches.length === 0,
        `推进量一致（${v.metric_mismatches.length} 处不一致）`)}</p>
      <p>偏移与推进量（整形结果逐字形对比）：</p>
      <ul>${v.sample_checks.map((c) =>
        `<li class="${c.equal ? "verify-ok" : "verify-bad"}">${
          c.equal ? "✓" : "✗"} ${esc(c.text)}</li>`).join("")}</ul>
      <details><summary>映射表（新 gid / 字形名 / 原版 gid）</summary>
        <table><thead><tr><th>新 gid</th><th>名称</th><th>原版 gid</th></tr></thead>
        <tbody>${mapRows}${more}</tbody></table>
      </details>`;
  };
  render1("verify-a", r.strategies.shaped, "方案 A：" + r.strategies.shaped.label);
  render1("verify-b", r.strategies.closure, "方案 B：" + r.strategies.closure.label);
}

function renderInventories(r) {
  const render1 = (elId, titleId, key, s) => {
    $(titleId).textContent = `${key}：${s.label}（${s.glyph_count} 字形）`;
    $(elId).innerHTML = s.glyphs.map((g) => {
      const kind = g.reason ? g.reason.kind : "none";
      return `<button class="glyph-btn kind-${kind}" data-strategy="${
        key === "方案 A" ? "shaped" : "closure"}" data-name="${esc(g.name)}"
        title="${esc(g.reason ? g.reason.detail : "")}">${esc(g.name)}</button>`;
    }).join("");
    $(elId).querySelectorAll(".glyph-btn").forEach((btn) =>
      btn.addEventListener("click", () =>
        showInspector(btn.dataset.strategy, btn.dataset.name)));
  };
  render1("inventory-a", "inv-a-title", "方案 A", r.strategies.shaped);
  render1("inventory-b", "inv-b-title", "方案 B", r.strategies.closure);
}

// ---------- 字形检查器 ----------
async function showInspector(strategy, name) {
  const r = state.result;
  const s = r.strategies[strategy];
  const entry = s.glyphs.find((g) => g.name === name);
  const byName = Object.fromEntries(s.glyphs.map((g) => [g.name, g]));

  const reasonChain = (gname, depth, seen) => {
    const g = byName[gname];
    if (!g || !g.reason || depth > 6 || seen.has(gname)) return "";
    seen.add(gname);
    const rs = g.reason;
    const srcs = (rs.sources || []).map((src) =>
      `<div class="node"><b>${esc(src)}</b>${reasonChain(src, depth + 1, seen)}</div>`
    ).join("");
    return `<div class="node">${esc(rs.detail)}${
      rs.feature ? ` <span class="meta">[特性 ${esc(rs.feature)}${
        rs.lookup != null ? " · lookup " + rs.lookup : ""}]</span>` : ""
    }${srcs}</div>`;
  };

  const pos = (entry.positioning || []).map((p) =>
    `<li>${esc(p)}</li>`).join("");

  $("inspector-body").innerHTML = `
    <p><b>${esc(name)}</b>（新 gid ${entry.gid}）</p>
    <div class="glyph-svgs" id="glyph-svgs">加载中……</div>
    <h3>留下原因</h3>
    <div class="reason-chain">${reasonChain(name, 0, new Set()) || "（无记录）"}</div>
    <h3>定位关系</h3>
    <ul class="positioning-list">${pos || "<li>（无）</li>"}</ul>`;
  $("inspector").classList.remove("hidden");

  const glyphs = await api(
    `/api/glyph/${r.build_id}/${strategy}/${encodeURIComponent(name)}`);
  $("glyph-svgs").innerHTML = `
    <figure>${glyphs.subset_svg || "（子集中缺失）"}<figcaption>子集</figcaption></figure>
    <figure>${glyphs.original_svg || "（原版缺失）"}<figcaption>原版</figcaption></figure>`;
}

init().catch((err) => {
  $("build-status").textContent = "初始化失败：" + err.message;
});
