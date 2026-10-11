import { read, RequestError, type ready, type PartDetail, type UpdatePart } from './bridge';

type API = Awaited<ReturnType<typeof ready>>;
const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const status = (text: string, error = false) => `<div class="status ${error ? 'error' : ''}" role="${error ? 'alert' : 'status'}">${esc(text)}</div>`;
const pair = (label: string, value: unknown) => `<div class="detail-pair"><span>${esc(label)}</span><strong>${esc(value || '—')}</strong></div>`;
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';
const ambiguous = (error: unknown) => error instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(error.code);

interface Hooks {
  show(part: PartDetail): void;
  refresh(): Promise<void>;
  notice(text: string, error?: boolean): void;
}
// What an unconfirmed outcome should look like once the operator reads it back.
interface Pending { title: string; submitted: string; resumeLabel: string; applied(part: PartDetail): boolean; resume(part: PartDetail): void; accept(part: PartDetail): void }

/** Edit, deactivate and reactivate Parts inside the Part drawer. Python stays the authority. */
export function partEditor(getAPI: () => API, hooks: Hooks) {
  const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
  $('#app').insertAdjacentHTML('afterend', `<dialog id="confirm-dialog" aria-labelledby="confirm-title"><div class="dialog-heading"><h2 id="confirm-title"></h2></div><div class="dialog-body"><p id="confirm-body" class="description"></p><div class="dialog-actions"><button id="confirm-cancel" class="btn" type="button"></button><button id="confirm-accept" class="btn primary" type="button"></button></div></div></dialog>`);
  let editing: PartDetail | null = null;
  let busy = false;
  let uncertain: Pending | null = null;
  const drawer = () => $('#drawer-data');
  const form = () => document.querySelector<HTMLFormElement>('#part-edit');
  const values = () => ({
    description: $<HTMLInputElement>('#edit-description').value,
    minimum_quantity: Number($<HTMLInputElement>('#edit-minimum').value),
    location: $<HTMLSelectElement>('#edit-location').value,
  });
  const isDirty = () => {
    if (!editing || !form()) return false;
    const now = values();
    return now.description !== editing.description || now.minimum_quantity !== editing.minimum_quantity || now.location !== editing.location;
  };

  function confirm(title: string, body: string, accept: string, cancel: string): Promise<boolean> {
    const dialog = $<HTMLDialogElement>('#confirm-dialog');
    $('#confirm-title').textContent = title; $('#confirm-body').textContent = body;
    $('#confirm-accept').textContent = accept; $('#confirm-cancel').textContent = cancel;
    return new Promise(resolve => {
      const finish = (answer: boolean) => { dialog.removeEventListener('close', dismissed); resolve(answer); dialog.close(); };
      // Escape keeps the safe state. Close events are queued, so a stale one can arrive after reopening.
      const dismissed = () => { if (!dialog.open) resolve(false); };
      $('#confirm-accept').onclick = () => finish(true);
      $('#confirm-cancel').onclick = () => finish(false);
      dialog.addEventListener('close', dismissed, { once: true });
      dialog.showModal();
      $('#confirm-cancel').focus();
    });
  }

  function lock(locked: boolean) {
    form()?.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>('input, select, button').forEach(control => { control.disabled = locked; });
    if (!locked) syncSave();
  }
  function syncSave() { const save = document.querySelector<HTMLButtonElement>('#part-save'); if (save) save.disabled = busy || !!uncertain || !isDirty(); }

  async function edit(part: PartDetail) {
    if (busy) return;
    editing = part;
    let locations: string[];
    try { locations = await read(getAPI().locations()); }
    catch (error) { editing = null; hooks.notice(message(error), true); return; }
    if (!locations.includes(part.location)) locations = [part.location, ...locations];
    drawer().innerHTML = `<form id="part-edit" class="dialog-body" novalidate><div class="review-part">${esc(part.part_number)}</div><p class="help">The part number cannot be changed.</p><div class="form-grid" style="margin-top:16px">
<div class="field full"><label for="edit-description">Description <span class="required">*</span></label><input id="edit-description" required value="${esc(part.description)}"></div>
<div class="field"><label for="edit-minimum">Minimum quantity <span class="required">*</span></label><input id="edit-minimum" type="number" min="0" max="2147483647" step="1" required value="${part.minimum_quantity}"></div>
<div class="field"><label for="edit-location">Default location <span class="required">*</span></label><select id="edit-location" required>${locations.map(l => `<option ${l === part.location ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div></div>
<div id="part-edit-feedback" role="alert"></div><div class="dialog-actions"><button id="part-cancel" class="btn" type="button">Cancel</button><button id="part-save" class="btn primary" disabled>Save changes</button></div><div id="part-recovery" hidden></div></form>`;
    form()!.addEventListener('input', syncSave);
    form()!.addEventListener('submit', event => { event.preventDefault(); void save(); });
    $('#part-cancel').onclick = () => void discard();
    $('#edit-description').focus();
  }

  async function discard() {
    if ((isDirty() || uncertain) && !await confirm('Discard unsaved edits?', uncertain ? 'The outcome of your last save is unconfirmed. Discarding forgets your entries; reopen the part to read its current values.' : 'Your changes to this part have not been saved.', 'Discard edits', 'Keep editing')) return;
    const previous = editing!; leave(); hooks.show(await current(previous));
  }
  async function current(fallback: PartDetail) {
    try { return await read(getAPI().part_detail(fallback.part_number)); }
    catch (error) { hooks.notice(`${message(error)} Showing the last loaded values.`, true); return fallback; }
  }
  function leave() { editing = null; uncertain = null; busy = false; }

  async function save() {
    const f = form();
    if (busy || uncertain || !f || !editing) return;
    if (!f.reportValidity()) return;
    const request: UpdatePart = { part_number: editing.part_number, ...values() };
    busy = true; lock(true); $('#part-edit-feedback').innerHTML = '';
    try {
      const part = await read(getAPI().update_part(request));
      leave(); hooks.show(part); hooks.notice(`Saved ${part.part_number}.`);
      await hooks.refresh();
    } catch (error) {
      busy = false;
      if (ambiguous(error)) {
        $('#part-edit-feedback').innerHTML = status(`${message(error)} The save may or may not have completed. Your entries are preserved and locked. Read the current part before deciding.`, true);
        hold({
          title: 'Verify uncertain save',
          submitted: pair('Description', request.description) + pair('Minimum quantity', request.minimum_quantity) + pair('Default location', request.location),
          applied: part => part.description === request.description.trim() && part.minimum_quantity === request.minimum_quantity && part.location === request.location,
          resumeLabel: 'Edit again',
          resume: () => { uncertain = null; $('#part-recovery').hidden = true; lock(false); $('#part-edit-feedback').innerHTML = status('Review your preserved entries, then save again.'); $('#edit-description').focus(); },
          accept: part => { leave(); hooks.show(part); void hooks.refresh(); },
        });
      } else { lock(false); $('#part-edit-feedback').innerHTML = status(message(error), true); }
    }
  }

  // Locks the draft until the operator reads authoritative state and explicitly decides.
  function hold(pending: Pending) {
    uncertain = pending; lock(true);
    const panel = $('#part-recovery'); panel.hidden = false;
    panel.innerHTML = `<h3>${esc(pending.title)}</h3>${pending.submitted}<button class="btn" type="button" data-recovery="read">Read current part</button><div class="recovery-records" role="status" aria-live="polite"></div>`;
    panel.querySelector<HTMLButtonElement>('[data-recovery=read]')!.onclick = () => void reconcile();
    panel.querySelector<HTMLButtonElement>('[data-recovery=read]')!.focus();
  }
  async function reconcile() {
    const pending = uncertain; if (!pending || busy) return;
    const records = $('#part-recovery .recovery-records'); busy = true;
    try {
      const part = await read(getAPI().part_detail(editing!.part_number));
      const done = pending.applied(part);
      records.innerHTML = `${status(done ? 'The change was saved.' : 'The change was not applied.')}${pair('Current description', part.description)}${pair('Current minimum', part.minimum_quantity)}${pair('Current default location', part.location)}${pair('State', part.active ? 'Active' : 'Inactive')}<div class="dialog-actions">${done ? '<button class="btn primary" type="button" data-decision="accept">Use saved part</button>' : `<button class="btn primary" type="button" data-decision="resume">${esc(pending.resumeLabel)}</button><button class="btn" type="button" data-decision="accept">Discard my entries</button>`}</div>`;
      records.querySelector<HTMLButtonElement>('[data-decision=accept]')!.onclick = () => pending.accept(part);
      records.querySelector<HTMLButtonElement>('[data-decision=resume]')?.addEventListener('click', () => pending.resume(part));
      records.querySelector<HTMLButtonElement>('.btn')!.focus();
    } catch (error) { records.textContent = `${message(error)} The outcome is still uncertain and your entries stay locked. Read again.`; }
    finally { busy = false; }
  }

  async function setActive(part: PartDetail, active: boolean) {
    if (busy || editing) return;
    const buttons = () => drawer().querySelectorAll<HTMLButtonElement>('button');
    const change = async (confirmed: boolean) => {
      busy = true; buttons().forEach(button => { button.disabled = true; });
      try {
        const updated = await read(getAPI().set_part_active({ part_number: part.part_number, active, confirm_stock: confirmed }));
        busy = false; hooks.show(updated);
        hooks.notice(`${updated.part_number} ${active ? 'reactivated' : 'deactivated'}.`);
        await hooks.refresh();
      } catch (error) {
        busy = false;
        if (error instanceof RequestError && error.code === 'CONFIRMATION_REQUIRED') {
          buttons().forEach(button => { button.disabled = false; });
          if (await confirm('Deactivate part with stock?', error.message, 'Deactivate part', 'Keep active')) await change(true);
        } else if (ambiguous(error)) {
          editing = part;
          drawer().innerHTML = `<form id="part-edit" class="dialog-body"><div class="review-part">${esc(part.part_number)}</div><div id="part-edit-feedback" role="alert">${status(`${message(error)} The change may or may not have completed. Read the current part before deciding.`, true)}</div><div id="part-recovery" hidden></div></form>`;
          hold({
            title: `Verify uncertain ${active ? 'reactivation' : 'deactivation'}`,
            submitted: pair('Requested state', active ? 'Active' : 'Inactive'),
            resumeLabel: 'Back to part',
            applied: latest => latest.active === active,
            resume: latest => { leave(); hooks.show(latest); },
            accept: updated => { leave(); hooks.show(updated); void hooks.refresh(); },
          });
        } else { buttons().forEach(button => { button.disabled = false; }); hooks.notice(message(error), true); }
      }
    };
    await change(false);
  }

  return {
    edit, setActive,
    /** True while the drawer holds a form, unsaved edits or an unconfirmed outcome. */
    active: () => !!editing,
    /** Asks before the drawer closes over unsaved work; resolves true when it may close. */
    async mayClose() {
      if (busy) return false;
      if (!editing || (!isDirty() && !uncertain)) return true;
      return confirm('Discard unsaved edits?', uncertain ? 'The outcome of your last change is unconfirmed. Closing forgets your entries; reopen the part to read its current values.' : 'Your changes to this part have not been saved.', 'Discard edits', 'Keep editing');
    },
    reset: leave,
  };
}
