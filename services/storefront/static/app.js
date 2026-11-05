// NeonByte storefront: cart buttons, checkout, returns and the Sparky chat widget.
const api = async (method, url, body) => {
  const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  return data;
};
const toast = (text) => {
  const t = document.createElement('div'); t.className = 'toast'; t.textContent = text;
  document.body.appendChild(t); setTimeout(() => t.remove(), 2500);
};
const setCount = (n) => { const el = document.getElementById('cart-count'); if (el) el.textContent = n; };

document.getElementById('user-switch')?.addEventListener('change', (e) => {
  location.href = `${location.pathname}?user=${encodeURIComponent(e.target.value)}`;
});

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  try {
    if (btn.classList.contains('add')) {
      const cart = await api('POST', '/api/cart/items', { product_id: btn.dataset.id, quantity: 1 });
      setCount(cart.item_count); toast('Added to cart ⚡');
    } else if (btn.classList.contains('remove')) {
      await api('DELETE', `/api/cart/items/${btn.dataset.id}`); location.reload();
    } else if (btn.classList.contains('return')) {
      await api('POST', `/api/orders/${btn.dataset.id}/return`, { reason: 'requested from order history' }); location.reload();
    }
  } catch (err) { toast(err.message); }
});

document.getElementById('checkout-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const out = document.getElementById('checkout-result');
  out.textContent = 'Placing order…';
  try {
    const order = await api('POST', '/api/checkout', {
      shipping: { name: f.get('name'), street: f.get('street'), city: f.get('city'), state: f.get('state'), zip: f.get('zip') },
      card_last4: String(f.get('card')).replace(/\D/g, '').slice(-4),
    });
    out.textContent = `✅ Order ${order.order_id} confirmed!`;
    setTimeout(() => (location.href = '/orders'), 1200);
  } catch (err) { out.textContent = `❌ ${err.message}`; }
});

// ---- Sparky chat -----------------------------------------------------------
const chat = document.getElementById('chat');
const log = document.getElementById('chat-log');
let session = sessionStorage.getItem('nb_chat_session');
if (!session) { session = crypto.randomUUID(); sessionStorage.setItem('nb_chat_session', session); }

// Show the AgentCore runtime session id (what GenAI Observability / Transaction Search index on).
const sessionEl = document.getElementById('chat-session-id');
const showSession = (id) => { sessionEl.textContent = id; sessionEl.title = id; };
const refreshSession = async () => {
  try { showSession((await api('GET', `/api/assistant/session?session=${encodeURIComponent(session)}`)).session_id); }
  catch { showSession(session); }
};
refreshSession();
document.getElementById('chat-copy').onclick = async () => {
  try { await navigator.clipboard.writeText(sessionEl.textContent); toast('Session id copied'); }
  catch { toast(sessionEl.textContent); }
};
document.getElementById('chat-new').onclick = () => {
  session = crypto.randomUUID(); sessionStorage.setItem('nb_chat_session', session);
  [...log.querySelectorAll('.msg')].slice(1).forEach((m) => m.remove());  // keep the greeting
  refreshSession(); toast('New chat session');
};

document.getElementById('chat-toggle').onclick = () => { chat.hidden = !chat.hidden; document.getElementById('chat-input').focus(); };
document.getElementById('chat-close').onclick = () => { chat.hidden = true; };

// Render the agent's light markdown safely: escape first, then bold + product links.
const render = (text) => {
  const esc = text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  return esc.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\b(NB-\d{4})\b/g, '<a href="/product/$1">$1</a>');
};
const addMsg = (cls, html) => { const m = document.createElement('div'); m.className = `msg ${cls}`; m.innerHTML = html; log.appendChild(m); log.scrollTop = log.scrollHeight; return m; };

document.getElementById('chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  addMsg('me', render(message));
  const pending = addMsg('bot typing', 'Sparky is thinking…');
  try {
    const res = await api('POST', '/api/assistant/chat', { message, session });
    pending.className = 'msg bot'; pending.innerHTML = render(res.reply || '(no reply)');
    if (res.session_id) showSession(res.session_id);
    const cart = await api('GET', '/api/cart'); setCount(cart.item_count);
  } catch (err) { pending.className = 'msg bot'; pending.textContent = `⚠️ ${err.message}`; }
});
