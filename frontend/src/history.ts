import { read, type ready, type HistoryRecord, type ShipmentDetail } from './bridge';

type API = Awaited<ReturnType<typeof ready>>;
const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const pair = (label: string, value: unknown) => `<div class="detail-pair"><span>${esc(label)}</span><strong>${esc(value || '—')}</strong></div>`;
const status = (text: string, error = false) => `<div class="status ${error ? 'error' : ''}" role="${error ? 'alert' : 'status'}">${esc(text)}</div>`;
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to read History.';

export function historyWorkflow(getAPI: () => API) {
  const search = { query: '', tx_type: '', page: 0 };
  let version = 0, detailVersion = 0, selected: number | null = null;
  let returnFocus: HTMLElement | null = null;
  let pagePosition = { x: 0, y: 0, tableX: 0 };
  let position = { x: 0, y: 0, tableX: 0 };
  const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
  $('main').insertAdjacentHTML('beforeend', `<section id="history" hidden><div class="page-heading"><div><h1>History</h1><p>Immutable inventory changes and shipment traceability.</p></div><button id="history-refresh" class="btn" disabled>Refresh</button></div><div class="panel"><div class="toolbar"><label class="search-input"><span class="sr-only">Search part, lot, operator, or shipment reference</span><input id="history-query" placeholder="Search part, lot, operator, or shipment reference"></label><label>Type <select id="history-type" class="select-input"><option value="">All types</option></select></label><button id="history-clear" class="btn small">Clear filters</button></div><div id="history-filters" class="filter-chips" role="status"></div><div id="history-data">${status('Connecting to the desktop…')}</div></div></section>`);
  $('#app').insertAdjacentHTML('afterend', `<dialog id="history-drawer" class="drawer" aria-labelledby="history-title"><div class="dialog-heading"><h2 id="history-title">History details</h2><button id="history-close" class="btn" aria-label="Close History details">Close</button></div><div id="history-detail" class="dialog-body"></div></dialog>`);
  const dialog = () => $<HTMLDialogElement>('#history-drawer');
  const remember = () => ({ x: scrollX, y: scrollY, tableX: $('#history-data .table-wrap')?.scrollLeft ?? 0 });
  const restore = (saved: typeof position) => {
    if (!$('#history').hidden) {
      window.scrollTo(saved.x, saved.y);
      const table = $('#history-data .table-wrap'); if (table) table.scrollLeft = saved.tableX;
    }
  };
  $('#history-close').onclick = () => dialog().close();
  dialog().addEventListener('close', () => {
    ++detailVersion;
    const target = returnFocus?.isConnected ? returnFocus : document.querySelector<HTMLElement>(`#history [data-history-id="${selected}"]`) ?? $('#history-refresh');
    target.focus({ preventScroll: true }); window.scrollTo(position.x, position.y); restore(position);
  });
  $<HTMLInputElement>('#history-query').addEventListener('input', event => { search.query = (event.target as HTMLInputElement).value; search.page = 0; void load(); });
  $<HTMLSelectElement>('#history-type').onchange = event => { search.tx_type = (event.target as HTMLSelectElement).value; search.page = 0; void load(); };
  $('#history-clear').onclick = () => { search.query = ''; search.tx_type = ''; search.page = 0; $<HTMLInputElement>('#history-query').value = ''; $<HTMLSelectElement>('#history-type').value = ''; void load(); };
  $('#history-refresh').onclick = () => { void load(); };
  $('#history-data').addEventListener('click', event => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-history-page]');
    if (button) { search.page = Number(button.dataset.historyPage); void load(); }
  });

  function transaction(tx: HistoryRecord) {
    return `${pair('Part', tx.part_number)}${pair('Type / quantity change', `${tx.tx_type} / ${tx.quantity_change > 0 ? '+' : ''}${tx.quantity_change}`)}${pair('From', tx.location_from)}${pair('To', tx.location_to)}${pair('Lot', tx.lot_number)}${pair('Operator', tx.operator)}${pair('Timestamp', tx.timestamp)}${pair('Reference', tx.reference)}${pair('Notes', tx.notes)}`;
  }
  function shipment(detail: ShipmentDetail) {
    return `<h3>Linked shipment ${esc(detail.shipment_number)}</h3>${pair('Parent part / shipped quantity', `${detail.part_number} / ${detail.quantity}`)}${pair('Recipient', detail.recipient)}${pair('Timestamp', detail.timestamp)}${pair('Carrier', detail.carrier)}${pair('Tracking', detail.tracking_number)}${pair('Reference', detail.reference)}<h3>Persisted component consumption</h3>${detail.consumed_components.length ? `<div class="table-wrap"><table><thead><tr><th>Material</th><th>Lot</th><th>Location</th><th class="num">Consumed</th></tr></thead><tbody>${detail.consumed_components.map(c => `<tr><td>${esc(c.part_number)}</td><td>${esc(c.lot_number)}</td><td>${esc(c.location)}</td><td class="num">${c.quantity}</td></tr>`).join('')}</tbody></table></div>` : '<p>Standard shipment — no BOM component consumption.</p>'}<h3>Shipment audit records</h3>${detail.transactions.map(tx => `<div class="status"><button class="text-link" data-history-id="${tx.transaction_id}">${esc(tx.tx_type)} · ${esc(tx.part_number)} · ${tx.quantity_change} · Lot ${esc(tx.lot_number || '—')}</button></div>`).join('')}`;
  }
  async function load(savedPosition?: typeof position) {
    const current = ++version; const saved = savedPosition ?? ($('#history').hidden ? pagePosition : remember());
    $('#history-filters').textContent = `Search: ${search.query || 'Any'} · Type: ${search.tx_type || 'All types'} · Page: ${search.page + 1}`;
    $('#history-data').innerHTML = status('Loading History…');
    try {
      const result = await read(getAPI().history({ ...search }));
      if (current !== version) return;
      const types = Array.from(new Set([...result.types, ...(search.tx_type ? [search.tx_type] : [])]));
      $('#history-type').innerHTML = '<option value="">All types</option>' + types.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');
      $<HTMLSelectElement>('#history-type').value = search.tx_type;
      $('#history-data').innerHTML = result.records.length ? `<div class="table-wrap"><table><thead><tr><th>Timestamp</th><th>Type / Part</th><th class="num">Change</th><th>Lot / Location</th><th>Operator</th><th>Reference / Shipment</th></tr></thead><tbody>${result.records.map(tx => `<tr ${selected === tx.transaction_id ? 'class="selected"' : ''}><td><button class="text-link" data-history-id="${tx.transaction_id}">${esc(tx.timestamp)}</button></td><td>${esc(tx.tx_type)}<br><strong>${esc(tx.part_number)}</strong></td><td class="num">${tx.quantity_change > 0 ? '+' : ''}${tx.quantity_change}</td><td>${esc(tx.lot_number || '—')}<br>${esc([tx.location_from, tx.location_to].filter(Boolean).join(' → '))}</td><td>${esc(tx.operator)}</td><td>${esc(tx.reference || '—')}${tx.shipment_number ? `<br><button class="text-link" data-shipment="${esc(tx.shipment_number)}">${esc(tx.shipment_number)}</button>` : ''}</td></tr>`).join('')}</tbody></table></div><div class="table-footer">${result.matching} matching records · Page ${result.page + 1}<div><button class="btn small" data-history-page="${Math.max(0, result.page - 1)}" ${result.page === 0 ? 'disabled' : ''}>Previous</button> <button class="btn small" data-history-page="${result.page + 1}" ${(result.page + 1) * 50 >= result.matching ? 'disabled' : ''}>Next</button></div></div>` : status(result.total ? 'No records match these filters. Clear filters to see all History.' : 'No inventory history yet. Receive stock to record the first change.');
      pagePosition = saved; restore(saved);
    } catch (error) { if (current === version) $('#history-data').innerHTML = status(message(error) + ' Use Refresh to try again.', true); }
  }
  async function inspect(id: number | string, origin: HTMLElement) {
    const current = ++detailVersion;
    if (!dialog().open) { returnFocus = origin; position = remember(); dialog().showModal(); }
    if (typeof id === 'number') {
      selected = id;
      document.querySelectorAll<HTMLElement>('#history tbody tr').forEach(row => row.classList.toggle('selected', !!row.querySelector(`[data-history-id="${id}"]`)));
    }
    $('#history-detail').innerHTML = status('Loading immutable record…');
    try {
      const api = getAPI();
      const html = typeof id === 'number' ? await read(api.history_detail(id)).then(d => transaction(d.transaction) + (d.shipment ? shipment(d.shipment) : '<p>No linked shipment.</p>')) : await read(api.shipment_detail(id)).then(shipment);
      if (current === detailVersion && dialog().open) { $('#history-detail').innerHTML = html; dialog().scrollTop = 0; }
    } catch (error) { if (current === detailVersion && dialog().open) $('#history-detail').innerHTML = status(message(error), true); }
  }
  return { load, inspect, open: () => load(pagePosition), leave: () => { pagePosition = remember(); } };
}
