(() => {
  "use strict";
  const body = document.body;
  const open = document.querySelector("[data-nav-open]");
  const close = document.querySelector("[data-nav-close]");
  if (open) open.addEventListener("click", () => body.classList.add("nav-open"));
  if (close) close.addEventListener("click", () => body.classList.remove("nav-open"));
  document.querySelectorAll("[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
})();
