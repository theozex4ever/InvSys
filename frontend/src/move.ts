import { pair, esc, message } from './presentation';
import { read, RequestError, type ready, type MoveRequest, type MovePreview, type StockContext } from './bridge';

type API = Awaited<ReturnType<typeof ready>>;

// Move a Lot between Locations. Self-contained so sibling stock workflows can copy the lifecycle:
// drafts live in the hidden section, availability is re-read on return, one request at a time,
// and an ambiguous mutation locks the form until the operator reconciles it against audit records.
export function moveWorkflow(getAPI: () => API, operator: () => string, changed: () => Promise<void>, toast: (text: string, summary?: string) => void) {
  const state = { pending: false, uncertain: false, reconciled: false, version: 0, context: null as StockContext | null, submitted: null as MoveRequest | null, before: 0 };
  let preview: MovePreview | null = null;
  let previewVersion = 0;
  let active = false;
  const control = <T extends HTMLElement>(name: string) => document.querySelector<T>(`#move-${name}`)!;
  const value = (name: string) => control<HTMLInputElement | HTMLSelectElement>(name).value;
  const dialog = () => document.querySelector<HTMLDialogElement>('#move-confirmation')!;
  const field = (name: string, label: string, kind: 'select' | 'number' | 'text', full = false) => `<div class="field ${full ? 'full' : ''}"><label for="move-${name}">${label}${name === 'reference' ? '' : ' <span class="required">*</span>'}</label>${kind === 'select' ? `<select id="move-${name}" name="${name}" required><option value="">Select…</option></select>` : `<input id="move-${name}" name="${name}" ${name === 'reference' ? '' : 'required'} ${kind === 'number' ? 'type="number" min="1" max="2147483647" step="1"' : ''}>`}</div>`;
  const feedback = (text: string, error = false) => {
    const element = control<HTMLElement>('error');
    element.textContent = text; element.className = error ? 'status error' : 'status';
  };

  document.querySelector('main')!.insertAdjacentHTML('beforeend', `<section id="move" hidden><div class="page-heading"><div><h1>Move stock</h1><p>Transfer a lot between locations. Both movement records post together.</p></div><button class="btn" id="move-refresh" disabled>Refresh availability</button></div><div id="move-result" role="status" aria-live="polite"></div><div class="stock-layout"><form id="move-form" class="panel panel-body"><h2>Select inventory</h2><div class="form-grid">${field('part_number', 'Part', 'select', true)}${field('location', 'From', 'select')}${field('destination', 'To', 'select')}${field('lot_number', 'Lot', 'select', true)}${field('quantity', 'Quantity', 'number')}${field('reference', 'Reference', 'text')}</div><p class="help">Operator identity comes from the visible header. Enter your name before submitting.</p><div id="move-error" role="alert" aria-live="polite"></div><button id="move-submit" class="btn primary" disabled>Review move</button></form><div class="panel"><div class="panel-head"><h2>Current stock and review</h2></div><div id="move-review" class="panel-body">Select a part to read current inventory.</div><div id="move-recovery" class="panel-body" hidden></div></div></div></section>`);
  document.querySelector('#app')!.insertAdjacentHTML('afterend', `<dialog id="move-confirmation" aria-labelledby="move-confirm-title"><div class="dialog-heading"><h2 id="move-confirm-title">Confirm move</h2><button id="move-cancel" class="btn">Cancel</button></div><div id="move-confirm-data" class="dialog-body"></div><div class="panel-body"><button id="move-confirm-submit" class="btn primary">Confirm move</button></div></dialog>`);

  const form = control<HTMLFormElement>('form');
  form.addEventListener('submit', event => { event.preventDefault(); void review(); });
  const edited = () => { preview = null; renderReview(); };
  form.addEventListener('input', edited); form.addEventListener('change', edited);
  control<HTMLSelectElement>('part_number').addEventListener('change', () => { control<HTMLInputElement>('lot_number').value = ''; void refresh(true); });
  control<HTMLSelectElement>('location').addEventListener('change', () => { renderLots(); renderReview(); });
  control<HTMLButtonElement>('refresh').onclick = () => { void refresh(); };
  document.querySelector<HTMLButtonElement>('#move-cancel')!.onclick = () => dialog().close();
  dialog().addEventListener('cancel', event => { if (state.pending) event.preventDefault(); });
  dialog().addEventListener('close', () => {
    preview = null;
    (state.uncertain ? control<HTMLElement>('recovery').querySelector<HTMLButtonElement>('[data-recovery=read]') : control<HTMLButtonElement>('submit'))?.focus();
  });
  document.querySelector<HTMLButtonElement>('#move-confirm-submit')!.onclick = () => { void confirm(); };
  control<HTMLElement>('recovery').onclick = event => {
    const action = (event.target as HTMLElement).closest<HTMLButtonElement>('button')?.dataset.recovery;
    if (action === 'read') void reconcile();
    if (!state.reconciled || (action !== 'completed' && action !== 'absent')) return;
    state.uncertain = false; state.reconciled = false;
    control<HTMLElement>('recovery').hidden = true;
    feedback(action === 'completed' ? 'Completion verified. Start another entry when ready.' : 'You verified no matching move. Review the preserved draft before submitting.');
    if (action === 'completed') {
      const submitted = state.submitted!; const context = state.context!;
      const text = `Verified move of ${submitted.quantity} × ${submitted.part_number}, lot ${submitted.lot_number}, from ${submitted.location} to ${submitted.destination}. Current stock — ${submitted.location}: ${context.part.location_balances[submitted.location] ?? 0}; ${submitted.destination}: ${context.part.location_balances[submitted.destination] ?? 0}.`;
      control<HTMLElement>('result').innerHTML = `<div class="status success">${esc(text)}</div>`;
      clearEntry(); toast(text, `Move completion verified for ${submitted.part_number}.`);
    }
    renderLots(); lock(); void changed();
  };

  function lock() {
    const blocked = state.pending || state.uncertain;
    form.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select').forEach(element => { element.disabled = blocked; });
    control<HTMLButtonElement>('submit').disabled = blocked || !state.context || !state.context.part.active;
    control<HTMLButtonElement>('refresh').disabled = state.pending;
  }
  function renderLots() {
    const select = control<HTMLSelectElement>('lot_number'); const saved = select.value;
    // Only positive-stock lots at the source can be moved.
    const lots = state.context?.part.balances.filter(b => b.location === value('location') && b.quantity > 0) ?? [];
    select.innerHTML = '<option value="">Select an available lot…</option>' + lots.map(b => `<option value="${esc(b.lot_number)}">${esc(b.lot_number)} · ${b.quantity} available</option>`).join('');
    if (saved && !lots.some(b => b.lot_number === saved)) select.insertAdjacentHTML('beforeend', `<option value="${esc(saved)}">${esc(saved)} · unavailable</option>`);
    select.value = saved;
  }
  function impact(title: string, rows: [string, number][]) {
    return `<div class="stock-impact"><div class="review-title">${esc(title)}</div>${rows.map(([label, quantity]) => `<div class="review-row"><span>${esc(label)}</span><strong>${quantity}</strong></div>`).join('')}</div>`;
  }
  function renderReview() {
    const context = state.context;
    const source = value('location'), destination = value('destination'), lot = value('lot_number');
    const stockAt = (location: string) => context?.part.balances.find(b => b.location === location && b.lot_number === lot)?.quantity ?? 0;
    control<HTMLElement>('review').innerHTML = context ? `<div class="review-part">${esc(context.part.part_number)}</div><p class="description help">${esc(context.part.description)}</p>${pair('From', source || 'Select a location')}${pair('To', destination || 'Select a location')}${pair('Selected lot', lot || 'Select a lot')}${lot ? pair(`Lot stock at ${source}`, stockAt(source)) + pair(`Lot stock at ${destination || 'destination'}`, destination ? stockAt(destination) : '—') : ''}${pair('Total stock at source', context.part.location_balances[source] ?? 0)}${pair('Total stock at destination', context.part.location_balances[destination] ?? 0)}${pair('Quantity requested', value('quantity') || 'Enter quantity')}${pair('Operator', operator() || 'Name required in header')}<p class="help">Review move reads current stock and shows the exact before and after quantities for both locations. Python validates current stock at submission.</p>${!context.part.active ? '<div class="status error">This part is inactive. Use the original application to reactivate it.</div>' : ''}` : 'Select a part to read current inventory.';
  }
  async function refresh(adoptLocation = false) {
    if (state.pending || state.uncertain) return;
    const version = ++state.version; preview = null;
    state.context = null; lock();
    control<HTMLElement>('review').textContent = 'Reading current stock…';
    try {
      const api = getAPI();
      const [parts, locations] = await Promise.all([read(api.search_parts({ query: '', status: 'all', low_stock: false, sort: 'part_number', descending: false })), read(api.locations())]);
      if (version !== state.version) return;
      const part = value('part_number'); const partSelect = control<HTMLSelectElement>('part_number');
      partSelect.innerHTML = '<option value="">Select a part…</option>' + parts.map(p => `<option value="${esc(p.part_number)}">${esc(p.part_number)} · ${esc(p.description)}${p.active ? '' : ' (inactive)'}</option>`).join('');
      if (part && !parts.some(p => p.part_number === part)) partSelect.insertAdjacentHTML('beforeend', `<option value="${esc(part)}">${esc(part)} · unavailable</option>`);
      partSelect.value = part;
      const [source, destination] = [value('location'), value('destination')];
      const options = locations.map(l => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
      control<HTMLSelectElement>('location').innerHTML = options; control<HTMLSelectElement>('destination').innerHTML = options;
      // Initial defaults only; a kept draft selection wins while the Location still exists.
      control<HTMLSelectElement>('location').value = locations.includes(source) ? source : locations.includes('Stock') ? 'Stock' : locations[0] ?? '';
      control<HTMLSelectElement>('destination').value = locations.includes(destination) ? destination : locations.find(l => l === 'Shipping Bench') ?? locations.find(l => l !== value('location')) ?? '';
      if (part) {
        const context = await read(api.stock_context(part));
        if (version !== state.version) return;
        state.context = context;
        if (adoptLocation) {
          const source = control<HTMLSelectElement>('location'); source.value = context.part.location;
          const target = control<HTMLSelectElement>('destination');
          if (target.value === source.value) target.value = locations.find(l => l !== source.value) ?? '';
        }
      }
      renderLots(); renderReview(); lock();
    } catch (error) {
      if (version !== state.version) return;
      state.context = null; feedback(`${message(error)} Use Refresh availability to try again.`, true); lock();
      control<HTMLElement>('review').textContent = 'Current availability is unavailable.';
    }
  }
  function request(): MoveRequest {
    if (!operator().trim()) throw new Error('Enter your operator name in the header before submitting.');
    return { part_number: value('part_number'), quantity: Number(value('quantity')), location: value('location'), destination: value('destination'), lot_number: value('lot_number'), operator: operator(), reference: value('reference') };
  }
  function clearEntry() {
    // Selection stays so the next transfer of the same Part is quick.
    for (const name of ['quantity', 'reference']) control<HTMLInputElement>(name).value = '';
    preview = null; renderReview();
  }
  function ambiguous(error: unknown) {
    state.uncertain = error instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(error.code);
    feedback(message(error) + (state.uncertain ? ' Completion is uncertain. Do not repeat this entry. Read current audit records below and verify whether it completed.' : ''), true);
    if (!state.uncertain) return;
    const submitted = state.submitted!;
    const recovery = control<HTMLElement>('recovery'); recovery.hidden = false;
    recovery.innerHTML = `<h3>Verify uncertain move</h3>${pair('Submitted part', submitted.part_number)}${pair('Lot', submitted.lot_number)}${pair('From → To', `${submitted.location} → ${submitted.destination}`)}${pair('Quantity / operator', `${submitted.quantity} / ${submitted.operator}`)}${pair('Reference', submitted.reference || '—')}<button class="btn" data-recovery="read">Read current stock and audit</button><div class="recovery-records"></div>`;
  }
  async function review() {
    if (state.pending || state.uncertain || !state.context) return;
    let fields: MoveRequest;
    try { fields = request(); } catch (error) { feedback(message(error), true); return; }
    state.pending = true; const version = ++state.version; const reviewVersion = previewVersion; lock(); feedback('Reading move review…');
    try {
      const result = await read(getAPI().preview_move(fields));
      if (version !== state.version || reviewVersion !== previewVersion || !active) return;
      state.context = result.context; preview = result;
      const r = result.request;
      document.querySelector('#move-confirm-data')!.innerHTML = pair('Part', r.part_number) + pair('Lot', r.lot_number) + pair('Quantity', r.quantity) + impact(`Source · ${r.location}`, [['Lot before', result.source_lot_before], ['Lot after', result.source_lot_after], ['Location total before', result.source_location_before], ['Location total after', result.source_location_after]]) + impact(`Destination · ${r.destination}`, [['Lot before', result.destination_lot_before], ['Lot after', result.destination_lot_after], ['Location total before', result.destination_location_before], ['Location total after', result.destination_location_after]]) + pair('Operator', r.operator) + pair('Reference', r.reference || '—') + '<p class="help">Confirmation records a MOVE_OUT and a MOVE_IN together. Python rechecks available stock at submission.</p>';
      feedback('Current move review is ready. Confirm or cancel.'); dialog().showModal();
    } catch (error) {
      if (version !== state.version || reviewVersion !== previewVersion) return;
      feedback(`${message(error)} No stock submission was sent.`, true);
    } finally {
      state.pending = false; lock(); renderReview();
      // The operator left and returned during the review; return-time refresh was skipped while pending.
      if (version !== state.version && active) void refresh();
    }
  }
  async function confirm() {
    if (state.pending || state.uncertain || !preview) return;
    if (operator().trim() !== preview.request.operator) {
      dialog().close(); feedback('Operator changed. Review the move again.', true); return;
    }
    const fields = { ...preview.request };
    state.before = preview.context.transactions.length; state.submitted = fields;
    state.pending = true; ++state.version; lock();
    document.querySelector<HTMLButtonElement>('#move-confirm-submit')!.disabled = true;
    document.querySelector<HTMLButtonElement>('#move-cancel')!.disabled = true;
    let rejected = false;
    try {
      const context = await read(getAPI().move(fields)); state.context = context;
      const text = `Moved ${fields.quantity} × ${fields.part_number}, lot ${fields.lot_number}, from ${fields.location} to ${fields.destination}. Current stock — ${fields.location}: ${context.part.location_balances[fields.location] ?? 0}; ${fields.destination}: ${context.part.location_balances[fields.destination] ?? 0}.`;
      control<HTMLElement>('result').innerHTML = `<div class="status success">${esc(text)}</div>`;
      clearEntry(); feedback('Ready for the next move.'); toast(text, `Moved ${fields.quantity} × ${fields.part_number} to ${fields.destination}.`); void changed();
    } catch (error) {
      ambiguous(error); rejected = !state.uncertain;
    } finally {
      state.pending = false; dialog().close(); lock(); renderLots(); renderReview();
      document.querySelector<HTMLButtonElement>('#move-confirm-submit')!.disabled = false;
      document.querySelector<HTMLButtonElement>('#move-cancel')!.disabled = false;
    }
    // A rejected move wrote nothing; re-read so the operator sees why (for example stale stock).
    if (rejected && active) void refresh();
  }
  async function reconcile() {
    if (!state.uncertain || state.pending || !state.submitted) return;
    state.pending = true; state.reconciled = false;
    const records = control<HTMLElement>('recovery').querySelector<HTMLElement>('.recovery-records')!;
    records.textContent = 'Reading authoritative stock and audit…'; lock();
    try {
      const context = await read(getAPI().stock_context(state.submitted.part_number)); state.context = context;
      const submitted = state.submitted;
      const recent = context.transactions.slice(0, Math.max(0, context.transactions.length - state.before));
      records.innerHTML = `${pair(`Current total stock at ${submitted.location}`, context.part.location_balances[submitted.location] ?? 0)}${pair(`Current total stock at ${submitted.destination}`, context.part.location_balances[submitted.destination] ?? 0)}<h3>Audit records added since review</h3>${recent.length ? recent.map(tx => `<div class="status">${esc(tx.timestamp)} · ${esc(tx.tx_type)} · ${tx.quantity_change} · ${esc(tx.lot_number)} · ${esc(tx.location_from)} → ${esc(tx.location_to)} · ${esc(tx.operator)} · ${esc(tx.reference)}</div>`).join('') : '<p>No new audit records were found.</p>'}<p class="help">Other operators may also have recorded stock. Compare the submitted entry with the records; stock totals alone cannot prove completion. No request is retried automatically.</p><button class="btn" data-recovery="completed">I verified completion</button> <button class="btn" data-recovery="absent">I verified it did not complete — unlock draft</button>`;
      state.reconciled = true; renderReview();
    } catch (error) { records.textContent = `${message(error)} Completion remains uncertain. Read again before taking action.`; }
    finally { state.pending = false; lock(); }
  }
  return {
    async open(number?: string) {
      active = true;
      if (dialog().open && !state.pending) dialog().close();
      preview = null;
      if (state.pending) { ++state.version; return; }
      if (state.uncertain) return;
      if (number && value('part_number') !== number) {
        const select = control<HTMLSelectElement>('part_number');
        if (!Array.from(select.options).some(o => o.value === number)) select.insertAdjacentHTML('beforeend', `<option value="${esc(number)}">${esc(number)}</option>`);
        select.value = number; control<HTMLSelectElement>('lot_number').value = '';
      }
      await refresh(!!number);
    },
    leave() { active = false; ++state.version; preview = null; if (dialog().open && !state.pending) dialog().close(); },
    operatorChanged() { ++previewVersion; preview = null; if (dialog().open && !state.pending) dialog().close(); renderReview(); },
  };
}
