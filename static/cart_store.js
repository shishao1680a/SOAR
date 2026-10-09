/* Shared across catalogue and product pages. Store only purchase fields. */
window.SoarCart = (() => {
  const KEY = 'soar-cart-v1';
  const fields = ['id','cart_key','name','price','image_url','variant_name','color_name','qty'];
  function clean(items) {
    if (!Array.isArray(items)) return [];
    return items.filter(x => x && typeof x.id === 'string' && Number.isInteger(x.qty) && x.qty > 0 && x.qty <= 999 && Number.isFinite(Number(x.price)) && Number(x.price) >= 0)
      .slice(0,200).map(x => Object.fromEntries(fields.map(k => [k, x[k] ?? (k === 'variant_name' || k === 'color_name' ? '' : undefined)])));
  }
  function load() { try { return clean(JSON.parse(localStorage.getItem(KEY) || '[]')); } catch(e) { return []; } }
  function save(items) { try { localStorage.setItem(KEY, JSON.stringify(clean(items))); return true; } catch(e) { return false; } }
  function key(id, variant='', color='') { return JSON.stringify([id,variant,color]); }
  return {load,save,key};
})();
