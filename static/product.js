(() => {
  const p=JSON.parse(document.getElementById('product-data').textContent);
  const $=id=>document.getElementById(id);
  const parse=x=>{try{return Array.isArray(x)?x:JSON.parse(x||'[]')}catch(e){return []}};
  const variants=parse(p.items_json).filter(v=>v&&typeof v==='object');
  let variant=variants[0]||null,color=null,cart=SoarCart.load(),sending=false;
  const fallback='/static/images/placeholder.svg';
  const stock=()=>Math.max(0,Number(color?.stock_qty??variant?.stock_qty??p.stock_qty)||0);
  const price=()=>Number(variant?.price??p.price)||0;
  const hasColors=()=>Array.isArray(variant?.colors)&&variant.colors.length>0;
  function image(img,url){img.onerror=()=>{img.onerror=null;img.src=fallback};img.src=url||fallback}
  function gallery(){
    const urls=[color?.image_url,variant?.image_url,p.image_url,...parse(p.images_json)].filter(x=>typeof x==='string'&&x);
    const unique=[...new Set(urls)];image($('main-image'),unique[0]);$('thumbnails').replaceChildren();
    unique.forEach(url=>{const b=document.createElement('button'),img=document.createElement('img');b.type='button';b.setAttribute('aria-label','查看商品圖片');img.alt=p.name;image(img,url);b.append(img);b.onclick=()=>image($('main-image'),url);$('thumbnails').append(b)});
  }
  function options(){
    $('variants').replaceChildren();
    variants.forEach(v=>{const b=document.createElement('button');b.type='button';b.textContent=v.name||'未命名款式';b.classList.toggle('selected',v===variant);b.setAttribute('aria-pressed',String(v===variant));b.onclick=()=>{variant=v;color=null;options();update()};$('variants').append(b)});
    $('colors').replaceChildren();
    (hasColors()?variant.colors:[]).forEach(c=>{const b=document.createElement('button');b.type='button';b.textContent=c.name||'未命名顏色';b.classList.toggle('selected',c===color);b.setAttribute('aria-pressed',String(c===color));b.onclick=()=>{color=c;options();update()};$('colors').append(b)});
  }
  function update(){
    $('price').textContent='NT$ '+price().toFixed(2);$('stock').textContent=hasColors()&&!color?'請選擇顏色':'剩餘 '+stock()+' 件';
    $('variant-description').textContent=variant?.description||'';
    $('quantity').max=String(Math.min(999,stock()));
    if(Number($('quantity').value)>stock())$('quantity').value=String(Math.max(1,Math.min(999,stock())));
    $('add-cart').disabled=stock()<=0||(hasColors()&&!color);$('add-cart').textContent=hasColors()&&!color?'請先選擇顏色':stock()>0?'加入購物車':'目前缺貨';gallery();
  }
  function persist(){if(!SoarCart.save(cart))$('message').textContent='瀏覽器無法保存購物車，請允許本機儲存後再試';renderCart()}
  $('add-cart').onclick=()=>{
    const qty=Number($('quantity').value),vname=variant?.name||'',cname=color?.name||'',key=SoarCart.key(p.id,vname,cname);
    const existing=cart.find(x=>x.cart_key===key);
    if(!Number.isInteger(qty)||qty<1||qty+(existing?.qty||0)>Math.min(999,stock())){ $('message').textContent='請輸入有效數量，購物車中的同款商品也計入庫存上限';return }
    if(hasColors()&&!color)return;
    if(existing)existing.qty+=qty;else cart.push({id:p.id,cart_key:key,name:p.name+(vname?' - '+vname:''),variant_name:vname,color_name:cname,price:price(),qty,image_url:color?.image_url||variant?.image_url||p.image_url});
    $('message').textContent='已加入購物車';persist();
  };
  function renderCart(){
    $('cart-count').textContent=cart.reduce((n,x)=>n+x.qty,0);$('cart-total').textContent='NT$ '+cart.reduce((n,x)=>n+Number(x.price)*x.qty,0).toFixed(2);$('cart-items').replaceChildren();
    if(!cart.length){$('cart-items').textContent='購物車目前沒有商品';return}
    cart.forEach(x=>{const row=document.createElement('div');row.className='cart-row';const img=document.createElement('img');img.alt=x.name;image(img,x.image_url);const body=document.createElement('div'),name=document.createElement('p'),amount=document.createElement('p'),qty=document.createElement('input'),del=document.createElement('button');name.textContent=x.name+(x.color_name?'（'+x.color_name+'）':'');amount.textContent='NT$ '+Number(x.price).toFixed(2);qty.type='number';qty.min='1';qty.max='999';qty.value=x.qty;qty.setAttribute('aria-label',x.name+'數量');qty.onchange=()=>{const n=Number(qty.value);if(!Number.isInteger(n)||n<1||n>999){qty.value=x.qty;return}x.qty=n;persist()};del.textContent='移除';del.onclick=()=>{cart=cart.filter(i=>i!==x);persist()};body.append(name,amount,qty,del);row.append(img,body);$('cart-items').append(row)});
  }
  $('cart-open').onclick=()=>{cart=SoarCart.load();renderCart();$('cart-dialog').showModal()};$('cart-close').onclick=()=>$('cart-dialog').close();
  $('checkout').onclick=async()=>{
    if(sending||!cart.length)return;sending=true;$('checkout').disabled=true;
    try{
      const u=await fetch('/api/user/current').then(r=>r.json());const user=u.status==='success'?u.user:null;
      const r=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cart,user_name:user?.name||'社團會員',user_line_id:user?.line_id||'GUEST'})});const data=await r.json();
      if(data.status==='success') {cart=[];persist();$('cart-message').textContent='訂單已送出！訂單編號：'+data.order_id} else $('cart-message').textContent=data.message||'訂單送出失敗';
    }catch(e){$('cart-message').textContent='連線失敗，購物車已保留，請稍後重試'}finally{sending=false;$('checkout').disabled=false}
  };
  document.querySelectorAll('.detail-image').forEach(img=>img.onerror=()=>{const note=document.createElement('p');note.className='broken-image';note.textContent='圖片暫時無法顯示';img.replaceWith(note)});
  window.addEventListener('storage',()=>{cart=SoarCart.load();renderCart()});options();update();renderCart();
})();
