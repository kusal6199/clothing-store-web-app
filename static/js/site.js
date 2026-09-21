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
  const configureRewardSelector = (root, reward, selectedVariantId = '') => {
    const hidden = root.querySelector('[name="reward_variant_id"]');
    const productSelect = root.querySelector('[data-reward-product]');
    const sizeSelect = root.querySelector('[data-reward-size]');
    const colorSelect = root.querySelector('[data-reward-color]');
    const colorNA = root.querySelector('[data-reward-color-na]');
    const help = root.querySelector('[data-reward-help]');
    const submit = root.querySelector('[data-reward-submit]');
    const summary = document.querySelector('[data-reward-summary]');
    if (!hidden || !productSelect || !sizeSelect || !colorSelect) return;
    const products = reward?.products || [];
    const resetFinalSelection = () => {
      hidden.value = '';
      if (submit) submit.disabled = true;
      if (summary) summary.hidden = true;
    };
    const setFinalSelection = (product, variant) => {
      hidden.value = variant.id;
      if (submit) submit.disabled = false;
      if (help) help.textContent = `${product.name} · ${variant.size}${variant.color ? ` · ${variant.color}` : ' · No color'} · FREE`;
      if (summary) {
        summary.hidden = false;
        summary.querySelector('[data-reward-summary-name]').textContent = product.name;
        summary.querySelector('[data-reward-summary-options]').textContent = `${variant.size}${variant.color ? `, ${variant.color}` : ' · No color'} · Quantity 1`;
      }
    };
    const productFor = (id) => products.find((product) => product.id === id);
    const fillSizes = (product) => {
      const sizes = [...new Set((product?.variants || []).map((variant) => variant.size))];
      sizeSelect.innerHTML = '<option value="">Choose a size</option>';
      sizes.forEach((size) => sizeSelect.add(new Option(size, size)));
      sizeSelect.disabled = !product;
      colorSelect.innerHTML = '<option value="">Choose a size first</option>';
      colorSelect.disabled = true;
      colorNA.hidden = true;
      resetFinalSelection();
    };
    const fillColors = (product, size) => {
      const variants = (product?.variants || []).filter((variant) => variant.size === size);
      colorSelect.innerHTML = '';
      colorSelect.required = false;
      colorNA.hidden = true;
      resetFinalSelection();
      if (!variants.length) {
        colorSelect.add(new Option('No in-stock colors', ''));
        colorSelect.disabled = true;
        return;
      }
      if (variants.every((variant) => !variant.color)) {
        colorSelect.add(new Option('Not applicable', ''));
        colorSelect.disabled = true;
        colorNA.hidden = false;
        setFinalSelection(product, variants[0]);
        return;
      }
      colorSelect.add(new Option('Choose a color', ''));
      variants.filter((variant) => variant.color).forEach((variant) => colorSelect.add(new Option(variant.color, variant.color)));
      colorSelect.disabled = false;
      colorSelect.required = true;
    };
    productSelect.innerHTML = '<option value="">Choose a free product</option>';
    products.forEach((product) => productSelect.add(new Option(product.name, product.id)));
    productSelect.onchange = () => fillSizes(productFor(productSelect.value));
    sizeSelect.onchange = () => fillColors(productFor(productSelect.value), sizeSelect.value);
    colorSelect.onchange = () => {
      const product = productFor(productSelect.value);
      const variant = product?.variants.find((item) => item.size === sizeSelect.value && item.color === colorSelect.value);
      resetFinalSelection();
      if (product && variant) setFinalSelection(product, variant);
    };
    resetFinalSelection();
    if (selectedVariantId) {
      for (const product of products) {
        const variant = product.variants.find((item) => item.id === selectedVariantId);
        if (!variant) continue;
        productSelect.value = product.id;
        fillSizes(product);
        sizeSelect.value = variant.size;
        fillColors(product, variant.size);
        if (variant.color) {
          colorSelect.value = variant.color;
          setFinalSelection(product, variant);
        }
        break;
      }
    }
  };
  const checkoutReward = document.querySelector('[data-reward-selector][data-source-url]');
  const phone = document.querySelector('#id_phone');
  if (phone && checkoutReward) {
    const status = checkoutReward.querySelector('[data-loyalty-status]');
    const panel = checkoutReward.querySelector('[data-reward-panel]');
    const title = checkoutReward.querySelector('[data-reward-title]');
    let timer;
    const loadLoyalty = async () => {
      const selectedVariant = checkoutReward.querySelector('[name="reward_variant_id"]').value || checkoutReward.dataset.selectedVariant || '';
      checkoutReward.dataset.selectedVariant = '';
      if (phone.value.trim().length < 5) {
        panel.hidden = true;
        if (status) status.textContent = 'Enter your phone number to check progress and available rewards.';
        return;
      }
      if (status) status.textContent = 'Checking loyalty progress…';
      try {
        const url = `${checkoutReward.dataset.sourceUrl}?phone=${encodeURIComponent(phone.value.trim())}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error('Loyalty lookup failed');
        const data = await response.json();
        const rewards = data.rewards || [];
        const selectedReward = rewards.find((reward) => reward.products.some((product) => product.variants.some((variant) => variant.id === selectedVariant)));
        const reward = selectedReward || rewards[0];
        panel.hidden = !reward;
        if (reward) {
          title.textContent = `You have ${reward.available} free ${reward.category} reward${reward.available === 1 ? '' : 's'} available.`;
          configureRewardSelector(checkoutReward, reward, selectedVariant);
        } else {
          checkoutReward.querySelector('[name="reward_variant_id"]').value = '';
          const summary = document.querySelector('[data-reward-summary]');
          if (summary) summary.hidden = true;
        }
        if (status) {
          const summaries = (data.progress || []).map((entry) => {
            const rewardsAvailable = `${entry.available} reward${entry.available === 1 ? '' : 's'} available`;
            return `${entry.category}: ${entry.towards_next} of 10 qualifying items · ${rewardsAvailable}`;
          });
          status.textContent = summaries.length ? summaries.join(' | ') : 'No paid qualifying items in the categories currently in your bag.';
        }
      } catch (_) {
        panel.hidden = true;
        if (status) status.textContent = 'Loyalty progress could not be checked. You can still place the order.';
      }
    };
    phone.addEventListener('input', () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(loadLoyalty, 450);
    });
    loadLoyalty();
  }
  const standaloneReward = document.querySelector('[data-reward-selector]:not([data-source-url])');
  const rewardData = document.querySelector('#reward-catalog-data');
  if (standaloneReward && rewardData) configureRewardSelector(standaloneReward, JSON.parse(rewardData.textContent));
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
