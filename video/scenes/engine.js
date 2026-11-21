// Linha do tempo das cenas: elementos com data-at="s" recebem a classe "in" e data-out="s" a classe "out".
// O gravador chama window.__start() logo após iniciar a captura, garantindo sincronia com o roteiro.
(() => {
  const actions = [];
  window.at = (t, fn) => actions.push({ t, fn });
  window.$ = (s, root = document) => root.querySelector(s);
  window.$$ = (s, root = document) => [...root.querySelectorAll(s)];

  window.__ready = async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map((img) =>
      img.complete ? null : new Promise((r) => { img.onload = img.onerror = r; })));
    return true;
  };

  window.__start = () => {
    $$("[data-at]").forEach((el) => at(parseFloat(el.dataset.at), () => el.classList.add("in")));
    $$("[data-out]").forEach((el) => at(parseFloat(el.dataset.out), () => el.classList.add("out")));
    actions.sort((a, b) => a.t - b.t);
    const t0 = performance.now();
    let i = 0;
    document.body.classList.add("play");
    const tick = () => {
      const t = (performance.now() - t0) / 1000;
      while (i < actions.length && actions[i].t <= t) {
        try { actions[i].fn(); } catch (err) { console.error(err); }
        i += 1;
      }
      if (i < actions.length) requestAnimationFrame(tick);
    };
    tick();
  };

  // Pré-visualização manual: abrir a cena com ?play no navegador.
  if (location.search.includes("play")) window.addEventListener("load", () => __ready().then(__start));
})();
