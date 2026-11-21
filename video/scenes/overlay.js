// Camada de apresentação injetada na interface durante a gravação (cursor, destaques e aviso de simulação).
// Fica fora do <body> para não ser afetada pelo zoom aplicado à interface; usa coordenadas da viewport.
(() => {
  if (window.__demo) return;
  const root = document.createElement("div");
  root.id = "__demo";
  root.innerHTML = `
  <style>
    #__demo { font-family: "Segoe UI", Arial, sans-serif; }
    #__demo .cur { position: fixed; left: 1500px; top: 760px; width: 34px; height: 34px; z-index: 100003; pointer-events: none;
      filter: drop-shadow(0 4px 6px rgba(0,0,0,.45)); transition-property: left, top; transition-timing-function: cubic-bezier(.45,.05,.25,1); }
    #__demo .rip { position: fixed; width: 18px; height: 18px; margin: -9px 0 0 -9px; border-radius: 50%; z-index: 100002; pointer-events: none;
      border: 3px solid #ff9900; animation: rip .6s ease-out forwards; }
    @keyframes rip { from { transform: scale(.4); opacity: 1; } to { transform: scale(3.2); opacity: 0; } }
    #__demo .spot { position: fixed; z-index: 100000; pointer-events: none; border-radius: 14px; border: 4px solid #ff9900;
      box-shadow: 0 0 0 9999px rgba(10,16,30,.50), 0 0 30px rgba(255,153,0,.8); opacity: 0;
      transition: opacity .35s, left .5s, top .5s, width .5s, height .5s; }
    #__demo .spot.on { opacity: 1; }
    #__demo .lbl { position: fixed; z-index: 100001; pointer-events: none; max-width: 640px; padding: 12px 18px; border-radius: 12px;
      background: #ff9900; color: #1a1205; font-size: 25px; font-weight: 700; line-height: 1.25; box-shadow: 0 10px 26px rgba(0,0,0,.35);
      opacity: 0; transform: translateY(8px); transition: opacity .35s, transform .35s; }
    #__demo .lbl.on { opacity: 1; transform: none; }
    #__demo .sim { position: fixed; left: 24px; bottom: 22px; z-index: 100004; pointer-events: none; padding: 10px 18px; border-radius: 99px;
      background: rgba(17,24,39,.92); color: #fff; font-size: 20px; box-shadow: 0 8px 22px rgba(0,0,0,.35); }
    #__demo .sim b { color: #ffb84d; }
    #__demo .modal { position: fixed; inset: 0; z-index: 100005; display: grid; place-items: center; background: rgba(10,16,30,.6);
      opacity: 0; transition: opacity .4s; pointer-events: none; }
    #__demo .modal.on { opacity: 1; }
    #__demo .sheet { width: 980px; background: #fff; color: #1b2433; border-radius: 18px; overflow: hidden; box-shadow: 0 30px 80px rgba(0,0,0,.5); }
    #__demo .sheet h4 { margin: 0; padding: 18px 24px; background: #1f2d3d; color: #fff; font-size: 24px; font-weight: 700; }
    #__demo .sheet h4 small { display: block; font-size: 17px; font-weight: 400; opacity: .75; margin-top: 2px; }
    #__demo table { width: 100%; border-collapse: collapse; font-size: 22px; }
    #__demo td { padding: 8px 24px; border-bottom: 1px solid #e6eaf0; font-family: Consolas, monospace; }
    #__demo td:last-child { text-align: right; font-weight: 700; }
    #__demo tr.hl td { background: #fff1db; }
    #__demo tr.hl td:first-child { box-shadow: inset 6px 0 0 #ff9900; }
  </style>
  <svg class="cur" viewBox="0 0 24 24"><path d="M4 2l16 10-7 1.5L9.5 21z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>
  <div class="spot"></div><div class="lbl"></div>
  <div class="sim"><b>Ambiente local simulado</b> · mesmo código das funções Lambda · não é a conta AWS</div>
  <div class="modal"><div class="sheet"><h4></h4><table></table></div></div>`;
  document.documentElement.appendChild(root);
  const cur = root.querySelector(".cur"), spot = root.querySelector(".spot"), lbl = root.querySelector(".lbl");
  const modal = root.querySelector(".modal");
  let pos = { x: 1500, y: 760 };

  window.__demo = {
    move(x, y, ms) {
      cur.style.transitionDuration = ms + "ms";
      cur.style.left = x - 6 + "px"; cur.style.top = y - 4 + "px"; pos = { x, y };
    },
    click() {
      const r = document.createElement("div"); r.className = "rip";
      r.style.left = pos.x + "px"; r.style.top = pos.y + "px"; root.appendChild(r);
      setTimeout(() => r.remove(), 700);
    },
    spot(rect, text, where = "bottom") {
      const pad = 10, x = rect.x - pad, y = rect.y - pad, w = rect.width + 2 * pad, h = rect.height + 2 * pad;
      Object.assign(spot.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
      spot.classList.add("on");
      if (!text) { lbl.classList.remove("on"); return; }
      lbl.textContent = text; lbl.classList.add("on");
      const lw = Math.min(640, lbl.offsetWidth), lh = lbl.offsetHeight, vw = innerWidth, vh = innerHeight;
      let lx = x, ly = y + h + 14;
      if (where === "top") ly = y - lh - 14;
      if (where === "left") { lx = x - lw - 18; ly = y; }
      if (where === "right") { lx = x + w + 18; ly = y; }
      lx = Math.max(16, Math.min(vw - lw - 16, lx)); ly = Math.max(16, Math.min(vh - lh - 70, ly));
      lbl.style.left = lx + "px"; lbl.style.top = ly + "px";
    },
    unspot() { spot.classList.remove("on"); lbl.classList.remove("on"); },
    csv(title, subtitle, text) {
      const rows = text.replace(/^\uFEFF/, "").trim().split(/\r?\n/).map((l) => l.split(","));
      modal.querySelector("h4").innerHTML = `${title}<small>${subtitle}</small>`;
      modal.querySelector("table").innerHTML = rows.slice(1).map((r) =>
        `<tr data-k="${r[0]}"><td>${r[0]}</td><td>${r.slice(1).join(",")}</td></tr>`).join("");
      modal.classList.add("on");
    },
    csvMark(keys) { modal.querySelectorAll("tr").forEach((tr) => tr.classList.toggle("hl", keys.includes(tr.dataset.k))); },
    csvHide() { modal.classList.remove("on"); },
  };
})();
