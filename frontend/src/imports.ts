import { $, esc, pair, status, message } from './presentation';
import { read, RequestError, type ready, type ImportKind, type ImportReview, type ImportResult } from './bridge';

type API = Awaited<ReturnType<typeof ready>>;

// Presentation only: selection, validation and posting stay behind the typed API.
const copy: Record<ImportKind, { title: string; summary: string; fields: string; select: string; confirm: string; commit: string; done: string; inspect: string }> = {
  parts: {
    title: 'Parts CSV import', summary: 'Preview catalog changes, then confirm. Every import requires a verified backup.',
    fields: 'Fields: part_number, description, default_location, minimum_quantity, active. Existing Part numbers are updated; other rows create Parts. Stock and History are preserved.',
    select: 'Select Parts CSV', confirm: 'I confirm the catalog changes and required backup.', commit: 'Commit Parts import', done: 'Parts import completed', inspect: 'catalog',
  },
  inventory: {
    title: 'Inventory receipt CSV import', summary: 'Preview receipts, then confirm. Every import requires a verified backup.',
    fields: 'Required: part_number, location, lot_number (a real Lot), quantity. Optional: reference (defaults to "CSV import"), notes. Each row posts a RECEIVE to the Stock ledger, attributed to the current operator. Committing the same file again receives the stock again.',
    select: 'Select Inventory CSV', confirm: 'I confirm these receipts and the required backup.', commit: 'Commit Inventory import', done: 'Inventory import completed', inspect: 'Stock and History',
  },
  bom: {
    title: 'BOM CSV import', summary: 'Preview BOM definition changes, then confirm. Every import requires a verified backup.',
    fields: 'Required: parent_part_number, component_part_number, quantity_per. Parent and component Parts must exist and be active. Rows add direct links or update the quantity of existing links; links not in the file are kept and none are removed. Self-references, cycles and invalid quantities are blocked. Stock, History and past shipment snapshots are not changed; a reviewed BOM shipment affected by a changed definition must be reviewed again.',
    select: 'Select BOM CSV', confirm: 'I confirm these BOM definition changes and the required backup.', commit: 'Commit BOM import', done: 'BOM import completed', inspect: 'BOM definitions',
  },
};

export function importWorkflow(getAPI: () => API, operator: () => string, changed: () => Promise<void>, kind: ImportKind) {
  const text = copy[kind];
  const id = (part: string) => `#${kind}-import-${part}`;
  $('#settings').insertAdjacentHTML('beforeend', `<div class="panel settings-panel"><div class="panel-head"><div><h2>${text.title}</h2><p>${text.summary}</p></div></div><div class="panel-body"><p>${esc(text.fields)}</p><div id="${kind}-import-review"></div><div id="${kind}-import-result" aria-live="polite"></div><div id="${kind}-import-actions" class="settings-actions"></div></div></div>`);
  let review: ImportReview | null = null;
  let pending = false;
  let uncertain = false;
  let recovered: ImportReview | null = null;
  let confirmed = false;
  let resultText = '';
  let error = false;
  const ready = () => confirmed && review?.state === 'reviewed' && review.preview.can_import && !!operator().trim();

  function render() {
    const preview = review?.preview;
    $(id('review')).innerHTML = preview ? `${pair('Selected CSV', preview.path)}${pair('Data rows', preview.row_count)}${pair('Valid rows', preview.valid_count)}${pair('Commit eligibility', preview.can_import ? 'Eligible after confirmation' : 'Blocked — correct the errors and select again')}${preview.errors.length || preview.warnings.length ? `<div class="table-scroll"><table><thead><tr><th>Level</th><th>Row</th><th>Field</th><th>Issue</th></tr></thead><tbody>${[...preview.errors, ...preview.warnings].map(issue => `<tr><td>${esc(issue.level)}</td><td>${issue.row_number}</td><td>${esc(issue.field || 'File')}</td><td>${esc(issue.message)}</td></tr>`).join('')}</tbody></table></div>` : status('No row errors or warnings.')}` : '';
    $(id('result')).innerHTML = resultText ? status(resultText, error) : '';
    const reviewed = review?.state === 'reviewed' && !uncertain;
    $(id('actions')).innerHTML = `<button class="btn" data-import="select" ${pending || uncertain ? 'disabled' : ''}>${text.select}</button>${reviewed ? `<label><input id="${kind}-import-confirm" type="checkbox" ${confirmed ? 'checked' : ''} ${pending || !preview?.can_import ? 'disabled' : ''}> ${text.confirm}</label><button class="btn primary" data-import="commit" ${pending || !ready() ? 'disabled' : ''}>${text.commit}</button>${preview?.can_import && !operator().trim() ? '<span class="help">Enter your operator name before committing.</span>' : ''}` : ''}${uncertain ? `<button class="btn" data-import="recover" ${pending ? 'disabled' : ''}>Check import outcome</button>${recovered ? `<button class="btn primary" data-import="resolve">${recovered.state === 'completed' ? 'Accept completed import' : 'Keep input and allow a new review'}</button>` : ''}` : ''}`;
  }
  async function refresh() {
    try { await changed(); }
    catch { resultText += ` The ${text.inspect} refresh failed. Use Refresh to read current data.`; }
  }
  function completed(result: ImportResult) {
    if (review) { review.state = 'completed'; review.result = result; }
    confirmed = false;
    resultText = `${text.done}: ${result.rows_imported} rows imported. Backup: ${result.backup_path}`;
    error = false;
  }
  async function perform(action: string) {
    if (pending) return;
    pending = true;
    if (action === 'recover') recovered = null;
    error = false;
    resultText = action === 'select' ? 'Selecting CSV…' : action === 'recover' ? 'Reading outcome…' : 'Validating and backing up…';
    render();
    try {
      if (action === 'select') {
        const selected = await read(getAPI().select_import(kind));
        if (selected.cancelled) resultText = 'Selection cancelled. Previous review retained.';
        else { review = selected; confirmed = false; resultText = 'Review counts and issues before confirming.'; }
      } else if (action === 'commit' && review) {
        const result = await read(getAPI().commit_import({ review_id: review.review_id, confirmed: true, operator: operator() }));
        completed(result);
        await refresh();
      } else if (action === 'recover' && review) {
        const outcome = await read(getAPI().import_status(review.review_id));
        // Offer a decision only after the authoritative reads succeed; any failure keeps the lock.
        await changed();
        recovered = outcome;
        resultText = outcome.state === 'completed' && outcome.result ? `Python reports ${outcome.result.rows_imported} rows imported. Backup: ${outcome.result.backup_path}. Accept this outcome to unlock selection.` : `No completed import reported. Inspect ${text.inspect} and backups, then allow a new review.`;
      }
    } catch (failure) {
      error = true;
      resultText = message(failure);
      if (action === 'recover') resultText += ' Submission stays locked until the outcome and current data are read.';
      if (action === 'commit') {
        confirmed = false;
        uncertain = failure instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(failure.code);
        if (uncertain) { recovered = null; resultText += ' Completion is uncertain. Input retained; submission locked. Check the outcome before deciding.'; }
        else if (review && failure instanceof RequestError && ['STALE', 'FILE_ERROR', 'VALIDATION'].includes(failure.code)) { review.state = 'failed'; resultText += ' Input is preserved. Correct the problem and select the CSV for a new review.'; }
      }
    } finally { pending = false; render(); }
  }
  $(id('actions')).addEventListener('change', () => { confirmed = $<HTMLInputElement>(id('confirm')).checked; render(); $<HTMLInputElement>(id('confirm')).focus(); });
  $(id('actions')).addEventListener('click', event => {
    const action = (event.target as HTMLElement).closest<HTMLElement>('[data-import]')?.dataset.import;
    if (!action || pending) return;
    if (action === 'resolve' && recovered) {
      if (recovered.result) completed(recovered.result);
      else { if (review) review.state = 'failed'; resultText = 'Input retained. Select the CSV to validate and review it again.'; error = false; }
      uncertain = false; recovered = null; render();
    } else if (action === 'recover' || (!uncertain && (action === 'select' || (action === 'commit' && ready())))) void perform(action);
  });
  render();
  return { operatorChanged: () => { if (!pending) render(); } };
}
