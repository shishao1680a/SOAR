(() => {
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  let page = Math.max(1, Number(params.get('page')) || 1);
  let current = null;
  let last5For = null;

  const money = n => 'NT$ ' + Number(n || 0).toLocaleString('zh-TW', {maximumFractionDigits: 0});
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function chipClass(o) {
    if (o.status === 'CANCELLED') return 'cancelled';
    if (o.status === 'SHIPPED' || o.status === 'COMPLETED') return 'shipped';
    if (o.payment_status === 'CONFIRMED') return 'paid';
    if (o.payment_status === 'REPORTED') return 'reported';
    return 'wait';
  }

  function card(o) {
    const items = (o.items || []).map(it => {
      const variant = [it.variant_name, it.variant_color].filter(Boolean).join(' / ');
      const showVariant = variant && !String(it.name || '').includes(String(it.variant_name || ''));
      return `<li><span>${esc(it.name)}${showVariant ? `<br><span class="meta">${esc(variant)}</span>` : ''}</span>` +
        `<span>×${Number(it.qty || 1)}　${money(Number(it.price || 0) * Number(it.qty || 1))}</span></li>`;
    }).join('');
    const ship = o.shipping || {};
    const shipLine = o.legacy
      ? '<div class="meta" style="color:var(--muted)">舊版訂單，沒有寄送資料</div>'
      : `<div>寄送：<b>${esc(ship.label)}</b>${ship.store ? '｜' + esc(ship.store) : ''}</div>
         <div>收件人：${esc(ship.recipient || '-')}／${esc(ship.phone || '-')}</div>
         <div>地址：${esc(ship.address || '-')}</div>`;
    const remit = o.remit_last5
      ? `<div>匯款末五碼：<b>${esc(o.remit_last5)}</b>${o.remit_reported_at ? `<span class="meta">　回報時間 ${esc(o.remit_reported_at)}</span>` : ''}</div>`
      : '';
    const actions = [];
    if (o.can_report) actions.push(`<button class="btn primary" data-remit="${esc(o.id)}">${o.remit_last5 ? '修改末五碼' : '填寫匯款末五碼'}</button>`);
    if (o.can_cancel) actions.push(`<button class="btn ghost" data-cancel="${esc(o.id)}">取消訂單</button>`);
    return `<article class="order" id="order-${esc(o.id)}">
      <div class="head">
        <div><div class="oid">${esc(o.id)}</div><div class="date">${esc(o.created_at)}</div></div>
        <span class="chip ${chipClass(o)}">${esc(o.status_text)}</span>
      </div>
      <div class="body">
        <ul class="items">${items || '<li><span>（沒有商品明細）</span></li>'}</ul>
        <div class="total-row"><span>商品小計</span><span>${money(o.subtotal)}</span></div>
        <div class="total-row"><span>運費</span><span>${o.legacy ? '—' : (Number(o.shipping_fee) ? money(o.shipping_fee) : '免運')}</span></div>
        <div class="total-row grand"><span>應付金額</span><span>${money(o.amount_due)}</span></div>
        <div style="margin-top:10px">${shipLine}</div>
        ${remit}
      </div>
      ${actions.length ? `<div class="acts">${actions.join('')}</div>` : ''}
    </article>`;
  }

  async function load() {
    $('list').innerHTML = '<div class="empty">正在讀取訂單…</div>';
    try {
      const res = await fetch('/api/orders/mine?page=' + page);
      if (res.status === 401) { location.href = '/login/line?next=/orders'; return; }
      const data = await res.json();
      if (data.status !== 'success') throw new Error(data.message || '讀取失敗');
      const rows = data.data || [];
      $('list').innerHTML = rows.length
        ? rows.map(card).join('')
        : '<div class="empty">目前還沒有訂單。<br><a href="/">回商品大廳逛逛</a></div>';
      $('pager').hidden = data.pages <= 1;
      $('page-info').textContent = `第 ${data.page} / ${data.pages} 頁（共 ${data.total} 筆）`;
      $('prev').disabled = data.page <= 1;
      $('next').disabled = data.page >= data.pages;
      const newId = params.get('new');
      if (newId) {
        const target = document.getElementById('order-' + newId);
        if (target) target.scrollIntoView({behavior: 'smooth', block: 'center'});
      }
    } catch (e) {
      $('list').innerHTML = `<div class="empty">訂單讀取失敗：${esc(e.message)}</div>`;
    }
  }

  $('list').addEventListener('click', e => {
    const remit = e.target.closest('[data-remit]');
    if (remit) { openRemit(remit.dataset.remit); return; }
    const cancel = e.target.closest('[data-cancel]');
    if (cancel) cancelOrder(cancel.dataset.cancel);
  });

  function openRemit(id) {
    last5For = id;
    $('last5').value = '';
    $('remit-msg').textContent = '';
    $('remit-msg').className = 'msg';
    const cardEl = document.getElementById('order-' + id);
    const existing = cardEl && cardEl.textContent.match(/匯款末五碼：(\d{5})/);
    $('remit-hint').textContent = existing
      ? `目前填寫的是 ${existing[1]}，可以重新填寫（確認收款前都能改）。`
      : '請輸入匯款帳號的最後 5 位數字。';
    $('remit-dialog').showModal();
    $('last5').focus();
  }

  async function saveRemit() {
    const last5 = $('last5').value.trim();
    if (!/^\d{5}$/.test(last5)) {
      $('remit-msg').textContent = '請輸入 5 位數字';
      $('remit-msg').className = 'msg error';
      return;
    }
    const btn = $('remit-save');
    btn.disabled = true;
    try {
      const res = await fetch('/api/orders/' + encodeURIComponent(last5For) + '/remit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({last5}),
      });
      const data = await res.json();
      if (data.status === 'success') {
        $('remit-dialog').close();
        banner('已回報匯款末五碼，我們核對後會盡快通知你。');
        await load();
      } else {
        $('remit-msg').textContent = data.message || '送出失敗';
        $('remit-msg').className = 'msg error';
      }
    } catch (e) {
      $('remit-msg').textContent = '連線失敗，請稍後重試';
      $('remit-msg').className = 'msg error';
    } finally {
      btn.disabled = false;
    }
  }

  async function cancelOrder(id) {
    if (!confirm(`確定取消訂單 ${id}？取消後庫存會釋放。`)) return;
    try {
      const res = await fetch('/api/orders/' + encodeURIComponent(id) + '/cancel', {method: 'POST'});
      const data = await res.json();
      if (data.status === 'success') {
        banner('訂單已取消，庫存已釋放。');
        await load();
      } else {
        banner(data.message || '取消失敗', true);
      }
    } catch (e) {
      banner('連線失敗，請稍後重試', true);
    }
  }

  function banner(text, error) {
    const el = $('banner');
    el.textContent = text;
    el.hidden = false;
    el.style.borderColor = error ? '#7A4038' : '';
    el.style.color = error ? '#FFB4A6' : '';
    el.style.background = error ? '#2A1A16' : '';
  }

  $('remit-cancel').addEventListener('click', () => $('remit-dialog').close());
  $('remit-save').addEventListener('click', saveRemit);
  $('last5').addEventListener('keydown', e => { if (e.key === 'Enter') saveRemit(); });
  $('prev').addEventListener('click', () => { if (page > 1) { page--; load(); } });
  $('next').addEventListener('click', () => { page++; load(); });

  const newId = params.get('new');
  if (newId) banner(`訂單已成立！訂單編號 ${newId}。匯款完成後，請在下方填寫匯款帳號後 5 碼。`);
  load();
})();
