import { $, esc, pair, status, message } from './presentation';
import { read, RequestError, type ready, type ImportKind, type ImportReview, type ImportResult } from './bridge';

type API = Awaited<ReturnType<typeof ready>>;

// Kind, selection and posting stay behind the typed API. Future import kinds
// share this review lifecycle while keeping their validation in Python.
export function importWorkflow(getAPI: () => API, operator: () => string, changed: () => Promise<void>, kind: ImportKind = 'parts') {
  $('#settings').insertAdjacentHTML('beforeend', `<div class="panel settings-panel"><div class="panel-head"><div><h2>Parts CSV import</h2><p>Preview catalog changes, then confirm. Every import requires a verified backup.</p></div></div><div class="panel-body"><p>Fields: part_number, description, default_location, minimum_quantity, active. Existing Part numbers are updated; other rows create Parts. Stock and History are preserved.</p><div id="import-review"></div><div id="import-result" aria-live="polite"></div><div id="import-actions" class="settings-actions"></div></div></div>`);
  let review: ImportReview | null = null;
  let pending = false;
  let uncertain = false;
  let recovered: ImportReview | null = null;
  let confirmed = false;
  let resultText = '';
  let error = false;

  function render() {
    const preview = review?.preview;
    $('#import-review').innerHTML = preview ? `${pair('Selected CSV', preview.path)}${pair('Data rows', preview.row_count)}${pair('Valid rows', preview.valid_count)}${pair('Commit eligibility', preview.can_import ? 'Eligible after confirmation' : 'Blocked — correct the errors and select again')}${preview.errors.length || preview.warnings.length ? `<div class="table-scroll"><table><thead><tr><th>Level</th><th>Row</th><th>Field</th><th>Issue</th></tr></thead><tbody>${[...preview.errors, ...preview.warnings].map(issue => `<tr><td>${esc(issue.level)}</td><td>${issue.row_number}</td><td>${esc(issue.field || 'File')}</td><td>${esc(issue.message)}</td></tr>`).join('')}</tbody></table></div>` : status('No row errors or warnings.')}` : '';
    $('#import-result').innerHTML = resultText ? status(resultText, error) : '';
    $('#import-actions').innerHTML = `<button class="btn" data-import="select" ${pending || uncertain ? 'disabled' : ''}>Select Parts CSV</button>${review?.state === 'reviewed' && !uncertain ? `<label><input id="import-confirm" type="checkbox" ${confirmed ? 'checked' : ''} ${pending || !preview?.can_import ? 'disabled' : ''}> I confirm the catalog changes and required backup.</label><button class="btn primary" data-import="commit" ${pending || !confirmed || !preview?.can_import ? 'disabled' : ''}>Commit Parts import</button>` : ''}${uncertain ? `<button class="btn" data-import="recover" ${pending ? 'disabled' : ''}>Check import outcome</button>${recovered ? `<button class="btn primary" data-import="resolve">${recovered.state === 'completed' ? 'Accept completed import' : 'Keep input and allow a new review'}</button>` : ''}` : ''}`;
  }
  async function refresh() {
    try { await changed(); }
    catch { resultText += ' The catalog refresh failed. Use Refresh to read current data.'; }
  }
  function completed(result: ImportResult) {
    if (review) { review.state = 'completed'; review.result = result; }
    confirmed = false;
    resultText = `Parts import completed: ${result.rows_imported} rows imported. Backup: ${result.backup_path}`;
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
        recovered = await read(getAPI().import_status(review.review_id));
        resultText = recovered.state === 'completed' && recovered.result ? `Python reports ${recovered.result.rows_imported} rows imported. Backup: ${recovered.result.backup_path}. Accept this outcome to unlock selection.` : 'No completed import reported. Inspect the catalog and backups, then allow a new review.';
        await refresh();
      }
    } catch (failure) {
      error = true;
      resultText = message(failure);
      if (action === 'commit') {
        confirmed = false;
        uncertain = failure instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(failure.code);
        if (uncertain) { recovered = null; resultText += ' Completion is uncertain. Input retained; submission locked. Check the outcome before deciding.'; }
        else if (review && failure instanceof RequestError && ['STALE', 'FILE_ERROR', 'VALIDATION'].includes(failure.code)) { review.state = 'failed'; resultText += ' Input is preserved. Correct the problem and select the CSV for a new review.'; }
      }
    } finally { pending = false; render(); }
  }
  $('#import-actions').addEventListener('change', () => { confirmed = $<HTMLInputElement>('#import-confirm').checked; render(); $<HTMLInputElement>('#import-confirm').focus(); });
  $('#import-actions').addEventListener('click', event => {
    const action = (event.target as HTMLElement).closest<HTMLElement>('[data-import]')?.dataset.import;
    if (!action || pending) return;
    if (action === 'resolve' && recovered) {
      if (recovered.result) completed(recovered.result);
      else { if (review) review.state = 'failed'; resultText = 'Input retained. Select the CSV to validate and review it again.'; error = false; }
      uncertain = false; recovered = null; render();
    } else if (action === 'recover' || (!uncertain && (action === 'select' || (action === 'commit' && confirmed && review?.state === 'reviewed' && review.preview.can_import)))) void perform(action);
  });
  render();
}
