// Plain vanilla JS: no frontend build step and no external JS CDN required.
const sidebar = document.getElementById('sidebar');
const toggle = document.getElementById('menu-toggle');
if (toggle && sidebar) {
  toggle.addEventListener('click', () => {
    const opened = sidebar.classList.toggle('opened');
    toggle.setAttribute('aria-expanded', String(opened));
  });
}
const dialog = document.getElementById('restock-dialog');
if (dialog) {
  const form = document.getElementById('restock-form');
  const productName = document.getElementById('restock-product-name');
  document.querySelectorAll('[data-restock-id]').forEach((button) => {
    button.addEventListener('click', () => {
      form.reset();
      const id = button.dataset.restockId;
      form.action = '/inventory/' + encodeURIComponent(id) + '/restock';
      productName.textContent = button.dataset.productName;
      dialog.showModal();
      const quantity = form.querySelector('[name="quantity"]');
      if (quantity) quantity.focus();
    });
  });
  document.getElementById('dialog-close').addEventListener('click', () => dialog.close());
  document.getElementById('dialog-cancel').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
}

// Sales entry interactions: progressive enhancement. Server revalidates EVERYTHING.
const saleForm = document.getElementById('new-sale-form');
if (saleForm) {
  const list = document.getElementById('sale-lines');
  const template = document.getElementById('sale-line-template');
  const addButton = document.getElementById('add-sale-line');
  const amount = document.getElementById('sale-grand-total');
  const errors = document.getElementById('sale-ui-errors');
  const submitButton = document.getElementById('sale-submit');
  const money = n => 'Rp ' + new Intl.NumberFormat('id-ID').format(n);
  function refresh() {
    let total = 0;
    const seen = new Set();
    let duplicate = false;
    list.querySelectorAll('[data-sale-line]').forEach(row => {
      const sel = row.querySelector('.sale-product-select');
      const input = row.querySelector('.sale-quantity-input');
      const opt = sel.options[sel.selectedIndex];
      const stock = Number(opt?.dataset.stock || 0);
      const price = Number(opt?.dataset.price || 0);
      const qty = Number(input.value || 0);
      if (sel.value && seen.has(sel.value)) duplicate = true;
      if (sel.value) seen.add(sel.value);
      const subtotal = Number.isSafeInteger(qty) && qty > 0 ? qty * price : 0;
      row.querySelector('[data-subtotal]').textContent = money(subtotal);
      row.querySelector('.sale-stock-hint').textContent = sel.value
        ? `Stok tersedia: ${stock} unit • Harga: ${money(price)}` + (qty > stock ? ' • Stok tidak cukup!' : '')
        : 'Harga dan stok mengikuti data terbaru di server.';
      total += subtotal;
    });
    amount.textContent = money(total);
    errors.textContent = duplicate ? 'Produk yang sama tidak boleh dipilih lebih dari sekali.' : '';
    addButton.disabled = list.children.length >= 20;
  }
  addButton.addEventListener('click', () => {
    if (list.children.length >= 20) return;
    list.appendChild(template.content.firstElementChild.cloneNode(true));
    refresh();
  });
  list.addEventListener('click', event => {
    if (!event.target.closest('[data-remove-line]')) return;
    if (list.children.length <= 1) return;
    event.target.closest('[data-sale-line]').remove();
    refresh();
  });
  list.addEventListener('input', refresh);
  list.addEventListener('change', refresh);
  saleForm.addEventListener('submit', event => {
    refresh();
    if (errors.textContent) {event.preventDefault(); return;}
    submitButton.disabled = true;
    submitButton.textContent = 'Menyimpan...';
  });
  refresh();
}
