// Подсказки при наведении для ячеек теплокарты и полосок: data-tip="...".
(function () {
  const tip = document.createElement("div");
  tip.className = "tip";
  document.body.appendChild(tip);
  document.addEventListener("pointermove", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el) { tip.style.opacity = 0; return; }
    tip.textContent = el.dataset.tip;
    const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px";
    tip.style.top = (e.clientY + 16) + "px";
    tip.style.opacity = 1;
  });
  // Встречная цена: поле цены показывается только при выборе «своя цена».
  document.querySelectorAll("[data-counter-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const box = document.getElementById(btn.dataset.counterToggle);
      box.hidden = !box.hidden;
      if (!box.hidden) box.querySelector("input").focus();
    });
  });
})();
