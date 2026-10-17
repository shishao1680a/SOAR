'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => Number(value).toLocaleString('zh-TW', {minimumFractionDigits: 0, maximumFractionDigits: 2});
  const number = n => String(n).padStart(3, '0');
  const labels = {OPEN:'開放取號',PAUSED:'暫停取號，既有預約照常服務',ENDED:'場次已結束',WAITING:'等候中',CALLED:'已到號，請至現場報到',CHECKED_IN:'已報到',CANCELLED:'已取消',NO_SHOW:'未到場',PENDING:'待發送',ACCEPTED:'LINE 已接受（未確認送達）',FAILED:'發送失敗',SKIPPED:'預約已結束，未發送'};
  let sceneId = new URLSearchParams(location.search).get('scene') || '';
  let state = null, admin = null, cart = [], products = [], key = crypto.randomUUID(), loading = false;
  let messageDirty = false, messageScene = '';
  const notifyKeys = new Map();
  function feedback(message, error = false) { $('feedback').hidden = !message; $('feedback').textContent = message; $('feedback').classList.toggle('error', error); }
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Reservation-CSRF':state?.csrf || ''},body:JSON.stringify(body)});
    const json = await response.json();
    if (!response.ok || json.status !== 'success') throw new Error(json.message || '服務暫時無法使用');
    return json;
  }
  async function action(button, fn) {
    button.disabled = true;
    try { await fn(); } catch (e) { feedback(e.message, true); }
    finally { button.disabled = false; await refresh(); }
  }
  function selectedProduct(id) { return products.find(p => p.id === id); }
  function variants(p) { try { return typeof p.items_json === 'string' ? JSON.parse(p.items_json) : p.items_json || []; } catch { return []; } }
  function renderProducts() {
    const signature = JSON.stringify(products.map(p => [p.id,p.name,p.price,p.description,p.items_json,p.image_url,p.stock_qty]));
    if ($('products').dataset.signature === signature) return;
    $('products').dataset.signature = signature;
    $('products').innerHTML = products.map((p, i) => `<article class="product">${p.image_url ? `<img src="${esc(p.image_url)}" alt="" loading="lazy">` : ''}<h3>${esc(p.name)}</h3><p>${esc(p.description || '')}</p><p class="price">NT$ ${money(p.price)} · ${p.stock_qty>0?`可售 ${p.stock_qty} 件`:'售罄'}</p>${variants(p).length ? `<label>${esc(p.variant_label || '款式')}<select data-variant="${i}"><option value="">請選擇</option>${variants(p).map((v,j)=>`<option value="${j}" ${Math.min(p.stock_qty,v.stock_qty)<=0?'disabled':''}>${esc(v.name)} · NT$ ${money(v.price ?? p.price)} · ${Math.min(p.stock_qty,v.stock_qty)>0?`可售 ${Math.min(p.stock_qty,v.stock_qty)} 件`:'售罄'}</option>`).join('')}</select></label>` : ''}<label data-color-wrap="${i}" hidden>${esc(p.color_label || '顏色')}<select data-color="${i}"></select></label><label>數量<input type="number" min="1" max="999" step="1" value="1" data-qty="${i}"></label><button data-add="${i}" ${p.stock_qty<=0?'disabled':''}>${p.stock_qty<=0?'售罄':'加入預約清單'}</button></article>`).join('') || '<p>目前沒有開放現場製作的商品。</p>';
  }
  function renderCart() {
    $('cart').innerHTML = cart.map((it,i) => `<div class="cart-item"><span>${esc(it.name)} ${esc(it.variant_name)} ${esc(it.variant_color)} ×${it.qty}<br>NT$ ${money(Number(it.price)*it.qty)}</span><button data-remove="${i}" aria-label="移除 ${esc(it.name)}">移除</button></div>`).join('') + (cart.length ? `<p><b>預估合計 NT$ ${money(cart.reduce((sum,it)=>sum+Number(it.price)*it.qty,0))}</b><br><small>正式金額會在取號時依商品價格計算。</small></p>` : '<p class="muted">請先加入要預約的商品。</p>');
  }
  function ticketHtml(t, management) {
    const items = t.items.map(it=>`<li>${esc(it.name)} ${esc(it.variant_name)} ${esc(it.variant_color)} ×${it.qty} · NT$ ${money(it.price)}</li>`).join('');
    const calls=t.notifications.filter(n=>n.kind==='CALLED');
    const latest=calls.at(-1);
    const notificationSummary=management?`<p>累計通知 ${calls.length} 次${latest?' · 最近通知：'+esc(labels[latest.status]):''}</p>`:'';
    const notifications = t.notifications.map(n=>`<small>${n.kind==='BOOKED'?'取號通知':'到號通知'}：${esc(labels[n.status] || n.status)}${n.last_error?' · '+esc(n.last_error):''}${management && ['PENDING','FAILED'].includes(n.status) ? ` <button data-retry="${esc(n.id)}">重試通知</button>`:''}</small>`).join('');
    let buttons = '';
    if (['WAITING','CALLED','NO_SHOW'].includes(t.status)) buttons += `<button data-ticket="${esc(t.id)}" data-command="cancel" data-management="${management}">取消預約</button>`;
    if (management && ['WAITING','CALLED','NO_SHOW'].includes(t.status)) buttons += `<button class="primary" data-ticket="${esc(t.id)}" data-command="notify" data-management="true">通知到場</button>`;
    if (management && ['CALLED','NO_SHOW'].includes(t.status)) buttons += `<button class="primary" data-ticket="${esc(t.id)}" data-command="check-in" data-management="true">已報到／建立訂單</button>${t.status==='CALLED'?`<button data-ticket="${esc(t.id)}" data-command="no-show" data-management="true">標記未到</button>`:''}`;
    return `<article class="ticket"><strong>${number(t.number)}</strong> · ${esc(t.name)}<p>${esc(labels[t.status])}</p><ul>${items}</ul><p>合計 NT$ ${money(t.total_amount)}${t.order_id?` · 訂單 ${esc(t.order_id)}`:''}</p>${notificationSummary}${notifications}<p class="muted">預約成功即扣庫存，取消預約才釋放。</p><div class="actions">${buttons}</div></article>`;
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      state = await api('/api/reservations/state' + (sceneId?'?scene='+encodeURIComponent(sceneId):''));
      if (!sceneId && state.scene) { sceneId=state.scene.id; history.replaceState(null,'','?scene='+sceneId); }
      const s=state.scene;
      $('scene-name').textContent=s?.name || '現場商品預約';
      $('current-number').textContent=s?.current_number == null?'—':number(s.current_number);
      $('scene-status').textContent=s?labels[s.status]+(s.current_number==null?' · 尚未叫號':''):'目前沒有開放場次';
      $('refresh-status').textContent='每 5 秒更新 · '+new Date().toLocaleTimeString('zh-TW');
      $('login-panel').hidden=!s || s.status==='ENDED' || Boolean(state.identity?.friend);
      $('booking-panel').hidden=!s || s.status==='ENDED' || !state.identity?.friend;
      $('mine-panel').hidden=!state.identity || !s;
      $('admin-panel').hidden=!state.is_admin;
      if (state.identity && !$('guest-name').value) $('guest-name').value=state.identity.name;
      products=state.products; renderProducts(); renderCart();
      let waiting=false;
      if (state.identity && s) {
        const mine=await api('/api/reservations/mine?scene='+encodeURIComponent(sceneId));
        waiting=mine.tickets.some(t=>t.status==='WAITING');
        $('my-tickets').innerHTML=mine.tickets.map(t=>ticketHtml(t,false)).join('') || '<p>尚未取號。</p>';
      }
      $('reserve-button').disabled=!s || s.status!=='OPEN' || waiting;
      $('reserve-button').textContent=waiting?'已有等候中預約，叫號或取消後可再取號':'確認預約並取號';
      if (state.is_admin) await renderAdmin();
    } catch(e) { $('refresh-status').textContent='更新失敗，畫面可能不是最新資料'; feedback(e.message,true); }
    finally { loading=false; }
  }
  async function renderAdmin() {
    admin=await api('/api/admin/reservations'+(sceneId?'?scene='+encodeURIComponent(sceneId):''));
    $('scene-select').innerHTML='<option value="">選擇場次</option>'+admin.scenes.map(s=>`<option value="${esc(s.id)}" ${s.id===sceneId?'selected':''}>${esc(s.name)} · ${esc(labels[s.status])}</option>`).join('');
    const s=admin.scene;
    $('scene-controls').hidden=!s;
    if(s) {
      const active=s.status!=='ENDED';
      $('pause-scene').disabled=!active; $('end-scene').disabled=!active; $('save-message').disabled=!active;
      $('pause-scene').textContent=s.status==='PAUSED'?'恢復取號':'暫停取號';
      if(messageScene!==s.id){ messageDirty=false; messageScene=s.id; }
      if(!messageDirty) $('call-message').value=s.call_message;
      $('scene-qr').src='/api/admin/reservations/sessions/'+s.id+'/qr.svg';
      const url=location.origin+'/reservations?scene='+encodeURIComponent(s.id);
      $('scene-link').href=url; $('scene-link').textContent=url;
      $('admin-tickets').innerHTML=admin.tickets.map(t=>ticketHtml(t,true)).join('') || '<p>目前沒有預約。</p>';
    }
    const all=await api('/api/admin/products');
    // 後台既有 API 使用 data 包裝。
    const list=all.data || [];
    $('admin-products').innerHTML=list.map(p=>`<label><input type="checkbox" data-flag="${esc(p.id)}" ${p.onsite_enabled?'checked':''}>${esc(p.name)} · NT$ ${money(p.price)}（現場製作）</label>`).join('') || '<p>請先至商品管理新增商品。</p>';
  }
  $('products').addEventListener('change',e=>{
    if(!e.target.matches('[data-variant]'))return;
    const i=Number(e.target.dataset.variant), v=variants(products[i])[e.target.value], colors=v?.colors || [];
    const wrap=document.querySelector(`[data-color-wrap="${i}"]`), sel=document.querySelector(`[data-color="${i}"]`);
    wrap.hidden=!colors.length; sel.innerHTML='<option value="">請選擇</option>'+colors.map(c=>`<option value="${esc(c.name)}" ${c.stock_qty<=0?'disabled':''}>${esc(c.name)} · ${c.stock_qty>0?`可售 ${c.stock_qty} 件`:'售罄'}</option>`).join('');
  });
  $('products').addEventListener('click',e=>{
    const button=e.target.closest('[data-add]'); if(!button)return;
    const i=Number(button.dataset.add),p=products[i],vs=variants(p),sel=document.querySelector(`[data-variant="${i}"]`),v=sel?vs[sel.value]:null;
    const color=document.querySelector(`[data-color="${i}"]`).value,qty=Number(document.querySelector(`[data-qty="${i}"]`).value);
    if(vs.length&&!v)return feedback('請先選擇商品款式',true);
    if(v?.colors?.length&&!color)return feedback('請先選擇顏色',true);
    if(!Number.isInteger(qty)||qty<1||qty>999)return feedback('數量請輸入 1～999 的整數',true);
    const available=Math.min(p.stock_qty,v?.stock_qty??p.stock_qty,color?(v.colors.find(c=>c.name===color)?.stock_qty??0):p.stock_qty);
    const inCart=cart.filter(it=>it.id===p.id && it.variant_name===(v?.name||'') && it.variant_color===color).reduce((n,it)=>n+it.qty,0);
    if(qty+inCart>available)return feedback(`可售庫存剩餘 ${available} 件，請減少數量`,true);
    cart.push({id:p.id,name:p.name,price:v?.price??p.price,qty,variant_name:v?.name||'',variant_color:color});renderCart();feedback('已加入預約清單');
  });
  $('cart').addEventListener('click',e=>{const b=e.target.closest('[data-remove]');if(b){cart.splice(Number(b.dataset.remove),1);renderCart();}});
  $('login-button').onclick=e=>action(e.target,async()=>{const r=await api('/api/reservations/login?scene='+encodeURIComponent(sceneId));location.assign(r.url);});
  $('reserve-button').onclick=e=>action(e.target,async()=>{
    if(!cart.length)throw new Error('請先加入商品');
    const name=$('guest-name').value.trim();if(!name)throw new Error('請填寫姓名');
    const r=await api('/api/reservations',{session_id:sceneId,name,items:cart,request_key:key});
    key=crypto.randomUUID();cart=[];feedback('您的預約號碼是 '+number(r.ticket.number)+'，請留意叫號。');
  });
  $('create-scene').onclick=e=>action(e.target,async()=>{const r=await api('/api/admin/reservations/sessions',{name:$('new-scene-name').value});sceneId=r.scene.id;history.replaceState(null,'','?scene='+sceneId);feedback('已開放新場次');});
  $('scene-select').onchange=e=>{sceneId=e.target.value;location.assign('/reservations'+(sceneId?'?scene='+encodeURIComponent(sceneId):''));};
  $('pause-scene').onclick=e=>action(e.target,async()=>{await api('/api/admin/reservations/sessions/'+sceneId+'/'+(admin.scene.status==='PAUSED'?'resume':'pause'),{});});
  $('end-scene').onclick=e=>action(e.target,async()=>{const count=admin.tickets.filter(t=>['WAITING','CALLED','NO_SHOW'].includes(t.status)).length;if(confirm(`結束場次將取消 ${count} 筆未報到預約並釋放庫存，保留所有紀錄。確定結束？`))await api('/api/admin/reservations/sessions/'+sceneId+'/end',{confirmed:true});});
  $('call-message').addEventListener('input',()=>{messageDirty=true;});
  $('save-message').onclick=e=>action(e.target,async()=>{await api('/api/admin/reservations/sessions/'+sceneId+'/message',{message:$('call-message').value});messageDirty=false;feedback('已儲存通知文字');});
  $('admin-products').addEventListener('change',e=>{const el=e.target;if(el.matches('[data-flag]'))action(el,async()=>{await api('/api/admin/reservations/products/'+encodeURIComponent(el.dataset.flag),{enabled:el.checked});});});
  document.addEventListener('click',e=>{
    const b=e.target.closest('[data-ticket],[data-retry]');if(!b)return;
    action(b,async()=>{
      if(b.dataset.retry){await api('/api/admin/reservations/notifications/'+b.dataset.retry+'/retry',{});return;}
      const cmd=b.dataset.command;
      if(cmd==='cancel'&&!confirm('確定取消這張預約？取消後會釋放庫存，重新取號須重新排隊。'))return;
      if(cmd==='check-in'&&!confirm('確認客人已到場？成功後會建立訂單，承接預約時已扣的庫存。'))return;
      const path=b.dataset.management==='true'?'/api/admin/reservations/tickets/'+b.dataset.ticket+'/'+cmd:'/api/reservations/'+b.dataset.ticket+'/cancel';
      const body={session_id:sceneId};
      if(cmd==='notify'){
        if(!notifyKeys.has(b.dataset.ticket))notifyKeys.set(b.dataset.ticket,crypto.randomUUID());
        body.request_key=notifyKeys.get(b.dataset.ticket);
      }
      const r=await api(path,body);
      if(cmd==='notify')notifyKeys.delete(b.dataset.ticket);
      feedback(cmd==='check-in'?'報到成功，已建立訂單 '+r.ticket.order_id:cmd==='notify'?'已通知到場，請查看通知結果':'預約狀態已更新');
    });
  });
  refresh();setInterval(()=>{if(!document.hidden)refresh();},5000);
})();
