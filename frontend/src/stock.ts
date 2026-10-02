import { read, RequestError, type ready, type Receipt, type ShipmentRequest, type ShipmentPreview, type BOMPreview, type StockContext } from './bridge';

type Mode = 'receive' | 'ship';
type API = Awaited<ReturnType<typeof ready>>;
const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';
const pair = (label: string, value: unknown) => `<div class="detail-pair"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;

export function stockWorkflows(getAPI: () => API, operator: () => string, changed: () => Promise<void>, toast: (text: string) => void) {
  const states = {
    receive: { pending: false, uncertain: false, completed: false, version: 0, context: null as StockContext | null, submitted: null as Receipt | ShipmentRequest | null, before: 0, beforeShipments: 0, recoveredNumbers: [] as string[], reconciled: false },
    ship: { pending: false, uncertain: false, completed: false, version: 0, context: null as StockContext | null, submitted: null as Receipt | ShipmentRequest | null, before: 0, beforeShipments: 0, recoveredNumbers: [] as string[], reconciled: false },
  };
  let preview: ShipmentPreview | BOMPreview | null = null;
  let bomReview: BOMPreview | null = null;
  let previewVersion = 0;
  let active: Mode | null = null;
  const control = <T extends HTMLElement>(mode: Mode, name: string) => document.querySelector<T>(`#${mode}-${name}`)!;
  const form = (mode: Mode) => control<HTMLFormElement>(mode, 'form');
  const value = (mode: Mode, name: string) => control<HTMLInputElement | HTMLSelectElement>(mode, name).value;
  const dialog = () => document.querySelector<HTMLDialogElement>('#ship-confirmation')!;
  const feedback = (mode: Mode, text: string, error = false) => {
    const element = control<HTMLElement>(mode, 'error');
    element.textContent = text; element.className = error ? 'status error' : 'status';
  };
  const field = (mode: Mode, name: string, label: string, required = false, select = false, number = false) => `<div class="field ${name === 'part_number' || name === 'lot_number' || name === 'recipient' || name === 'notes' ? 'full' : ''}"><label for="${mode}-${name}">${label}${required ? ' <span class="required">*</span>' : ''}</label>${select ? `<select id="${mode}-${name}" name="${name}" ${required ? 'required' : ''}><option value="">Select…</option></select>` : `<input id="${mode}-${name}" name="${name}" ${required ? 'required' : ''} ${number ? 'type="number" min="1" max="2147483647" step="1"' : ''}>`}</div>`;
  for (const mode of ['receive', 'ship'] as const) {
    document.querySelector('main')!.insertAdjacentHTML('beforeend', `<section id="${mode}" hidden><div class="page-heading"><div><h1>${mode === 'receive' ? 'Receive' : 'Ship'} stock</h1><p>${mode === 'receive' ? 'Record a receipt. Keep every lot traceable.' : 'Review stock or component lot allocations before inventory leaves.'}</p></div><button class="btn" id="${mode}-refresh" disabled>Refresh availability</button></div><div id="${mode}-result" role="status" aria-live="polite"></div><div class="stock-layout"><form id="${mode}-form" class="panel panel-body"><h2>Select inventory</h2><div class="form-grid">${field(mode, 'part_number', 'Part', true, true)}${field(mode, 'location', mode === 'receive' ? 'Receive into' : 'Ship from', true, true)}${field(mode, 'quantity', 'Quantity', true, false, true)}${field(mode, 'lot_number', 'Lot number', true, mode === 'ship')}</div><h2>${mode === 'receive' ? 'Receipt' : 'Shipment'} details</h2><div class="form-grid">${mode === 'receive' ? field(mode, 'reference', 'Reference') + field(mode, 'notes', 'Notes') : field(mode, 'recipient', 'Recipient / project', true) + field(mode, 'carrier', 'Carrier') + field(mode, 'tracking', 'Tracking number') + field(mode, 'reference', 'Reference')}</div><p class="help">Operator identity comes from the visible header. Enter your name before submitting.</p><div id="${mode}-error" role="alert" aria-live="polite"></div><button id="${mode}-submit" class="btn primary" disabled>${mode === 'receive' ? 'Receive stock' : 'Review shipment'}</button></form><div class="panel"><div class="panel-head"><h2>Current stock and review</h2></div><div id="${mode}-review" class="panel-body">Select a part to read current inventory.</div><div id="${mode}-recovery" class="panel-body" hidden></div></div></div></section>`);
    form(mode).addEventListener('submit', event => { event.preventDefault(); void submit(mode); });
    const edited = () => { if (mode === 'ship') { preview = null; bomReview = null; } renderReview(mode); };
    form(mode).addEventListener('input', edited); form(mode).addEventListener('change', edited);
    control<HTMLSelectElement>(mode, 'part_number').addEventListener('change', () => { void refresh(mode, true); });
    control<HTMLSelectElement>(mode, 'location').addEventListener('change', () => { renderLots(mode); renderReview(mode); });
    control<HTMLButtonElement>(mode, 'refresh').onclick = () => { void refresh(mode); };
    control<HTMLElement>(mode, 'result').onclick = event => {
      if ((event.target as HTMLElement).closest('[data-another]')) { states[mode].completed = false; clearEntry(mode); lock(mode); void refresh(mode); }
    };
    control<HTMLElement>(mode, 'recovery').onclick = event => {
      const action = (event.target as HTMLElement).closest<HTMLButtonElement>('button')?.dataset.recovery;
      if (action === 'read') void reconcile(mode);
      if (!states[mode].reconciled) return;
      if (action === 'completed' || action === 'absent') {
        states[mode].uncertain = false; states[mode].reconciled = false;
        control<HTMLElement>(mode, 'recovery').hidden = true;
        feedback(mode, action === 'completed' ? 'Completion verified. Start another entry when ready.' : 'You verified no matching operation. Review the preserved draft before submitting.');
        if (action === 'completed') {
          const submitted = states[mode].submitted!; const context = states[mode].context!;
          const text = `Verified ${mode === 'receive' ? 'receipt' : 'shipment'} of ${submitted.quantity} × ${submitted.part_number}, lot ${submitted.lot_number}, at ${submitted.location}. Current location stock: ${context.part.location_balances[submitted.location] ?? 0}; total stock: ${context.part.quantity}.${mode === 'ship' ? ` Shipment numbers reviewed: ${states[mode].recoveredNumbers.join(', ') || 'No new shipment records; investigate in History.'}` : ''}`;
          control<HTMLElement>(mode, 'result').innerHTML = `<div class="status success">${esc(text)}${mode === 'ship' ? ' <button class="btn" data-another>Ship another</button>' : ''}</div>`;
          if (mode === 'receive') clearEntry(mode); else states[mode].completed = true;
          toast(text);
        }
        lock(mode); void changed();
      }
    };
  }
  document.querySelector('#app')!.insertAdjacentHTML('afterend', `<dialog id="ship-confirmation" aria-labelledby="ship-confirm-title"><div class="dialog-heading"><h2 id="ship-confirm-title">Confirm shipment</h2><button id="ship-cancel" class="btn">Cancel</button></div><div id="ship-confirm-data" class="dialog-body"></div><div class="panel-body"><button id="ship-confirm-submit" class="btn primary">Confirm shipment</button></div></dialog>`);
  document.querySelector<HTMLButtonElement>('#ship-cancel')!.onclick = () => dialog().close();
  dialog().addEventListener('cancel', event => { if (states.ship.pending) event.preventDefault(); });
  dialog().addEventListener('close', () => {
    preview = null;
    const focus = states.ship.completed ? control<HTMLElement>('ship', 'result').querySelector<HTMLButtonElement>('[data-another]') : states.ship.uncertain ? control<HTMLElement>('ship', 'recovery').querySelector<HTMLButtonElement>('[data-recovery=read]') : control<HTMLButtonElement>('ship', 'submit');
    focus?.focus();
  });
  document.querySelector<HTMLButtonElement>('#ship-confirm-submit')!.onclick = () => { void confirmShipment(); };

  function lock(mode: Mode) {
    const state = states[mode];
    const blocked = state.pending || state.uncertain || state.completed;
    form(mode).querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select').forEach(field => { field.disabled = blocked; });
    control<HTMLButtonElement>(mode, 'submit').disabled = blocked || !state.context || !state.context.part.active;
    control<HTMLButtonElement>(mode, 'refresh').disabled = state.pending;
    if (mode === 'ship') {
      const lot = control<HTMLSelectElement>(mode, 'lot_number');
      lot.disabled = blocked || !!state.context?.has_bom; lot.required = !state.context?.has_bom;
      lot.closest<HTMLElement>('.field')!.hidden = !!state.context?.has_bom;
    }
  }
  function renderLots(mode: Mode) {
    if (mode !== 'ship') return;
    const select = control<HTMLSelectElement>(mode, 'lot_number'); const saved = select.value;
    const lots = states[mode].context?.part.balances.filter(b => b.location === value(mode, 'location') && b.quantity > 0) ?? [];
    select.innerHTML = '<option value="">Select an available lot…</option>' + lots.map(b => `<option value="${esc(b.lot_number)}">${esc(b.lot_number)} · ${b.quantity} available</option>`).join('');
    if (saved && !lots.some(b => b.lot_number === saved)) select.insertAdjacentHTML('beforeend', `<option value="${esc(saved)}">${esc(saved)} · unavailable</option>`);
    select.value = saved;
  }
  function allocations(review: BOMPreview) {
    return pair('BOM build capacity at this location', review.buildable) + pair('Requested shipment readiness', review.plan.ready ? 'Ready' : 'Blocked — component shortage') + `<h3>Aggregated leaf requirements</h3><div class="table-wrap"><table><thead><tr><th>Material</th><th class="num">Required</th><th class="num">Available</th><th class="num">Shortage</th></tr></thead><tbody>${review.plan.requirements.map(r => `<tr><td>${esc(r.part_number)}<br>${esc(r.description)}</td><td class="num">${r.quantity_required}</td><td class="num">${r.stock_available}</td><td class="num">${r.shortage}</td></tr>`).join('')}</tbody></table></div><h3>Leaf lot allocations</h3><div class="table-wrap"><table><thead><tr><th>Material</th><th>Lot / Location</th><th class="num">Consume</th><th class="num">Lot stock</th></tr></thead><tbody>${review.plan.lines.map(line => `<tr><td>${esc(line.part_number)}</td><td>${esc(line.lot_number)}<br>${esc(line.location)}</td><td class="num">${line.quantity_allocated}</td><td class="num">${line.lot_stock}</td></tr>`).join('')}</tbody></table></div><p class="help">Parent and intermediate assembly stock stays unchanged. Only these leaf lots are consumed.</p>`;
  }
  function renderReview(mode: Mode) {
    const context = states[mode].context;
    const location = value(mode, 'location'), lot = value(mode, 'lot_number');
    const lotStock = context?.part.balances.find(b => b.location === location && b.lot_number === lot)?.quantity ?? 0;
    control<HTMLElement>(mode, 'review').innerHTML = context ? `${pair('Part', context.part.part_number)}<p class="description">${esc(context.part.description)}</p>${pair('Location', location)}${pair('Total location stock', context.part.location_balances[location] ?? 0)}${mode === 'ship' && !context.has_bom ? pair('Selected lot', lot || 'Select a lot') + pair('Selected-lot availability', lotStock) : ''}${pair('Quantity requested', value(mode, 'quantity') || 'Enter quantity')}${pair('Operator', operator() || 'Name required in header')}<p class="help">${mode === 'ship' ? 'Review shipment reads current stock and shows the exact stock impact before confirmation.' : 'Stock is revalidated by Python when receiving.'}</p>${!context.part.active ? '<div class="status error">This part is inactive. Use the original application to reactivate it.</div>' : ''}${pair('Part stock status', context.part.low_stock ? 'Low stock' : 'Above minimum')}${mode === 'ship' && context.has_bom ? states.ship.completed ? '<p class="help">Shipment complete. Inspect shipment for consumed leaf lots, or use Ship another.</p>' : bomReview ? allocations(bomReview) : '<p class="help">BOM parent selected. Review shipment to read current leaf requirements, build capacity, and lot allocations.</p>' : ''}` : 'Select a part to read current inventory.';
  }
  async function refresh(mode: Mode, adoptLocation = false) {
    const state = states[mode];
    if (state.pending || state.uncertain) return;
    const version = ++state.version; preview = null; bomReview = null;
    state.context = null; lock(mode);
    control<HTMLElement>(mode, 'review').textContent = 'Reading current stock…';
    try {
      const api = getAPI();
      const [parts, locations] = await Promise.all([read(api.search_parts({ query: '', status: 'all', low_stock: false, sort: 'part_number', descending: false })), read(api.locations())]);
      if (version !== state.version) return;
      const part = value(mode, 'part_number');
      control<HTMLSelectElement>(mode, 'part_number').innerHTML = '<option value="">Select a part…</option>' + parts.map(p => `<option value="${esc(p.part_number)}">${esc(p.part_number)} · ${esc(p.description)}${p.active ? '' : ' (inactive)'}</option>`).join('');
      if (part && !parts.some(p => p.part_number === part)) control<HTMLSelectElement>(mode, 'part_number').insertAdjacentHTML('beforeend', `<option value="${esc(part)}">${esc(part)} · unavailable</option>`);
      control<HTMLSelectElement>(mode, 'part_number').value = part;
      const location = value(mode, 'location');
      control<HTMLSelectElement>(mode, 'location').innerHTML = locations.map(l => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
      control<HTMLSelectElement>(mode, 'location').value = locations.includes(location) ? location : locations[0] ?? '';
      if (part) {
        const context = await read(api.stock_context(part));
        if (version !== state.version) return;
        state.context = context;
        if (adoptLocation) control<HTMLSelectElement>(mode, 'location').value = context.part.location;
      }
      renderLots(mode); renderReview(mode); lock(mode);
    } catch (error) {
      if (version !== state.version) return;
      state.context = null; feedback(mode, `${message(error)} Use Refresh availability to try again.`, true); lock(mode);
      control<HTMLElement>(mode, 'review').textContent = 'Current availability is unavailable.';
    }
  }
  function request(mode: Mode): Receipt | ShipmentRequest {
    const common = { part_number: value(mode, 'part_number'), quantity: Number(value(mode, 'quantity')), location: value(mode, 'location'), lot_number: value(mode, 'lot_number'), operator: operator(), reference: value(mode, 'reference') };
    if (!common.operator.trim()) throw new Error('Enter your operator name in the header before submitting.');
    return mode === 'receive' ? { ...common, notes: value(mode, 'notes') } : { ...common, recipient: value(mode, 'recipient'), carrier: value(mode, 'carrier'), tracking: value(mode, 'tracking') };
  }
  function clearEntry(mode: Mode) {
    for (const name of mode === 'receive' ? ['quantity', 'lot_number', 'reference'] : ['quantity', 'lot_number', 'reference', 'recipient', 'carrier', 'tracking']) control<HTMLInputElement | HTMLSelectElement>(mode, name).value = '';
    if (mode === 'ship') { preview = null; bomReview = null; } renderReview(mode);
  }
  function ambiguous(mode: Mode, error: unknown) {
    const state = states[mode];
    state.uncertain = error instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(error.code);
    feedback(mode, message(error) + (state.uncertain ? ' Completion is uncertain. Do not repeat this entry. Read current audit records below and verify whether it completed.' : ''), true);
    if (state.uncertain) {
      const submitted = state.submitted!;
      const recovery = control<HTMLElement>(mode, 'recovery'); recovery.hidden = false;
      recovery.innerHTML = `<h3>Verify uncertain ${mode === 'receive' ? 'receipt' : 'shipment'}</h3>${pair('Submitted part', submitted.part_number)}${pair('Lot / location', `${submitted.lot_number || 'Automatic component lots'} / ${submitted.location}`)}${mode === 'ship' && bomReview ? allocations(bomReview) : ''}${pair('Quantity / operator', `${submitted.quantity} / ${submitted.operator}`)}${pair('Reference', submitted.reference || '—')}${'notes' in submitted ? pair('Notes', submitted.notes || '—') : pair('Recipient', submitted.recipient) + pair('Carrier', submitted.carrier || '—') + pair('Tracking', submitted.tracking || '—')}<button class="btn" data-recovery="read">Read current stock and audit</button><div class="recovery-records"></div>`;
    }
  }
  async function submit(mode: Mode) {
    const state = states[mode];
    if (state.pending || state.uncertain || state.completed || !state.context) return;
    let fields: Receipt | ShipmentRequest;
    try { fields = request(mode); } catch (error) { feedback(mode, message(error), true); return; }
    state.pending = true; const version = ++state.version; const reviewVersion = previewVersion; lock(mode); feedback(mode, mode === 'receive' ? 'Receiving…' : 'Reading shipment review…');
    let mutationStarted = false;
    try {
      if (mode === 'ship') {
        const { lot_number: _lot, ...bomFields } = fields as ShipmentRequest;
        const result = state.context.has_bom ? await read(getAPI().preview_bom_ship(bomFields)) : await read(getAPI().preview_ship(fields as ShipmentRequest));
        if (version !== state.version || reviewVersion !== previewVersion || active !== 'ship') return;
        state.context = result.context; preview = result;
        if ('plan' in result) {
          bomReview = result;
          if (!result.plan.ready) { preview = null; feedback(mode, 'Component shortage. No shipment was sent. Replenish stock and review again.', true); return; }
        }
        const r = result.request;
        document.querySelector('#ship-confirm-data')!.innerHTML = pair('Part', r.part_number) + pair('Location / lot', `${r.location} / ${'lot_number' in r ? r.lot_number : 'Automatic component lots'}`) + pair('Quantity', r.quantity) + pair('Recipient', r.recipient) + pair('Operator', r.operator) + pair('Carrier', r.carrier || '—') + pair('Tracking', r.tracking || '—') + pair('Reference', r.reference || '—') + ('plan' in result ? allocations(result) : pair('Selected-lot stock', result.lot_stock) + pair('Total location stock', result.location_stock) + pair('Lot remaining after shipment', result.remaining)) + '<p class="help">Confirmation creates a real shipment. Python rechecks available stock at submission.</p>';
        feedback(mode, 'Current shipment review is ready. Confirm or cancel.'); dialog().showModal();
      } else {
        const before = await read(getAPI().stock_context(fields.part_number));
        state.before = before.transactions.length; state.submitted = { ...fields };
        mutationStarted = true;
        const context = await read(getAPI().receive(fields as Receipt)); state.context = context;
        const locationStock = context.part.location_balances[fields.location] ?? 0;
        const text = `Received ${fields.quantity} × ${context.part.part_number} into ${fields.location}, lot ${fields.lot_number.trim().toUpperCase()}. Updated location stock: ${locationStock}; total stock: ${context.part.quantity}.`;
        control<HTMLElement>(mode, 'result').innerHTML = `<div class="status success">${esc(text)}</div>`;
        clearEntry(mode); feedback(mode, 'Ready for the next receipt.'); toast(text); void changed();
      }
    } catch (error) {
      if (mode === 'ship' && (version !== state.version || reviewVersion !== previewVersion)) return;
      if (mutationStarted) ambiguous(mode, error); else feedback(mode, `${message(error)} No stock submission was sent.`, true);
    } finally {
      state.pending = false; lock(mode); renderReview(mode);
      if (mode === 'ship' && (version !== state.version || reviewVersion !== previewVersion)) {
        feedback(mode, 'Previous review cancelled. Review current availability before submitting.');
        if (active === 'ship') void refresh(mode);
      }
    }
  }
  async function confirmShipment() {
    const state = states.ship;
    if (state.pending || state.uncertain || state.completed || !preview) return;
    if (operator().trim() !== preview.request.operator) {
      dialog().close(); feedback('ship', 'Operator changed. Review the shipment again.', true); return;
    }
    const reviewed = preview;
    const fields: ShipmentRequest = { ...reviewed.request, lot_number: 'lot_number' in reviewed.request ? reviewed.request.lot_number : '' };
    state.before = preview.context.transactions.length; state.beforeShipments = preview.context.shipments.length; state.submitted = fields;
    state.pending = true; ++state.version; lock('ship');
    document.querySelector<HTMLButtonElement>('#ship-confirm-submit')!.disabled = true;
    document.querySelector<HTMLButtonElement>('#ship-cancel')!.disabled = true;
    try {
      const result = 'plan' in reviewed ? await read(getAPI().ship_bom({ ...reviewed.request, review_id: reviewed.review_id })) : await read(getAPI().ship(fields)); state.context = result.context; state.completed = true;
      const text = `Shipped ${fields.quantity} × ${fields.part_number} to ${fields.recipient}. Shipment ${result.shipment_number}. ${'plan' in reviewed ? 'Parent stock unchanged; leaf consumption recorded in History.' : `Updated total stock: ${result.context.part.quantity}.`}`;
      bomReview = null;
      control<HTMLElement>('ship', 'result').innerHTML = `<div class="status success">${esc(text)} <button class="btn" data-another>Ship another</button> <button class="btn" data-shipment="${esc(result.shipment_number)}">Inspect shipment</button></div>`;
      feedback('ship', 'Shipment complete. Use Ship another to begin the next entry.'); toast(text); void changed();
    } catch (error) {
      ambiguous('ship', error);
      if (error instanceof RequestError && error.code === 'PLAN_CHANGED') {
        preview = null;
        try {
          const { lot_number: _lot, ...draft } = fields;
          bomReview = await read(getAPI().preview_bom_ship(draft)); state.context = bomReview.context;
          feedback('ship', 'Allocation changed. Nothing was shipped. Updated allocations are shown below. Review shipment again to confirm the new plan.', true);
        } catch (refreshError) { bomReview = null; feedback('ship', `${message(error)} ${message(refreshError)} Refresh availability and review again.`, true); }
      }
    }
    finally {
      state.pending = false; dialog().close(); lock('ship'); renderReview('ship');
      document.querySelector<HTMLButtonElement>('#ship-confirm-submit')!.disabled = false;
      document.querySelector<HTMLButtonElement>('#ship-cancel')!.disabled = false;
    }
  }
  async function reconcile(mode: Mode) {
    const state = states[mode];
    if (!state.uncertain || state.pending || !state.submitted) return;
    state.pending = true; state.reconciled = false;
    const records = control<HTMLElement>(mode, 'recovery').querySelector<HTMLElement>('.recovery-records')!;
    records.textContent = 'Reading authoritative stock and audit…'; lock(mode);
    try {
      const context = await read(getAPI().stock_context(state.submitted.part_number)); state.context = context;
      state.recoveredNumbers = mode === 'ship' ? context.shipments.slice(0, Math.max(0, context.shipments.length - state.beforeShipments)).map(s => s.shipment_number) : [];
      const shipmentDetails = await Promise.all(state.recoveredNumbers.map(number => read(getAPI().shipment_detail(number))));
      const snapshots = shipmentDetails.map(s => `<h3>${esc(s.shipment_number)} component snapshots</h3>${s.consumed_components.map(c => `<div class="status">${esc(c.part_number)} · ${esc(c.lot_number)} · ${esc(c.location)} · Consumed ${c.quantity}</div>`).join('')}<button class="btn" data-shipment="${esc(s.shipment_number)}">Inspect shipment</button>`).join('');
      const recent = context.transactions.slice(0, Math.max(0, context.transactions.length - state.before));
      records.innerHTML = `${pair('Current total stock', context.part.quantity)}<h3>Audit records added since review</h3>${recent.length ? recent.map(tx => `<div class="status">${esc(tx.timestamp)} · ${esc(tx.tx_type)} · ${tx.quantity_change} · ${esc(tx.lot_number)} · ${esc(tx.location_from || tx.location_to)} · ${esc(tx.operator)} · ${esc(tx.reference)} · ${esc(tx.notes)}</div>`).join('') : '<p>No new audit records were found.</p>'}<h3>Recent shipments for this part</h3>${context.shipments.slice(0, 10).map(s => `<div class="status">${esc(s.shipment_number)} · ${esc(s.timestamp)} · ${s.quantity} · ${esc(s.recipient)} · ${esc(s.carrier)} · ${esc(s.tracking_number)}</div>`).join('') || '<p>No shipments.</p>'}${snapshots}<p class="help">Other operators may also have recorded stock. Compare the submitted entry with the records; stock totals alone cannot prove completion. No request is retried automatically.</p><button class="btn" data-recovery="completed">I verified completion</button> <button class="btn" data-recovery="absent">I verified it did not complete — unlock draft</button>`;
      state.reconciled = true; renderReview(mode);
    } catch (error) { records.textContent = `${message(error)} Completion remains uncertain. Read again before taking action.`; }
    finally { state.pending = false; lock(mode); }
  }
  return {
    async open(mode: Mode, number?: string) {
      active = mode;
      const state = states[mode];
      if (dialog().open && !state.pending) dialog().close(); preview = null;
      if (state.pending) { ++state.version; return; }
      if (state.uncertain || state.completed) return;
      if (number && value(mode, 'part_number') !== number) {
        const select = control<HTMLSelectElement>(mode, 'part_number');
        if (!Array.from(select.options).some(o => o.value === number)) select.insertAdjacentHTML('beforeend', `<option value="${esc(number)}">${esc(number)}</option>`);
        select.value = number; control<HTMLInputElement | HTMLSelectElement>(mode, 'lot_number').value = '';
      }
      await refresh(mode, !!number);
    },
    leave() { active = null; ++states.ship.version; preview = null; if (dialog().open && !states.ship.pending) dialog().close(); },
    operatorChanged() { ++previewVersion; preview = null; if (dialog().open && !states.ship.pending) dialog().close(); renderReview('receive'); renderReview('ship'); },
  };
}
