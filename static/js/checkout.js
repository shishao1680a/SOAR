(() => {
  const $ = id => document.getElementById(id);
  let cart = SoarCart.load();
  let sending = false;

  const money = n => 'NT$ ' + Number(n || 0).toLocaleString('zh-TW', {maximumFractionDigits: 0});
  const feeFor = subtotal => subtotal >= 500 ? 0 : 50;
  const method = () => document.querySelector('input[name="ship"]:checked').value;

  function renderItems() {
    const list = $('items');
    if (!cart.length) {
      list.innerHTML = '<li><span>購物車是空的，請先回商品大廳挑選。</span></li>';
      $('submit').disabled = true;
      $('subtotal').textContent = money(0);
      $('fee').textContent = money(0);
      $('total').textContent = money(0);
      return;
    }
    $('submit').disabled = false;
    list.innerHTML = cart.map(it => {
      const variant = [it.variant_name, it.color_name].filter(Boolean).join(' / ');
      const showVariant = variant && !String(it.name || '').includes(String(it.variant_name || ''));
      return `<li><span>${esc(it.name)}${showVariant ? `<br><span class="meta">${esc(variant)}</span>` : ''}</span>` +
        `<span>×${it.qty}　${money(Number(it.price) * it.qty)}</span></li>`;
    }).join('');
    const subtotal = cart.reduce((sum, it) => sum + Number(it.price) * it.qty, 0);
    const fee = feeFor(subtotal);
    $('subtotal').textContent = money(subtotal);
    $('fee').textContent = fee ? money(fee) : '免運';
    $('total').textContent = money(subtotal + fee);
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function refreshMethod() {
    const seven = method() === 'SEVEN';
    $('store-wrap').hidden = !seven;
    $('address-label').textContent = seven ? '7-11 門市地址' : '收件地址';
    $('address').placeholder = seven ? '請填寫門市地址' : '請填寫收件地址';
  }

  function say(text, kind) {
    const el = $('msg');
    el.textContent = text || '';
    el.className = 'msg' + (kind ? ' ' + kind : '');
  }

  function validate() {
    const recipient = $('recipient').value.trim();
    const phone = $('phone').value.trim();
    const address = $('address').value.trim();
    const store = $('store').value.trim();
    if (!recipient) return '請填寫收件者姓名';
    if (!/^[0-9+\-\s()]{6,30}$/.test(phone)) return '請填寫有效的手機或電話';
    if (method() === 'SEVEN' && !store) return '請填寫 7-11 門市名稱';
    if (!address) return method() === 'SEVEN' ? '請填寫門市地址' : '請填寫收件地址';
    return '';
  }

  $('submit').addEventListener('click', async () => {
    if (sending) return;
    if (!cart.length) return say('購物車是空的', 'error');
    const problem = validate();
    if (problem) return say(problem, 'error');
    sending = true;
    $('submit').disabled = true;
    say('正在送出訂單…');
    try {
      const res = await fetch('/api/orders', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          cart,
          shipping: {
            recipient: $('recipient').value.trim(),
            phone: $('phone').value.trim(),
            method: method(),
            address: $('address').value.trim(),
            store: method() === 'SEVEN' ? $('store').value.trim() : '',
          },
        }),
      });
      if (res.status === 401) {
        location.href = '/login/line?next=/checkout';
        return;
      }
      const data = await res.json();
      if (data.status === 'success') {
        SoarCart.save([]);
        location.href = '/orders?new=' + encodeURIComponent(data.order_id);
        return;
      }
      say(data.message || '訂單送出失敗，請稍後重試', 'error');
    } catch (e) {
      say('連線失敗，購物車已保留，請稍後重試', 'error');
    } finally {
      sending = false;
      $('submit').disabled = !cart.length;
    }
  });

  document.querySelectorAll('input[name="ship"]').forEach(r => r.addEventListener('change', refreshMethod));
  refreshMethod();
  renderItems();
})();
