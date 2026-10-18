(() => {
  const $ = id => document.getElementById(id);
  if (!$('messages')) return;
  const state = {lastId: 0, sending: false};

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function say(text, kind) {
    const el = $('status');
    el.textContent = text || '';
    el.className = 'status' + (kind ? ' ' + kind : '');
    if (text) setTimeout(() => { if (el.textContent === text) { el.textContent = ''; el.className = 'status'; } }, 5000);
  }

  function append(m, scroll = true) {
    if (document.querySelector(`.msg[data-id="${m.id}"]`)) return;
    state.lastId = Math.max(Number(state.lastId) || 0, Number(m.id) || 0);
    const mine = m.direction === 'IN';
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + (mine ? 'mine' : 'admin');
    wrap.dataset.id = m.id;
    const body = m.kind === 'image' && m.image_src
      ? `<img class="shot" src="${esc(m.image_src)}" alt="圖片" loading="lazy" onclick="window.open(this.src)">`
      : `<div class="bubble">${esc(m.body)}</div>`;
    wrap.innerHTML = body +
      `<div class="meta">${mine ? '你' : '客服'} · ${esc((m.created_at || '').slice(5))}</div>`;
    const empty = $('messages').querySelector('.empty');
    if (empty) empty.remove();
    $('messages').appendChild(wrap);
    if (scroll) $('messages').scrollTop = $('messages').scrollHeight;
  }

  async function load() {
    try {
      const res = await fetch('/api/messages/mine?after_id=' + state.lastId);
      if (res.status === 401) { location.href = '/login/line?next=/messages'; return; }
      const data = await res.json();
      for (const m of data.data || []) append(m);
    } catch (e) {
      say('訊息讀取失敗，請稍後重新整理', 'error');
    }
  }

  async function sendText() {
    const text = $('text').value.trim();
    if (!text || state.sending) return;
    state.sending = true;
    $('send').disabled = true;
    try {
      const res = await fetch('/api/messages/mine', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text}),
      });
      if (res.status === 401) { location.href = '/login/line?next=/messages'; return; }
      const data = await res.json();
      if (data.status === 'success') {
        $('text').value = '';
        append(data.message);
        say('已送出', 'ok');
      } else {
        say(data.message || '送出失敗', 'error');
      }
    } catch (e) {
      say('連線失敗，請稍後重試', 'error');
    } finally {
      state.sending = false;
      $('send').disabled = false;
    }
  }

  async function sendImage(file) {
    if (!file || state.sending) return;
    state.sending = true;
    $('send').disabled = true;
    say('圖片上傳中…');
    try {
      const form = new FormData();
      form.append('image', file);
      const res = await fetch('/api/messages/mine/image', {method: 'POST', body: form});
      if (res.status === 401) { location.href = '/login/line?next=/messages'; return; }
      const data = await res.json();
      if (data.status === 'success') {
        append(data.message);
        say('圖片已送出（原始檔保存）', 'ok');
      } else {
        say(data.message || '圖片送出失敗', 'error');
      }
    } catch (e) {
      say('圖片送出失敗，請稍後重試', 'error');
    } finally {
      state.sending = false;
      $('send').disabled = false;
      $('image').value = '';
    }
  }

  $('send').addEventListener('click', sendText);
  $('text').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText(); }
  });
  $('image').addEventListener('change', e => sendImage(e.target.files[0]));

  load();
  setInterval(load, 5000);
})();
