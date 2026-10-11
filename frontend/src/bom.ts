import { read, RequestError, type ready, type BOMDefinition, type BOMLink } from './bridge';

type API = Awaited<ReturnType<typeof ready>>;
type Change = { kind: 'save'; parent: string; component: string; quantity_per: number } | { kind: 'remove'; parent: string; component: string };
const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';
const pair = (label: string, value: unknown) => `<div class="detail-pair"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;

// BOM authoring: direct components of nested definitions. Python owns every rule; this module collects input and shows results.
export function bomWorkflow(getAPI: () => API) {
  let parent = '';
  let definition: BOMDefinition | null = null;
  let pending = false, uncertain = false, reconciled = false;
  let submitted: Change | null = null;
  let version = 0;
  let removeTrigger: HTMLElement | null = null;
  const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
  const control = <T extends HTMLElement>(name: string) => $<T>(`#bom-${name}`);
  const field = (name: string, label: string, full: boolean, select: boolean) => `<div class="field ${full ? 'full' : ''}"><label for="bom-${name}">${label} <span class="required">*</span></label>${select ? `<select id="bom-${name}" name="${name}" required><option value="">Select…</option></select>` : `<input id="bom-${name}" name="${name}" type="number" min="1" max="2147483647" step="1" required>`}</div>`;
  $('main').insertAdjacentHTML('beforeend', `<section id="bom" hidden><div class="page-heading"><div><h1>BOM</h1><p>Add, update and remove the direct components of nested bills of material.</p></div><button class="btn" id="bom-refresh" disabled>Refresh</button></div><div id="bom-result" role="status" aria-live="polite"></div><div class="stock-layout"><form id="bom-form" class="panel panel-body"><h2>Edit definition</h2><div class="form-grid">${field('parent', 'Parent part', true, true)}${field('component', 'Component part', false, true)}${field('quantity', 'Quantity per parent', false, false)}</div><p id="bom-hint" class="help">Saving an existing component updates its quantity. Stock is never changed here.</p><div id="bom-error" role="alert" aria-live="polite"></div><button id="bom-submit" class="btn primary" disabled>Add component</button></form><div class="panel"><div class="panel-head"><h2>Current definition</h2></div><div id="bom-definition" class="panel-body">Select a parent part to read its definition.</div><div id="bom-recovery" class="panel-body" hidden></div></div></div></section>`);
  $('#app').insertAdjacentHTML('afterend', `<dialog id="bom-remove" aria-labelledby="bom-remove-title"><div class="dialog-heading"><h2 id="bom-remove-title">Remove component</h2><button id="bom-remove-cancel" class="btn">Cancel</button></div><div id="bom-remove-data" class="dialog-body"></div><div class="panel-body"><button id="bom-remove-confirm" class="btn primary">Remove component</button></div></dialog>`);
  const dialog = () => $<HTMLDialogElement>('#bom-remove');
  const select = (name: string) => control<HTMLSelectElement>(name);
  const feedback = (text: string, error = false) => { const element = control('error'); element.textContent = text; element.className = error ? 'status error' : 'status'; };
  const result = (text: string) => { control('result').innerHTML = text ? `<div class="status success">${esc(text)}</div>` : ''; };

  function lock() {
    const blocked = pending || uncertain;
    for (const name of ['parent', 'component', 'quantity']) control<HTMLInputElement | HTMLSelectElement>(name).disabled = blocked;
    control<HTMLButtonElement>('refresh').disabled = pending;
    control<HTMLButtonElement>('submit').disabled = blocked || !parent;
    document.querySelectorAll<HTMLButtonElement>('#bom-definition button').forEach(button => { button.disabled = blocked; });
  }
  function link(item: BOMLink, editable: boolean) {
    const state = item.active ? '' : ' <span class="badge neutral">Inactive</span>';
    return `<tr><td><button class="part-id" data-bom-open="${esc(item.part_number)}">${esc(item.part_number)}</button>${item.has_bom ? ' <span class="badge neutral">Assembly</span>' : ''}${state}<div class="description">${esc(item.description)}</div></td><td class="num">${item.quantity_per}</td>${editable ? `<td><button class="btn small" data-bom-edit="${esc(item.part_number)}" data-quantity="${item.quantity_per}" aria-label="Edit quantity of ${esc(item.part_number)}">Edit</button> <button class="btn small" data-bom-remove="${esc(item.part_number)}" aria-label="Remove ${esc(item.part_number)}">Remove</button></td>` : ''}</tr>`;
  }
  function render() {
    const view = control('definition');
    if (!definition) { view.textContent = parent ? 'Reading current definition…' : 'Select a parent part to read its definition.'; return; }
    const { part, components, used_in: usedIn } = definition;
    view.innerHTML = `<div class="review-part">${esc(part.part_number)}</div><p class="description help">${esc(part.description)}</p>`
      + `<h3>Direct components</h3>${components.length ? `<div class="table-wrap"><table><thead><tr><th>Component</th><th class="num">Per parent</th><th>Actions</th></tr></thead><tbody>${components.map(c => link(c, true)).join('')}</tbody></table></div>` : '<p class="help">No components. This part is not an assembly.</p>'}`
      + `<h3>Used in</h3>${usedIn.length ? `<div class="table-wrap"><table><thead><tr><th>Parent assembly</th><th class="num">Per parent</th></tr></thead><tbody>${usedIn.map(u => link(u, false)).join('')}</tbody></table></div>` : '<p class="help">Not used in another BOM.</p>'}`
      + '<p class="help">Changing a definition never changes stock or past shipment snapshots. A reviewed BOM shipment that no longer matches must be reviewed again.</p>';
    lock(); hint();
  }
  function hint() {
    const number = select('component').value;
    const existing = definition?.part.part_number === parent ? definition.components.find(c => c.part_number === number) : undefined;
    control('submit').textContent = existing ? 'Update quantity' : 'Add component';
    control('hint').textContent = existing ? `${number} is already on this BOM at ${existing.quantity_per} per parent. Saving updates that quantity instead of adding a second link.` : 'Saving an existing component updates its quantity. Stock is never changed here.';
  }
  async function loadDefinition() {
    const current = ++version; definition = null; render();
    if (!parent) return;
    try {
      const loaded = await read(getAPI().bom_definition(parent));
      if (current === version) { definition = loaded; render(); }
    } catch (error) {
      if (current === version) control('definition').innerHTML = `<div class="status error" role="alert">${esc(message(error))} Use Refresh to try again.</div>`;
    }
  }
  async function refresh() {
    if (pending || uncertain) return;
    try {
      const parts = await read(getAPI().search_parts({ query: '', status: 'all', low_stock: false, sort: 'part_number', descending: false }));
      const options = '<option value="">Select a part…</option>' + parts.map(p => `<option value="${esc(p.part_number)}">${esc(p.part_number)} · ${esc(p.description)}${p.active ? '' : ' (inactive)'}</option>`).join('');
      for (const name of ['parent', 'component']) { const element = select(name); const saved = element.value; element.innerHTML = options; element.value = saved; }
      parent = select('parent').value;
    } catch (error) { feedback(`${message(error)} Use Refresh to try again.`, true); return; }
    feedback(''); await loadDefinition();
  }
  function ambiguous(error: unknown) {
    uncertain = error instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(error.code);
    feedback(message(error) + (uncertain ? ' Completion is uncertain. Do not repeat this change. Read the current definition below and verify whether it was applied.' : ''), true);
    if (!uncertain) return;
    const change = submitted!;
    const recovery = control('recovery'); recovery.hidden = false;
    recovery.innerHTML = `<h3>Verify uncertain change</h3>${pair('Submitted change', change.kind === 'save' ? `Set ${change.component} to ${change.quantity_per} per ${change.parent}` : `Remove ${change.component} from ${change.parent}`)}<p class="help">Your entries are preserved. Read the authoritative definition before deciding.</p><button class="btn" data-bom-recovery="read">Read current definition</button><div class="recovery-records" role="status" aria-live="polite"></div>`;
  }
  async function mutate(change: Change) {
    if (pending || uncertain) return;
    pending = true; submitted = { ...change }; ++version; lock(); result(''); feedback(change.kind === 'save' ? 'Saving…' : 'Removing…');
    if (dialog().open) { control<HTMLButtonElement>('remove-confirm').disabled = true; control<HTMLButtonElement>('remove-cancel').disabled = true; }
    try {
      const api = getAPI();
      if (change.kind === 'save') {
        const saved = await read(api.save_bom_component({ parent: change.parent, component: change.component, quantity_per: change.quantity_per }));
        definition = saved.definition;
        result(`${saved.action === 'added' ? 'Added' : 'Updated'} ${change.component} at ${change.quantity_per} per ${change.parent}.`);
        select('component').value = ''; control<HTMLInputElement>('quantity').value = '';
      } else {
        definition = (await read(api.remove_bom_component({ parent: change.parent, component: change.component, confirmed: true }))).definition;
        result(`Removed ${change.component} from ${change.parent}.`);
      }
      feedback('');
    } catch (error) {
      ambiguous(error);
      // A rejected change leaves the draft intact; re-read so the displayed definition is current.
      if (!uncertain) void loadDefinition();
    } finally {
      pending = false; dialog().close(); control<HTMLButtonElement>('remove-confirm').disabled = false; control<HTMLButtonElement>('remove-cancel').disabled = false;
      lock(); render();
    }
  }
  async function reconcile() {
    if (!uncertain || pending || !submitted) return;
    const change = submitted;
    pending = true; reconciled = false; lock();
    const records = control('recovery').querySelector<HTMLElement>('.recovery-records')!;
    records.textContent = 'Reading authoritative definition…';
    try {
      definition = await read(getAPI().bom_definition(change.parent)); parent = change.parent; select('parent').value = parent;
      const current = definition.components.find(c => c.part_number === change.component);
      const matches = change.kind === 'save' ? current?.quantity_per === change.quantity_per : current === undefined;
      records.innerHTML = `${pair('Current definition', matches ? 'Matches the submitted change' : 'Does not match the submitted change')}${pair(`${change.component} per ${change.parent}`, current ? current.quantity_per : 'Not on this BOM')}<p class="help">Choose what happened. Nothing is retried automatically.</p><button class="btn" data-bom-recovery="applied">The change is applied</button> <button class="btn" data-bom-recovery="absent">The change was not applied</button>`;
      reconciled = true; render();
    } catch (error) { records.textContent = `${message(error)} Completion remains uncertain. Read again before taking action.`; }
    finally { pending = false; lock(); }
  }
  control('form').addEventListener('input', hint); control('form').addEventListener('change', hint);
  control('parent').addEventListener('change', () => { parent = select('parent').value; result(''); feedback(''); void loadDefinition(); });
  control('refresh').onclick = () => { void refresh(); };
  control('form').addEventListener('submit', event => {
    event.preventDefault();
    if (pending || uncertain || !parent) return;
    const quantity = control<HTMLInputElement>('quantity');
    if (!quantity.validity.valid || !Number.isSafeInteger(quantity.valueAsNumber)) { feedback('Quantity per parent must be a whole number between 1 and 2147483647.', true); return; }
    if (!select('component').value) { feedback('Select a component part.', true); return; }
    void mutate({ kind: 'save', parent, component: select('component').value, quantity_per: quantity.valueAsNumber });
  });
  control('definition').addEventListener('click', event => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button');
    if (!button || pending || uncertain) return;
    if (button.dataset.bomOpen) { select('parent').value = button.dataset.bomOpen; select('parent').dispatchEvent(new Event('change')); }
    if (button.dataset.bomEdit) { select('component').value = button.dataset.bomEdit; control<HTMLInputElement>('quantity').value = button.dataset.quantity ?? ''; hint(); control('quantity').focus(); }
    if (button.dataset.bomRemove) {
      removeTrigger = button; const number = button.dataset.bomRemove;
      const item = definition?.components.find(c => c.part_number === number);
      control('remove-data').innerHTML = pair('Parent', parent) + pair('Component', number) + pair('Quantity per parent', item?.quantity_per ?? '') + '<p class="help">Only this link is removed. Stock and past shipment snapshots are not changed. A reviewed BOM shipment that depends on it must be reviewed again.</p>';
      dialog().showModal(); control('remove-cancel').focus();
    }
  });
  control('recovery').onclick = event => {
    const action = (event.target as HTMLElement).closest<HTMLButtonElement>('button')?.dataset.bomRecovery;
    if (action === 'read') void reconcile();
    if (!reconciled || !submitted || (action !== 'applied' && action !== 'absent')) return;
    const change = submitted;
    uncertain = false; reconciled = false; control('recovery').hidden = true;
    if (action === 'applied') {
      select('component').value = ''; control<HTMLInputElement>('quantity').value = '';
      feedback(''); result(`Verified ${change.kind === 'save' ? 'update of' : 'removal of'} ${change.component} on ${change.parent}.`);
    } else feedback('You verified the change was not applied. Review the preserved draft before submitting again.');
    lock(); render();
  };
  control('remove-cancel').onclick = () => { if (!pending) dialog().close(); };
  dialog().addEventListener('cancel', event => { if (pending) event.preventDefault(); });
  dialog().addEventListener('close', () => { const target = removeTrigger?.isConnected ? removeTrigger : control('component'); target.focus({ preventScroll: true }); });
  control('remove-confirm').onclick = () => { const number = removeTrigger?.dataset.bomRemove; if (number && parent) void mutate({ kind: 'remove', parent, component: number }); };

  return {
    async open(number?: string) {
      if (number && !uncertain && !pending) { if (!Array.from(select('parent').options).some(o => o.value === number)) select('parent').insertAdjacentHTML('beforeend', `<option value="${esc(number)}">${esc(number)}</option>`); select('parent').value = number; }
      await refresh(); lock();
    },
    leave() { if (!pending) { ++version; if (dialog().open) dialog().close(); } },
  };
}
