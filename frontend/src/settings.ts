import { read, RequestError, type ready, type BackupInfo, type ExportKind, type Folder, type UtilityContext } from './bridge';

type API = Awaited<ReturnType<typeof ready>>;
const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const pair = (label: string, value: unknown) => `<div class="detail-pair"><span>${esc(label)}</span><strong>${esc(value || '—')}</strong></div>`;
const status = (text: string, error = false) => `<div class="status ${error ? 'error' : ''}" role="${error ? 'alert' : 'status'}">${esc(text)}</div>`;
const success = (text: string) => `<div class="status success" role="status">${esc(text)}</div>`;
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';
const size = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
const describe = (backup: BackupInfo) => `${backup.name} · ${backup.modified} · ${size(backup.size_bytes)}`;
const exportLabels: Record<ExportKind, string> = { parts: 'Parts', inventory: 'Inventory', transactions: 'Transactions', shipments: 'Shipments', bom: 'BOM definitions' };

export function settingsWorkflow(getAPI: () => API) {
  let version = 0;
  let pending = false;
  const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
  $('main').insertAdjacentHTML('beforeend', `<section id="settings" hidden><div class="page-heading"><div><h1>Settings</h1><p>CSV exports, backups and folders for the inventory selected at launch.</p></div><button id="settings-refresh" class="btn" disabled>Refresh</button></div><div id="settings-result" aria-live="polite"></div><div id="settings-data">${status('Connecting to the desktop…')}</div></section>`);

  function render(context: UtilityContext) {
    const latest = context.latest_backup;
    $('#settings-data').innerHTML = `<div class="panel"><div class="panel-head"><div><h2>Inventory location</h2><p>Backups, exports and logs stay beside the selected database.</p></div></div><div class="panel-body">${pair('Database', context.database)}${pair('Backups folder', context.backup_dir)}${pair('Exports folder', context.export_dir)}${pair('Logs folder', context.log_dir)}</div></div>
<div class="panel settings-panel"><div class="panel-head"><div><h2>Backup</h2><p>The latest ${context.backup_retention} backups are kept. A startup backup is also written each launch.</p></div><button class="btn primary" data-backup-create ${context.database_exists ? '' : 'disabled'}>Create backup</button></div><div class="panel-body">${context.database_exists ? '' : status(`No database file was found at ${context.database}. A backup cannot be created.`, true)}${context.backup_error ? status(context.backup_error, true) : pair('Latest backup', latest ? describe(latest) : 'No backup found yet')}${pair('Backups on disk', context.backup_error ? '' : String(context.backup_count))}</div></div>
<div class="panel settings-panel"><div class="panel-head"><div><h2>CSV exports</h2><p>Export one CSV from this inventory. Inventory and audit files retain Lot trace.</p></div></div><div class="panel-body">${pair('Destination', context.export_dir)}<div class="settings-actions">${Object.entries(exportLabels).map(([kind, label]) => `<button class="btn" data-export-kind="${kind}">Export ${label}</button>`).join('')}</div></div></div>
<div class="panel settings-panel"><div class="panel-head"><div><h2>Folders</h2><p>Open a folder in your system file manager.</p></div><div class="settings-actions"><button class="btn" data-open-folder="backups">Open backups folder</button><button class="btn" data-open-folder="exports">Open exports folder</button></div></div></div>`;
    if (pending) lockControls();
  }
  function lockControls() {
    document.querySelectorAll<HTMLButtonElement>('#settings button').forEach(button => { button.disabled = true; });
  }
  async function load() {
    const current = ++version;
    try {
      const context = await read(getAPI().utility_context());
      if (current === version) render(context);
    } catch (error) {
      if (current === version) {
        $('#settings-data').innerHTML = `${status(message(error), true)}<button class="btn" data-settings-retry>Retry</button>`;
        if (pending) lockControls();
      }
    }
  }
  async function perform<T>(trigger: string, label: string, action: () => Promise<T>, done: (value: T) => string, recovery = 'The current backups are shown below; check them before trying again.') {
    if (pending) return;
    pending = true;
    lockControls();
    $('#settings-result').innerHTML = status(`${label}…`);
    try { $('#settings-result').innerHTML = success(done(await action())); }
    catch (error) {
      const uncertain = error instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(error.code);
      $('#settings-result').innerHTML = status(message(error) + (uncertain ? ` Completion is uncertain. ${recovery}` : ''), true);
    }
    finally {
      pending = false; $<HTMLButtonElement>('#settings-refresh').disabled = false;
      await load();
      if (!$('#settings').hidden) document.querySelector<HTMLElement>(trigger)?.focus();
    }
  }
  $('#settings').addEventListener('click', event => {
    const target = (event.target as HTMLElement).closest<HTMLElement>('button');
    if (!target || pending) return;
    if (target.hasAttribute('data-settings-retry') || target.id === 'settings-refresh') { $('#settings-result').innerHTML = ''; void load(); }
    if (target.hasAttribute('data-backup-create')) {
      void perform('[data-backup-create]', 'Creating backup', () => read(getAPI().create_backup()), result => `Backup created: ${describe(result.created)}`);
    }
    if (target.dataset.exportKind) {
      const kind = target.dataset.exportKind as ExportKind;
      void perform(`[data-export-kind="${kind}"]`, `Exporting ${exportLabels[kind]}`, () => read(getAPI().export_csv(kind)), result => `Exported ${exportLabels[result.kind]}: ${result.rows_exported} rows. File: ${result.path}`, 'Open the exports folder and inspect the files before trying again.');
    }
    if (target.dataset.openFolder) {
      const folder = target.dataset.openFolder as Folder;
      void perform(`[data-open-folder="${folder}"]`, 'Opening folder', () => read(getAPI().open_folder(folder)), result => `Opened ${result.folder}`, 'Check your system file manager before trying again.');
    }
  });
  return {
    open: () => load(),
  };
}
