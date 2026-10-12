import { read, RequestError, type ready, type CountDraft, type CountReview, type CountSubmission, type StockContext } from './bridge';

type API = Awaited<ReturnType<typeof ready>>;
const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';
const pair = (label: string, value: unknown) => `<div class="detail-pair"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
const signed = (value: number) => `${value > 0 ? '+' : ''}${value}`;

// Adjust Count is self-contained: Python owns expected stock, the large-correction threshold and the ledger.
export function adjustWorkflow(getAPI: () => API, operator: () => string, changed: () => Promise<void>, toast: (text: string, summary?: string) => void) {
  const state = { pending: false, uncertain: false, version: 0, context: null as StockContext | null, submitted: null as CountSubmission | null, before: 0, reconciled: false };
  let review: CountReview | null = null;
  let reviewing = false;
  let reviewVersion = 0;
  let reviewTimer: ReturnType<typeof setTimeout> | undefined;
  let proposal: CountSubmission | null = null;
  let active = false;
  const control = <T extends HTMLElement>(name: string) => document.querySelector<T>(`#adjust-${name}`)!;
  const value = (name: string) => control<HTMLInputElement | HTMLSelectElement>(name).value;
  const dialog = () => document.querySelector<HTMLDialogElement>('#adjust-confirmation')!;
  const feedback = (text: string, error = false) => { const element = control<HTMLElement>('error'); element.textContent = text; element.className = error ? 'status error' : 'status'; };
  const field = (name: string, label: string, kind: 'select' | 'number' | 'text', full = false) => `<div class="field ${full ? 'full' : ''}"><label for="adjust-${name}">${label} <span class="required">*</span></label>${kind === 'select' ? `<select id="adjust-${name}" name="${name}" required><option value="">Select…</option></select>` : `<input id="adjust-${name}" name="${name}" required ${kind === 'number' ? 'type="number" min="0" max="2147483647" step="1"' : ''}>`}</div>`;
  document.querySelector('main')!.insertAdjacentHTML('beforeend', `<section id="adjust" hidden><div class="page-heading"><div><h1>Adjust count</h1><p>Reconcile a counted Lot total with the ledger. Every correction is recorded with its reason.</p></div><button class="btn" id="adjust-refresh" disabled>Refresh availability</button></div><div id="adjust-result" role="status" aria-live="polite"></div><div class="stock-layout"><form id="adjust-form" class="panel panel-body"><h2>Select Lot</h2><div class="form-grid">${field('part_number', 'Part', 'select', true)}${field('location', 'Location', 'select')}${field('lot_number', 'Lot', 'select')}</div><h2>Count</h2><div class="form-grid">${field('counted', 'Counted total', 'number')}${field('reason', 'Reason', 'text', true)}</div><p class="help">Enter the total physically counted in this Lot at this Location. Operator identity comes from the visible header.</p><div id="adjust-error" role="alert" aria-live="polite"></div><button id="adjust-submit" class="btn primary" disabled>Record count correction</button></form><div class="panel"><div class="panel-head"><h2>Expected and counted</h2></div><div id="adjust-review" class="panel-body">Select a part to read current inventory.</div><div id="adjust-recovery" class="panel-body" hidden></div></div></div></section>`);
  document.querySelector('#app')!.insertAdjacentHTML('afterend', `<dialog id="adjust-confirmation" aria-labelledby="adjust-confirm-title"><div class="dialog-heading"><h2 id="adjust-confirm-title">Confirm large count correction</h2><button id="adjust-cancel" class="btn">Cancel</button></div><div id="adjust-confirm-data" class="dialog-body"></div><div class="panel-body"><button id="adjust-confirm-submit" class="btn primary">Confirm count correction</button></div></dialog>`);
  const form = control<HTMLFormElement>('form');
  form.addEventListener('submit', event => { event.preventDefault(); void submit(); });
  form.addEventListener('input', event => { if ((event.target as HTMLElement).id === 'adjust-reason') renderReview(); else scheduleReview(); }); form.addEventListener('change', () => scheduleReview());
  control<HTMLSelectElement>('part_number').addEventListener('change', () => { control<HTMLSelectElement>('lot_number').value = ''; void refresh(true); });
  control<HTMLSelectElement>('location').addEventListener('change', () => { control<HTMLSelectElement>('lot_number').value = ''; renderLots(); scheduleReview(); });
  control<HTMLButtonElement>('refresh').onclick = () => { void refresh(); };
  control<HTMLElement>('recovery').onclick = event => {
    const action = (event.target as HTMLElement).closest<HTMLButtonElement>('button')?.dataset.recovery;
    if (action === 'read') void reconcile();
    if (!state.reconciled) return;
    if (action === 'completed' || action === 'absent') {
      state.uncertain = false; state.reconciled = false; control<HTMLElement>('recovery').hidden = true;
      feedback(action === 'completed' ? 'Completion verified. Start another count when ready.' : 'You verified no matching correction. Review the preserved draft before submitting.');
      if (action === 'completed') {
        const s = state.submitted!;
        const text = `Verified count correction of ${s.part_number} lot ${s.lot_number} at ${s.location}: expected ${s.expected}, counted ${s.counted}. Current total stock: ${state.context!.part.quantity}.`;
        control<HTMLElement>('result').innerHTML = `<div class="status success">${esc(text)}</div>`;
        clearEntry(); toast(text, `Count correction verified for ${s.part_number}.`); void changed();
      }
      lock(); scheduleReview();
    }
  };
  document.querySelector<HTMLButtonElement>('#adjust-cancel')!.onclick = () => dialog().close();
  dialog().addEventListener('cancel', event => { if (state.pending) event.preventDefault(); });
  dialog().addEventListener('close', () => { if (proposal) feedback('Count correction cancelled. Nothing was recorded.'); proposal = null; (state.uncertain ? control<HTMLElement>('recovery').querySelector<HTMLButtonElement>('[data-recovery=read]') : control<HTMLButtonElement>('submit'))?.focus(); });
  document.querySelector<HTMLButtonElement>('#adjust-confirm-submit')!.onclick = () => { void confirm(); };

  const lots = () => state.context?.part.balances.filter(b => b.location === value('location')) ?? [];
  function draft(): CountDraft | null {
    const input = control<HTMLInputElement>('counted'); const counted = input.valueAsNumber;
    const part = value('part_number'), location = value('location'), lot = value('lot_number');
    if (!part || !location || !lot || !input.validity.valid || !Number.isSafeInteger(counted) || counted < 0) return null;
    return { part_number: part, location, lot_number: lot, counted };
  }
  function lock() {
    const blocked = state.pending || state.uncertain;
    form.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select').forEach(element => { element.disabled = blocked; });
    control<HTMLButtonElement>('submit').disabled = blocked || !state.context;
    control<HTMLButtonElement>('refresh').disabled = state.pending;
  }
  function renderLots() {
    const select = control<HTMLSelectElement>('lot_number'); const saved = select.value;
    select.innerHTML = '<option value="">Select a lot…</option>' + lots().map(b => `<option value="${esc(b.lot_number)}">${esc(b.lot_number)} · ${b.quantity} in system</option>`).join('');
    if (saved && !lots().some(b => b.lot_number === saved)) select.insertAdjacentHTML('beforeend', `<option value="${esc(saved)}">${esc(saved)} · unavailable</option>`);
    select.value = saved;
  }
  function scheduleReview() {
    review = null; ++reviewVersion; clearTimeout(reviewTimer); reviewing = false;
    if (state.uncertain || state.pending) { renderReview(); return; }
    renderReview();
    const requested = draft();
    if (!requested || !state.context || !active) return;
    reviewing = true; renderReview();
    reviewTimer = setTimeout(() => { void loadReview(requested, reviewVersion); }, 150);
  }
  async function loadReview(requested: CountDraft, version: number) {
    try {
      const result = await read(getAPI().preview_count(requested));
      if (version !== reviewVersion) return;
      review = result; state.context = result.context; reviewing = false; renderReview();
    } catch (error) {
      if (version !== reviewVersion) return;
      reviewing = false; renderReview(message(error));
    }
  }
  function renderReview(problem = '') {
    const context = state.context;
    if (!context) { control<HTMLElement>('review').textContent = 'Select a part to read current inventory.'; return; }
    const selected = lots().find(b => b.lot_number === value('lot_number'));
    let figures = '<p class="help">Select a lot and enter the counted total to review the correction.</p>';
    if (problem) figures = `<div class="status error">${esc(problem)}</div>`;
    else if (reviewing) figures = '<p class="help">Reading the authoritative expected count…</p>';
    else if (review) {
      const trend = review.difference === 0 ? 'No change' : review.difference > 0 ? 'Increase' : 'Decrease';
      figures = `<div class="stock-impact"><div class="review-title">Count review</div><div class="review-row"><span>Expected in system</span><strong>${review.expected}</strong></div><div class="review-row"><span>Counted total</span><strong>${review.counted}</strong></div><div class="review-row total"><span>Difference</span><strong>${signed(review.difference)} · ${trend}</strong></div></div>${review.requires_confirmation ? '<span class="badge warn">Large correction — confirmation required</span>' : ''}<p class="help">Python validates the current count again at submission.</p>`;
    } else if (selected) figures = `<div class="stock-impact"><div class="review-title">Last read</div><div class="review-row"><span>Expected in system</span><strong>${selected.quantity}</strong></div></div><p class="help">Enter the counted total to review the correction.</p>`;
    control<HTMLElement>('review').innerHTML = `<div class="review-part">${esc(context.part.part_number)}</div><p class="description help">${esc(context.part.description)}</p>${pair('Location', value('location') || 'Select a location')}${pair('Lot', value('lot_number') || 'Select a lot')}${figures}${pair('Reason', value('reason') || 'Required')}${pair('Operator', operator() || 'Name required in header')}${!context.part.active ? '<div class="status">This part is inactive. Counts can still be corrected.</div>' : ''}`;
  }
  async function refresh(adoptLocation = false) {
    if (state.pending || state.uncertain) return;
    const version = ++state.version; state.context = null; lock();
    control<HTMLElement>('review').textContent = 'Reading current stock…';
    try {
      const api = getAPI();
      const [parts, locations] = await Promise.all([read(api.search_parts({ query: '', status: 'all', low_stock: false, sort: 'part_number', descending: false })), read(api.locations())]);
      if (version !== state.version) return;
      const part = value('part_number');
      control<HTMLSelectElement>('part_number').innerHTML = '<option value="">Select a part…</option>' + parts.map(p => `<option value="${esc(p.part_number)}">${esc(p.part_number)} · ${esc(p.description)}${p.active ? '' : ' (inactive)'}</option>`).join('');
      if (part && !parts.some(p => p.part_number === part)) control<HTMLSelectElement>('part_number').insertAdjacentHTML('beforeend', `<option value="${esc(part)}">${esc(part)} · unavailable</option>`);
      control<HTMLSelectElement>('part_number').value = part;
      const location = value('location');
      control<HTMLSelectElement>('location').innerHTML = locations.map(l => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
      control<HTMLSelectElement>('location').value = locations.includes(location) ? location : locations[0] ?? '';
      if (part) {
        const context = await read(api.stock_context(part));
        if (version !== state.version) return;
        state.context = context;
        if (adoptLocation) control<HTMLSelectElement>('location').value = context.part.location;
      }
      renderLots(); lock(); scheduleReview();
    } catch (error) {
      if (version !== state.version) return;
      state.context = null; feedback(`${message(error)} Use Refresh availability to try again.`, true); lock();
      control<HTMLElement>('review').textContent = 'Current availability is unavailable.';
    }
  }
  function clearEntry() { control<HTMLInputElement>('counted').value = ''; control<HTMLInputElement>('reason').value = ''; }
  async function submit() {
    if (state.pending || state.uncertain || !state.context) return;
    const requested = draft(); const name = operator().trim(); const reason = value('reason');
    if (!requested) { feedback('Select a lot and enter a whole-number counted total of 0 or more.', true); return; }
    if (!name) { feedback('Enter your operator name in the header before submitting.', true); return; }
    state.pending = true; const version = ++state.version; lock(); feedback('Reading the current count…');
    let next: CountSubmission | null = null;
    try {
      const fresh = await read(getAPI().preview_count(requested));
      if (version !== state.version || !active) return;
      state.context = fresh.context; renderLots();
      const shown = review; review = fresh; renderReview();
      if (!shown || shown.expected !== fresh.expected || shown.counted !== fresh.counted) { feedback('Expected count refreshed. Check the review below, then submit again.', true); return; }
      next = { ...requested, expected: fresh.expected, operator: name, reason, confirmed: false };
      if (fresh.requires_confirmation) {
        proposal = next; next = null;
        document.querySelector('#adjust-confirm-data')!.innerHTML = pair('Part', requested.part_number) + pair('Location / lot', `${requested.location} / ${requested.lot_number}`) + pair('Expected in system', fresh.expected) + pair('Counted total', fresh.counted) + pair('Difference', signed(fresh.difference)) + pair('Reason', reason) + pair('Operator', name) + '<p class="help">This is a large correction. Confirmation records a real count correction. Python rechecks the current count at submission.</p>';
        feedback('Large correction. Confirm or cancel.'); dialog().showModal();
      }
    } catch (error) {
      if (version === state.version) feedback(`${message(error)} No count correction was sent.`, true);
    } finally { state.pending = false; lock(); }
    if (next) await send(next);
  }
  async function confirm() {
    if (state.pending || state.uncertain || !proposal) return;
    const pending = proposal;
    if (operator().trim() !== pending.operator) { proposal = null; dialog().close(); feedback('Operator changed. Review the count again.', true); return; }
    proposal = null; dialog().close(); await send({ ...pending, confirmed: true });
  }
  async function send(submission: CountSubmission) {
    if (state.pending || state.uncertain) return;
    state.submitted = submission; state.before = state.context?.transactions.length ?? 0;
    state.pending = true; ++state.version; lock(); feedback('Recording count correction…'); control<HTMLElement>('result').textContent = '';
    try {
      const result = await read(getAPI().adjust_count(submission));
      state.context = result.context; renderLots();
      const text = `Corrected ${submission.part_number} lot ${submission.lot_number} at ${submission.location} from ${submission.expected} to ${submission.counted} (${signed(result.difference)}). Updated total stock: ${result.context.part.quantity}.`;
      control<HTMLElement>('result').innerHTML = `<div class="status success">${esc(text)}</div>`;
      clearEntry(); feedback('Ready for the next count.'); toast(text, `Count corrected for ${submission.part_number}.`); void changed();
    } catch (error) {
      const uncertain = error instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(error.code);
      state.uncertain = uncertain;
      feedback(message(error) + (uncertain ? ' Completion is uncertain. Do not repeat this entry. Read current audit records below and verify whether it completed.' : ' No count correction was recorded.'), true);
      if (uncertain) showRecovery(submission);
      else if (error instanceof RequestError && error.code === 'STALE') void refresh();
    } finally { state.pending = false; lock(); scheduleReview(); }
  }
  function showRecovery(s: CountSubmission) {
    const recovery = control<HTMLElement>('recovery'); recovery.hidden = false; state.reconciled = false;
    recovery.innerHTML = `<h3>Verify uncertain count correction</h3>${pair('Submitted lot / location', `${s.lot_number} / ${s.location}`)}${pair('Expected / counted', `${s.expected} / ${s.counted}`)}${pair('Reason / operator', `${s.reason} / ${s.operator}`)}<button class="btn" data-recovery="read">Read current stock and audit</button><div class="recovery-records"></div>`;
  }
  async function reconcile() {
    const submitted = state.submitted;
    if (!state.uncertain || state.pending || !submitted) return;
    state.pending = true; state.reconciled = false;
    const records = control<HTMLElement>('recovery').querySelector<HTMLElement>('.recovery-records')!;
    records.textContent = 'Reading authoritative stock and audit…'; lock();
    try {
      const context = await read(getAPI().stock_context(submitted.part_number)); state.context = context;
      const current = context.part.balances.find(b => b.location === submitted.location && b.lot_number === submitted.lot_number)?.quantity ?? 0;
      const recent = context.transactions.slice(0, Math.max(0, context.transactions.length - state.before));
      records.innerHTML = `${pair('Current lot stock', current)}<h3>Audit records added since review</h3>${recent.length ? recent.map(tx => `<div class="status">${esc(tx.timestamp)} · ${esc(tx.tx_type)} · ${signed(tx.quantity_change)} · ${esc(tx.part_number)} · ${esc(tx.lot_number)} · ${esc(tx.location_from || tx.location_to)} · ${esc(tx.operator)} · ${esc(tx.reference)}</div>`).join('') : '<p>No new audit records were found.</p>'}<p class="help">Other operators may also have recorded stock. Compare the submitted entry with the records; a stock total alone cannot prove completion. No request is retried automatically.</p><button class="btn" data-recovery="completed">I verified completion</button> <button class="btn" data-recovery="absent">I verified it did not complete — unlock draft</button>`;
      state.reconciled = true;
    } catch (error) { records.textContent = `${message(error)} Completion remains uncertain. Read again before taking action.`; }
    finally { state.pending = false; lock(); }
  }
  return {
    async open(number?: string) {
      active = true;
      if (dialog().open && !state.pending) dialog().close();
      if (state.pending) { ++state.version; return; }
      if (state.uncertain) { if (number && number !== state.submitted?.part_number) feedback('Verify the uncertain count correction for the earlier part before starting another.', true); return; }
      if (number && value('part_number') !== number) {
        const select = control<HTMLSelectElement>('part_number');
        if (!Array.from(select.options).some(o => o.value === number)) select.insertAdjacentHTML('beforeend', `<option value="${esc(number)}">${esc(number)}</option>`);
        select.value = number; control<HTMLSelectElement>('lot_number').value = '';
      }
      await refresh(!!number);
    },
    leave() { active = false; ++state.version; ++reviewVersion; clearTimeout(reviewTimer); reviewing = false; if (dialog().open && !state.pending) dialog().close(); },
    operatorChanged() { proposal = null; if (dialog().open && !state.pending) dialog().close(); renderReview(); },
  };
}
