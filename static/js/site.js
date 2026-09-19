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
  if (mainImage) {
    const frame = mainImage.closest('.product-main-image');
    frame.addEventListener('mousemove', (event) => {
      const bounds = frame.getBoundingClientRect();
      mainImage.style.transformOrigin = `${((event.clientX - bounds.left) / bounds.width) * 100}% ${((event.clientY - bounds.top) / bounds.height) * 100}%`;
    });
  }
  const optionsForm = document.querySelector('[data-product-options]');
  if (optionsForm) {
    const select = optionsForm.querySelector('#variant');
    const quantity = optionsForm.querySelector('#quantity');
    const displayPrice = document.querySelector('[data-product-display-price]');
    const addPrice = optionsForm.querySelector('[data-add-price]');
    const availability = optionsForm.querySelector('[data-variant-availability]');
    const formatter = new Intl.NumberFormat('en-NP', { maximumFractionDigits: 2 });
    const updateVariant = () => {
      const selected = select.selectedOptions[0];
      const surcharge = Number(selected?.dataset.additionalPrice || 0);
      const stock = Number(selected?.dataset.stock || 0);
      const price = `Rs ${formatter.format(Number(optionsForm.dataset.basePrice) + surcharge)}`;
      if (displayPrice) displayPrice.textContent = price;
      if (addPrice) addPrice.textContent = price;
      if (availability) availability.textContent = selected?.value ? `${stock} in stock` : 'Select an option to see availability.';
      if (quantity && selected?.value) {
        quantity.max = Math.min(stock, 99);
        if (Number(quantity.value) > stock) quantity.value = Math.min(stock, 99);
      }
    };
    select.addEventListener('change', updateVariant);
  }
});
