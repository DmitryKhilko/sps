document.addEventListener("click", function (e) {
  const card = e.target.closest(".grid.cards li");
  if (!card) return;
  if (e.target.closest("a")) return;       // клик по самой ссылке обрабатывается как обычно
  const link = card.querySelector("a[href]");
  if (link) link.click();
});