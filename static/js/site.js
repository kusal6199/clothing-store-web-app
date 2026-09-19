document.addEventListener('DOMContentLoaded', () => {
  const menu = document.querySelector('[data-menu-toggle]');
  const nav = document.querySelector('[data-nav]');
  if (menu && nav) menu.addEventListener('click', () => nav.classList.toggle('open'));
  const slides = [...document.querySelectorAll('.hero-slide')];
  const dots = [...document.querySelectorAll('.hero-dot')];
  let index = 0;
  const show = (next) => {
    index = next;
    slides.forEach((slide, i) => slide.classList.toggle('active', i === index));
    dots.forEach((dot, i) => dot.classList.toggle('active', i === index));
  };
  dots.forEach((dot) => dot.addEventListener('click', () => show(Number(dot.dataset.slide))));
  if (slides.length > 1) window.setInterval(() => show((index + 1) % slides.length), 6000);
  const phone = document.querySelector('#id_phone');
  const rewardSelect = document.querySelector('#id_reward_variant_id');
  if (phone && rewardSelect) {
    let timer;
    phone.addEventListener('input', () => {
      window.clearTimeout(timer);
      rewardSelect.innerHTML = '<option value="">No reward selected</option>';
      if (phone.value.trim().length < 5) return;
      timer = window.setTimeout(async () => {
        try {
          const response = await fetch('/loyalty/options/?phone=' + encodeURIComponent(phone.value.trim()));
          const data = await response.json();
          for (const reward of data.rewards || []) {
            for (const variant of reward.variants) {
              const option = document.createElement('option');
              option.value = variant.id;
              option.textContent = reward.category + ': ' + variant.label;
              rewardSelect.appendChild(option);
            }
          }
        } catch (_) { /* The order form still works without loyalty lookup. */ }
      }, 450);
    });
  }
  const mainImage = document.querySelector('#main-product-image');
  document.querySelectorAll('[data-image]').forEach((button) => button.addEventListener('click', () => {
    if (mainImage) mainImage.src = button.dataset.image;
  }));
});
