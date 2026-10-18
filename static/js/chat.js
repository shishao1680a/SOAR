(() => {
  const $ = id => document.getElementById(id);
  const state = {threads: [], current: null, lastId: 0, sending: false};

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function say(text, kind) {
    const el = $('status');
    el.textContent = text || '';
    el.className = 'status' + (kind ? ' ' + kind : '');
    if (text) setTimeout(() => { if (el.textContent === text) { el.textContent = ''; el.className = 'status'; } }, 5000);
  }

  async function api(url, opts) {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.message || ('HTTP ' + res.status));
    return data;
  }

  async function loadThreads() {
    try {
      const data = await api('/api/admin/chat/threads');
      state.threads = data.data || [];
      $('unread-total').hidden = !data.unread;
      $('unread-total').textContent = data.unread || '';
      renderThreads();
    } catch (e) {
      $('thread-list').innerHTML = `<p class="empty">讀取失敗：${esc(e.message)}</p>`;
    }
  }

  function renderThreads() {
    const box = $('thread-list');
    if (!state.threads.length) {
      box.innerHTML = '<p class="empty">目前沒有對話。<br>客人在 LINE 傳訊息給你時，會出現在這裡。</p>';
      return;
    }
    box.innerHTML = state.threads.map(t => `
      <div class="thread ${t.line_user_id === state.current ? 'active' : ''}" data-id="${esc(t.line_user_id)}">
        <div class="avatar">${esc((t.name || '?').slice(0, 1))}</div>
        <div class="thread-main">
          <div class="thread-top">
            <span class="thread-name">${esc(t.name)}${t.member ? '' : ' <span class="meta">未綁定</span>'}</span>
            <span class="thread-time">${esc((t.last_at || '').slice(5))}</span>
          </div>
          <div class="thread-last">${t.last_direction === 'OUT' ? '你：' : ''}${esc(t.last || '（沒有訊息）')}
            ${t.unread ? `<span class="badge">${t.unread}</span>` : ''}</div>
        </div>
      </div>`).join('');
  }

  $('thread-list').addEventListener('click', e => {
    const item = e.target.closest('[data-id]');
    if (item) openThread(item.dataset.id);
  });

  async function openThread(id) {
    state.current = id;
    state.lastId = 0;
    $('messages').innerHTML = '';
    $('chat-empty').hidden = true;
    $('chat-body').hidden = false;
    document.querySelector('.shell').classList.add('open');
    const t = state.threads.find(x => x.line_user_id === id);
    $('chat-name').textContent = t ? t.name : id;
    $('chat-sub').textContent = t && t.member ? '已綁定會員' : '未綁定會員';
    renderThreads();
    await Promise.all([loadMessages(), markRead(id)]);
    $('text').focus();
  }

  async function markRead(id) {
    try {
      const data = await api('/api/admin/chat/' + encodeURIComponent(id) + '/read', {method: 'POST'});
      $('unread-total').hidden = !data.unread;
      $('unread-total').textContent = data.unread || '';
      const t = state.threads.find(x => x.line_user_id === id);
      if (t) t.unread = 0;
      renderThreads();
    } catch (e) {}
  }

  async function loadMessages() {
    if (!state.current) return;
    try {
      const data = await api('/api/admin/chat/' + encodeURIComponent(state.current) +
        '/messages?after_id=' + state.lastId);
      for (const m of data.data || []) {
        appendMessage(m);
        state.lastId = Math.max(state.lastId, Number(m.id));
      }
    } catch (e) {
      say('訊息讀取失敗：' + e.message, 'error');
    }
  }

  function appendMessage(m, scroll = true) {
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + (m.direction === 'IN' ? 'in' : 'out');
    wrap.dataset.id = m.id;
    const body = m.kind === 'image' && m.image_url
      ? `<img class="shot" src="${esc(m.image_url)}" alt="圖片" loading="lazy" onclick="window.open(this.src)">`
      : `<div class="bubble">${esc(m.body)}</div>`;
    const fail = m.direction === 'OUT' && m.status === 'FAILED'
      ? `<div class="failed">未送出：${esc(m.error || '未知原因')}
           <button type="button" data-retry="${m.id}">重試</button></div>` : '';
    wrap.innerHTML = body + `<div class="meta">${esc((m.created_at || '').slice(5))}${m.direction === 'OUT' && m.admin_name ? ' · ' + esc(m.admin_name) : ''}</div>` + fail;
    $('messages').appendChild(wrap);
    if (scroll) $('messages').scrollTop = $('messages').scrollHeight;
  }

  $('messages').addEventListener('click', async e => {
    const btn = e.target.closest('[data-retry]');
    if (!btn) return;
    btn.disabled = true;
    try {
      const data = await api('/api/admin/chat/messages/' + btn.dataset.retry + '/retry', {method: 'POST'});
      const bubble = document.querySelector(`[data-id="${btn.dataset.retry}"]`);
      if (bubble) bubble.remove();
      appendMessage(data.message);
      say(data.ok ? '已重新送出' : ('重試失敗：' + data.error), data.ok ? 'ok' : 'error');
    } catch (err) {
      say('重試失敗：' + err.message, 'error');
      btn.disabled = false;
    }
  });

  async function sendText() {
    const text = $('text').value.trim();
    if (!text || !state.current || state.sending) return;
    state.sending = true;
    $('send').disabled = true;
    try {
      const data = await api('/api/admin/chat/' + encodeURIComponent(state.current) + '/send',
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})});
      $('text').value = '';
      appendMessage(data.message);
      say(data.ok ? '已送出' : ('未送出：' + data.error), data.ok ? 'ok' : 'error');
      loadThreads();
    } catch (e) {
      say('送出失敗：' + e.message, 'error');
    } finally {
      state.sending = false;
      $('send').disabled = false;
    }
  }

  async function sendImage(file) {
    if (!file || !state.current || state.sending) return;
    state.sending = true;
    $('send').disabled = true;
    say('圖片上傳中…');
    try {
      const form = new FormData();
      form.append('image', file);
      const data = await api('/api/admin/chat/' + encodeURIComponent(state.current) + '/send-image',
        {method: 'POST', body: form});
      appendMessage(data.message);
      say(data.ok ? '圖片已送出' : ('圖片未送出：' + data.error), data.ok ? 'ok' : 'error');
      loadThreads();
    } catch (e) {
      say('圖片送出失敗：' + e.message, 'error');
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
  $('back-list').addEventListener('click', () => {
    document.querySelector('.shell').classList.remove('open');
  });

  loadThreads();
  setInterval(loadThreads, 8000);
  setInterval(() => { if (state.current) loadMessages(); }, 4000);
})();
