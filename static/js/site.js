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
    const status = document.querySelector('[data-loyalty-status]');
    const selectedReward = status?.dataset.selectedReward || '';
    let timer;
    const loadLoyalty = async () => {
      rewardSelect.innerHTML = '<option value="">No reward selected</option>';
      if (phone.value.trim().length < 5) {
        if (status) status.textContent = 'Enter your phone number to check progress and available rewards.';
        return;
      }
      if (status) status.textContent = 'Checking loyalty progress…';
      try {
        const response = await fetch('/loyalty/options/?phone=' + encodeURIComponent(phone.value.trim()));
        if (!response.ok) throw new Error('Loyalty lookup failed');
        const data = await response.json();
        for (const reward of data.rewards || []) {
          for (const variant of reward.variants) {
            const option = document.createElement('option');
            option.value = variant.id;
            option.textContent = `${reward.category}: ${variant.label}`;
            rewardSelect.appendChild(option);
          }
        }
        if (selectedReward && [...rewardSelect.options].some((option) => option.value === selectedReward)) {
          rewardSelect.value = selectedReward;
        }
        if (status) {
          const summaries = (data.progress || []).map((entry) => {
            const rewards = `${entry.available} reward${entry.available === 1 ? '' : 's'} available`;
            return `${entry.category}: ${entry.towards_next} of 10 qualifying items · ${rewards}`;
          });
          status.textContent = summaries.length ? summaries.join(' | ') : 'No paid qualifying items in the categories currently in your bag.';
        }
      } catch (_) {
        if (status) status.textContent = 'Loyalty progress could not be checked. You can still place the order.';
      }
    };
    phone.addEventListener('input', () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(loadLoyalty, 450);
    });
    loadLoyalty();
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
  const checkoutForm = document.querySelector('#checkout-form');
  const summary = document.querySelector('[data-checkout-summary]');
  if (checkoutForm && summary) {
    const promoInput = checkoutForm.querySelector('#id_promo_code');
    const applyPromo = checkoutForm.querySelector('[data-apply-promo]');
    const feedback = checkoutForm.querySelector('[data-promo-feedback]');
    const discountRow = summary.querySelector('[data-discount-row]');
    const discountDisplay = summary.querySelector('[data-discount]');
    const deliveryDisplay = summary.querySelector('[data-delivery]');
    const deliveryZone = summary.querySelector('[data-delivery-zone]');
    const totalDisplay = summary.querySelector('[data-total]');
    const toCents = (value) => Math.round(Number(value || 0) * 100);
    const format = (cents) => `Rs ${new Intl.NumberFormat('en-NP', { maximumFractionDigits: 2 }).format(cents / 100)}`;
    const subtotal = toCents(summary.dataset.subtotal);
    let discount = 0;
    let appliedCode = '';
    const updateSummary = () => {
      const zone = checkoutForm.querySelector('input[name="delivery_zone"]:checked')?.value === 'outside' ? 'outside' : 'inside';
      const charge = toCents(zone === 'outside' ? summary.dataset.outsideCharge : summary.dataset.insideCharge);
      deliveryZone.textContent = `${zone} valley`;
      deliveryDisplay.textContent = format(charge);
      discountDisplay.textContent = `−${format(discount)}`;
      discountRow.hidden = discount === 0;
      totalDisplay.textContent = format(subtotal - discount + charge);
    };
    checkoutForm.querySelectorAll('input[name="delivery_zone"]').forEach((input) => input.addEventListener('change', updateSummary));
    promoInput.addEventListener('input', () => {
      if (promoInput.value.trim().toUpperCase() !== appliedCode) {
        discount = 0;
        appliedCode = '';
        feedback.textContent = 'Enter a code and select Apply to preview the discount.';
        updateSummary();
      }
    });
    applyPromo.addEventListener('click', async () => {
      const code = promoInput.value.trim();
      if (!code) {
        feedback.textContent = 'Enter a promo code first.';
        return;
      }
      applyPromo.disabled = true;
      feedback.textContent = 'Checking promo code…';
      try {
        const response = await fetch(applyPromo.dataset.promoUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': checkoutForm.querySelector('[name="csrfmiddlewaretoken"]').value },
          body: new URLSearchParams({ code }),
        });
        const result = await response.json();
        if (!response.ok || !result.valid) throw new Error(result.reason || 'This promo code is unavailable.');
        discount = toCents(result.discount);
        appliedCode = result.code;
        promoInput.value = result.code;
        feedback.textContent = `${result.code} applied.`;
      } catch (error) {
        discount = 0;
        appliedCode = '';
        feedback.textContent = error.message || 'Could not check the promo code.';
      } finally {
        applyPromo.disabled = false;
        updateSummary();
      }
    });
    updateSummary();
  }
});
