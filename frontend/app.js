(() => {
  "use strict";

  const cfg = window.TECHCOMMERCE_CONFIG || {};
  const state = {
    apiBase: localStorage.getItem("techcommerce.apiUrl") || cfg.apiBaseUrl || "/api",
    local: !!cfg.localRuntime,
    selectedOrder: null,
    lastAutomationKey: null,
  };
  const $ = (sel) => document.querySelector(sel);
  const money = (v) => Number(v || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const time = (iso) => (iso ? new Date(iso).toLocaleTimeString("pt-BR") : "-");
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const PRESETS = {
    ok: { name: "Maria Souza", email: "maria@exemplo.com.br", paymentMethod: "PIX",
      items: [["SKU-NOTEBOOK-01", "Notebook 14\"", 1, 3899.9], ["SKU-MOUSE-02", "Mouse sem fio", 2, 89.9]] },
    reject: { name: "João Lima", email: "joao@exemplo.com.br", paymentMethod: "BOLETO",
      items: [["SKU-SERVIDOR-99", "Servidor rack", 3, 8500]] },
    fail: { name: "Ana Teste", email: "ana@exemplo.com.br", paymentMethod: "CREDIT_CARD",
      items: [["SKU-FALHA-TEMPORARIA", "Item de teste de falha", 1, 10]] },
  };

  // ------------------------------------------------------------------ HTTP
  async function api(method, path, body, headers = {}) {
    const res = await fetch(state.apiBase.replace(/\/$/, "") + path, {
      method,
      headers: { "Content-Type": "application/json", ...headers },
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { data = text; }
    return { status: res.status, data };
  }
  async function local(path, method = "GET") {
    const res = await fetch(path, { method });
    return res.json();
  }
  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.classList.add("hidden"), 3500);
  }
  function pulse(svc) {
    document.querySelectorAll(`[data-svc="${svc}"]`).forEach((n) => {
      n.classList.add("pulse");
      setTimeout(() => n.classList.remove("pulse"), 1200);
    });
  }

  // ------------------------------------------------------------------ formulário de pedido
  function addItem([sku, name, qty, price] = ["", "", 1, ""]) {
    const row = document.createElement("div");
    row.className = "item-row";
    row.innerHTML = `
      <input name="sku" placeholder="SKU-001" value="${esc(sku)}" required>
      <input name="itemName" placeholder="Produto" value="${esc(name)}">
      <input name="quantity" type="number" min="1" step="1" value="${esc(qty)}" required>
      <input name="unitPrice" type="number" min="0.01" step="0.01" value="${esc(price)}" required>
      <button type="button" class="remove" title="Remover">✕</button>`;
    row.querySelector(".remove").onclick = () => { row.remove(); updateTotal(); };
    row.querySelectorAll("input").forEach((i) => (i.oninput = updateTotal));
    $("#items").appendChild(row);
    updateTotal();
  }
  function readItems() {
    return [...document.querySelectorAll(".item-row")].map((r) => ({
      sku: r.querySelector('[name="sku"]').value.trim(),
      name: r.querySelector('[name="itemName"]').value.trim(),
      quantity: Number(r.querySelector('[name="quantity"]').value),
      unitPrice: Number(r.querySelector('[name="unitPrice"]').value),
    }));
  }
  function updateTotal() {
    const total = readItems().reduce((s, i) => s + (i.quantity || 0) * (i.unitPrice || 0), 0);
    $("#orderTotal").textContent = `Total: ${money(total)}`;
  }
  function applyPreset(key) {
    const p = PRESETS[key];
    const f = $("#orderForm");
    f.name.value = p.name; f.email.value = p.email; f.paymentMethod.value = p.paymentMethod;
    $("#items").innerHTML = "";
    p.items.forEach(addItem);
  }

  $("#orderForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    const payload = {
      customer: { name: f.name.value, email: f.email.value },
      paymentMethod: f.paymentMethod.value,
      items: readItems(),
    };
    pulse("api"); pulse("create_order");
    const { status, data } = await api("POST", "/orders", payload, { "Idempotency-Key": crypto.randomUUID() });
    const out = $("#orderResult");
    out.classList.remove("hidden");
    out.textContent = `HTTP ${status}\n${JSON.stringify(data, null, 2)}`;
    if (status === 202) {
      pulse("bus");
      toast(`Pedido ${data.orderId} aceito. Processamento automático via EventBridge…`);
      state.selectedOrder = data.orderId;
    }
    refresh();
  });

  // ------------------------------------------------------------------ transações
  $("#txForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    if (!f.orderId.value) return toast("Crie um pedido primeiro.");
    await sendTransaction({ orderId: f.orderId.value, status: f.status.value });
  });
  $("#txUnknown").onclick = () => sendTransaction({ orderId: "ORD-INEXISTENTE", status: "CAPTURED", amount: 10 });
  async function sendTransaction(body) {
    pulse("api");
    const { status, data } = await api("POST", "/transactions", body);
    const out = $("#txResult");
    out.classList.remove("hidden");
    out.textContent = `HTTP ${status}\n${JSON.stringify(data, null, 2)}`;
    if (status === 202) { pulse("bus"); toast("Evento publicado. update_transaction será acionada pela regra do EventBridge."); }
    refresh();
  }

  // ------------------------------------------------------------------ relatórios
  $("#requestReport").onclick = async () => {
    pulse("api");
    const { status, data } = await api("POST", "/reports", { period: $("#reportPeriod").value });
    if (status === 202) { pulse("bus"); toast(data.message); } else toast(`Erro: ${JSON.stringify(data)}`);
    setTimeout(refresh, 800);
  };
  $("#runSchedule").onclick = async () => {
    pulse("scheduler");
    const data = await local("/local/scheduler/run", "POST");
    toast(data.message);
    setTimeout(refresh, 800);
  };
  async function downloadReport(key) {
    const res = await fetch(`${state.apiBase.replace(/\/$/, "")}/reports/download?key=${encodeURIComponent(key)}`);
    const blob = new Blob([await res.text()], { type: "text/csv;charset=utf-8" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: key.split("/").pop() });
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ------------------------------------------------------------------ renderização
  function renderOrders(orders) {
    const body = $("#ordersBody");
    if (!orders.length) {
      body.innerHTML = '<tr><td colspan="6" class="muted">Nenhum pedido ainda.</td></tr>';
    } else {
      body.innerHTML = orders.map((o) => `
        <tr data-id="${esc(o.orderId)}" class="${o.orderId === state.selectedOrder ? "selected" : ""}">
          <td><strong>${esc(o.orderId)}</strong></td>
          <td>${esc(o.customer?.name)}</td>
          <td>${money(o.total)}</td>
          <td><span class="status s-${esc(o.status)}">${esc(o.status)}</span></td>
          <td>${esc(o.paymentStatus)}</td>
          <td>${time(o.createdAt)}</td>
        </tr>`).join("");
      body.querySelectorAll("tr[data-id]").forEach((tr) => (tr.onclick = () => { state.selectedOrder = tr.dataset.id; refresh(); }));
    }
    const select = $("#txOrder");
    const current = select.value;
    select.innerHTML = orders.map((o) => `<option value="${esc(o.orderId)}">${esc(o.orderId)} · ${esc(o.status)} · ${money(o.total)}</option>`).join("");
    if (current && orders.some((o) => o.orderId === current)) select.value = current;
    else if (state.selectedOrder) select.value = state.selectedOrder;
  }

  async function renderDetail() {
    const box = $("#orderDetail");
    if (!state.selectedOrder) return box.classList.add("hidden");
    const { status, data } = await api("GET", `/orders/${encodeURIComponent(state.selectedOrder)}`);
    if (status !== 200) return box.classList.add("hidden");
    box.classList.remove("hidden");
    const tx = Object.values(data.transactions || {});
    box.innerHTML = `
      <h3>${esc(data.orderId)} <span class="status s-${esc(data.status)}">${esc(data.status)}</span></h3>
      <div class="muted small">correlationId: ${esc(data.correlationId)} · ${data.items.length} item(ns) · ${money(data.total)} · ${esc(data.paymentMethod)}</div>
      ${data.decisionReasons?.length ? `<p class="small" style="color:var(--err)">${data.decisionReasons.map(esc).join("<br>")}</p>` : ""}
      <ul class="steps">${data.history.map((h) => `
        <li><span class="muted">${time(h.at)}</span>
            <span><span class="status s-${esc(h.status)}">${esc(h.status)}</span></span>
            <span><span class="tag ${h.automatic ? "tag-auto" : "tag-api"}">${h.automatic ? "AUTOMÁTICO" : "REQUISIÇÃO"}</span>
              <strong>${esc(h.actor)}</strong> via ${esc(h.trigger)} — ${esc(h.note)}</span></li>`).join("")}
      </ul>
      ${tx.length ? `<div class="small muted" style="margin-top:8px">Transações: ${tx.map((t) => `${esc(t.transactionId)} (${esc(t.status)})`).join(", ")}</div>` : ""}`;
  }

  function renderAutomations(items) {
    const key = items[0] ? items[0].sk : null;
    if (key && key !== state.lastAutomationKey && state.lastAutomationKey) {
      items.filter((i) => i.sk > state.lastAutomationKey).forEach((i) => pulse(i.function === "lambda-async-runtime (simulado)" ? "bus" : i.function));
      if (items.some((i) => i.sk > state.lastAutomationKey && i.trigger === "EventBridge Scheduler")) pulse("scheduler");
    }
    state.lastAutomationKey = key;
    $("#automations").innerHTML = items.length ? items.map((i) => `
      <li>
        <span class="time">${time(i.timestamp)}</span>
        <div>
          <div class="title">
            <span class="tag ${i.automatic ? "tag-auto" : "tag-api"}">${i.automatic ? "AUTOMÁTICO" : "REQUISIÇÃO"}</span>
            <span class="tag tag-trigger">${esc(i.trigger)}</span>
            λ ${esc(i.function)}
            <span class="tag tag-${esc(i.status)}">${esc(i.status)}</span>
            <span class="muted small">${esc(i.eventType)}${i.durationMs ? ` · ${i.durationMs} ms` : ""}</span>
          </div>
          <div class="summary">${esc(i.summary)}</div>
          ${i.details?.message && i.details?.team ? `<div class="msg"><strong>SNS → equipe ${esc(i.details.team)}</strong> · ${esc(i.details.subject)}\n${esc(i.details.message)}</div>` : ""}
        </div>
      </li>`).join("") : '<li class="muted">Nenhuma execução registrada ainda.</li>';
  }

  function renderReports(reports) {
    $("#reports").innerHTML = reports.length ? reports.map((r) => `
      <li><a href="#" data-key="${esc(r.key)}">${esc(r.key.replace("reports/", ""))}</a>
          <span class="muted small">${r.size} B · ${time(r.lastModified)}</span></li>`).join("")
      : '<li class="muted">Nenhum relatório gerado ainda.</li>';
    $("#reports").querySelectorAll("a[data-key]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); downloadReport(a.dataset.key); }));
  }

  function renderLocal(status, events, dlq) {
    const sch = status.scheduler;
    const s = sch.schedules[0] || {};
    const next = sch.nextRunAt ? Math.max(0, Math.round((new Date(sch.nextRunAt) - Date.now()) / 1000)) : null;
    $("#schedulerInfo").innerHTML = `
      <strong>⏰ ${esc(s.name)}</strong> → λ ${esc(s.target)}<br>
      Na AWS: <code>${esc(s.awsExpression)}</code> (${esc(s.timezone)}) — EventBridge Scheduler<br>
      Simulação local: a cada <strong>${sch.localIntervalSeconds}s</strong>${next !== null ? ` · próxima execução em <strong>${next}s</strong>` : ""}
      · execuções: ${sch.runs}`;
    $("#events").innerHTML = events.length ? events.slice(0, 30).map((e) => `
      <li><strong>${esc(e.detailType)}</strong> <span class="muted small">${esc(e.source)} · ${time(e.timestamp)}</span>
        <div class="rules">${e.matchedRules.length ? e.matchedRules.map((m) => `regra ${esc(m.rule)} → λ ${esc(m.target)}`).join("<br>") : "nenhuma regra correspondente"}</div></li>`).join("")
      : '<li class="muted">Nenhum evento publicado ainda.</li>';
    $("#dlqCount").textContent = dlq.length;
    $("#dlq").innerHTML = dlq.length ? dlq.map((d) => `
      <li><strong>${esc(d.function)}</strong> <span class="muted small">${time(d.timestamp)} · ${d.attempts} tentativas</span>
        <div class="rules">${esc(d.error)}</div></li>`).join("") : '<li class="muted">Vazia.</li>';
  }

  // ------------------------------------------------------------------ ciclo de atualização
  async function refresh() {
    try {
      const [orders, automations, reports] = await Promise.all([
        api("GET", "/orders?limit=30"), api("GET", "/automations?limit=60"), api("GET", "/reports"),
      ]);
      renderOrders(orders.data.orders || []);
      renderAutomations(automations.data.automations || []);
      renderReports(reports.data.reports || []);
      await renderDetail();
      if (state.local) {
        const [status, events, dlq] = await Promise.all([local("/local/status"), local("/local/events"), local("/local/dead-letters")]);
        renderLocal(status, events.events, dlq.deadLetters);
      }
    } catch (err) {
      $("#envBadge").textContent = "API indisponível";
      $("#envBadge").className = "badge badge-muted";
    }
  }

  async function init() {
    applyPreset("ok");
    $("#addItem").onclick = () => addItem();
    document.querySelectorAll("[data-preset]").forEach((b) => (b.onclick = () => applyPreset(b.dataset.preset)));
    $("#settingsBtn").onclick = () => { $("#apiUrlInput").value = state.apiBase; $("#settingsDialog").showModal(); };
    $("#saveApiUrl").onclick = () => {
      const v = $("#apiUrlInput").value.trim();
      if (v) localStorage.setItem("techcommerce.apiUrl", v); else localStorage.removeItem("techcommerce.apiUrl");
      location.reload();
    };
    const health = await api("GET", "/health").catch(() => null);
    const badge = $("#envBadge");
    if (health && health.status === 200) {
      const isLocal = health.data.mode === "local-simulation";
      state.local = isLocal && state.apiBase.startsWith("/");
      badge.textContent = isLocal ? "LOCAL · SIMULADO" : `AWS · ${health.data.region} · ${health.data.environment}`;
      badge.className = `badge ${isLocal ? "badge-local" : "badge-aws"}`;
      $("#simBanner").classList.toggle("hidden", !isLocal);
      $("#localPanels").classList.toggle("hidden", !state.local);
      $("#runSchedule").classList.toggle("hidden", !state.local);
      if (!state.local) {
        $("#schedulerInfo").innerHTML = "⏰ O relatório é gerado automaticamente pelo <strong>EventBridge Scheduler</strong> conforme o parâmetro <code>ReportScheduleExpression</code> do stack. Use o botão abaixo para geração sob demanda.";
      }
    } else {
      badge.textContent = "API não configurada";
      toast("Configure a URL da API no botão ⚙ API.");
    }
    refresh();
    setInterval(refresh, 2500);
  }

  init();
})();
