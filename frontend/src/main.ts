import './styles.css';
import { createIcons, Boxes, LayoutDashboard, Package, Moon, Sun, Plus, X, RefreshCw } from 'lucide';
import { ready, read, RequestError, type Search, type Part, type PartDetail, type Dashboard } from './bridge';

const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const icons = () => createIcons({ icons: { Boxes, LayoutDashboard, Package, Moon, Sun, Plus, X, RefreshCw } });
const icon = (name: string) => `<i data-lucide="${name}" aria-hidden="true"></i>`;
const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
const message = (error: unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';
const status = (text: string, error = false) => `<div class="status ${error ? 'error' : ''}" role="${error ? 'alert' : 'status'}">${esc(text)}</div>`;
const badges = (part: Part) => `<span class="badge ${part.active ? 'good' : 'neutral'}">${part.active ? 'Active' : 'Inactive'}</span> ${part.low_stock ? '<span class="badge warn">Low stock</span>' : ''}`;
const search: Search = { query: '', status: 'all', low_stock: false, sort: 'part_number', descending: false };
let api: Awaited<ReturnType<typeof ready>>;
let page: 'dashboard' | 'parts' = 'dashboard';
let searchVersion = 0;
let dashboardVersion = 0;
let detailVersion = 0;
let selected = '';
let returnFocus: HTMLElement | null = null;
let drawerScroll = { x: 0, y: 0 };
let createReturnFocus: HTMLElement | null = null;
let creating = false;
let uncertain = false;
let submittedNumber = '';
let theme: 'light' | 'dark' = 'light';

$('#app').innerHTML = `<div class="app-shell"><aside class="sidebar" aria-label="Main navigation">
<div class="brand"><div class="brand-mark">${icon('boxes')}</div><div><strong>INVSYS</strong><small>INVENTORY CONTROL</small></div></div>
<nav><button class="nav-button active" data-page="dashboard" aria-label="Dashboard" aria-current="page">${icon('layout-dashboard')}<span>Dashboard</span></button><div class="nav-group eyebrow">Catalog</div><button class="nav-button" data-page="parts" aria-label="Parts">${icon('package')}<span>Parts</span></button></nav>
<div class="sidebar-bottom"><button id="theme" class="nav-button" disabled aria-label="Switch to dark mode">${icon('moon')}<span>Dark mode</span></button><div class="local-status">LOCAL-FIRST · SQLITE</div></div></aside>
<div class="workspace"><header class="topbar"><div class="breadcrumb">Workspace / <strong id="page-name">Dashboard</strong></div>
<div class="header-actions"><button id="global-search" class="btn">Search parts</button><form id="operator-form" class="operator"><div><label for="operator">Operator</label><input id="operator" name="operator" placeholder="Your name" disabled></div><button id="save-operator" class="btn small" disabled>Save</button></form></div></header>
<div id="notice" role="status" aria-live="polite"></div><main>
<section id="dashboard"><div class="page-heading"><div><h1>Dashboard</h1><p>Attention first. Current inventory, at a glance.</p></div><button class="btn refresh" disabled>${icon('refresh-cw')}Refresh</button></div><div id="dashboard-data">${status('Connecting to the desktop…')}</div></section>
<section id="parts" hidden><div class="page-heading"><div><h1>Parts</h1><p>Search the catalog and inspect stock by location and lot.</p></div><button id="add-part" class="btn primary" disabled>${icon('plus')}New part</button></div>
<div class="panel"><div class="toolbar"><label class="search-input"><span class="sr-only">Search by number or description</span><input id="query" placeholder="Search number or description"></label>
<label>Status <select id="filter-status" class="select-input"><option value="all">All parts</option><option value="active">Active</option><option value="inactive">Inactive</option></select></label><label><input id="filter-low" type="checkbox">Low stock only</label>
<label>Sort <select id="sort" class="select-input"><option value="part_number">Part number</option><option value="description">Description</option><option value="quantity">Stock</option><option value="minimum_quantity">Minimum</option></select></label><label><input id="descending" type="checkbox">Descending</label><button id="clear" class="btn small">Clear filters</button><button class="btn small refresh" disabled>Refresh</button></div><div id="filter-state" class="filter-chips" role="status"></div><div id="parts-data">${status('Connecting to the desktop…')}</div></div></section>
</main></div></div>
<dialog id="drawer" class="drawer" aria-labelledby="drawer-title"><div class="dialog-heading"><h2 id="drawer-title">Part details</h2><button id="close-drawer" class="icon-btn" aria-label="Close part details">${icon('x')}</button></div><div id="drawer-data"></div></dialog>
<dialog id="create-dialog" aria-labelledby="create-title"><div class="dialog-heading"><h2 id="create-title">New part</h2><button id="close-create" class="icon-btn" aria-label="Close new part">${icon('x')}</button></div><form id="new-part" class="dialog-body"><div class="form-grid">
<div class="field"><label for="number">Part number <span class="required">*</span></label><input id="number" name="part_number" required></div>
<div class="field"><label for="minimum">Minimum quantity <span class="required">*</span></label><input id="minimum" name="minimum_quantity" type="number" min="0" max="2147483647" step="1" value="0" required></div>
<div class="field full"><label for="description">Description <span class="required">*</span></label><input id="description" name="description" required></div>
<div class="field full"><label for="location">Default location <span class="required">*</span></label><select id="location" name="location" required></select></div></div>
<div id="create-error" role="alert"></div><button id="create-submit" class="btn primary">Create part</button></form></dialog>`;
icons();

// Native dialog focus can otherwise escape into the Qt browser chrome on Tab.
for (const dialog of document.querySelectorAll<HTMLDialogElement>('dialog')) {
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const controls = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]')).filter(element => element.getClientRects().length > 0);
    const first = controls[0]; const last = controls.at(-1);
    if (!first) { event.preventDefault(); return; }
    if (!dialog.contains(document.activeElement) || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
      event.preventDefault(); (event.shiftKey ? last : first)?.focus();
    }
  });
}

function notice(text: string, error = false) {
  $('#notice').textContent = text;
  $('#notice').className = error ? 'alert error' : 'alert success';
}
function navigate(next: typeof page, refresh = true) {
  page = next;
  $('#dashboard').hidden = next !== 'dashboard'; $('#parts').hidden = next !== 'parts';
  $('#page-name').textContent = next === 'dashboard' ? 'Dashboard' : 'Parts';
  document.querySelectorAll<HTMLElement>('[data-page]').forEach(button => {
    button.classList.toggle('active', button.dataset.page === next);
    if (button.dataset.page === next) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  if (api && refresh) void (next === 'dashboard' ? loadDashboard() : loadParts());
}
async function loadDashboard() {
  const version = ++dashboardVersion;
  $('#dashboard-data').innerHTML = status('Loading current dashboard…');
  try {
    const data: Dashboard = await read(api.dashboard());
    if (version !== dashboardVersion) return;
    $('#dashboard-data').innerHTML = `<div class="dashboard-grid"><div class="panel"><div class="panel-head"><div><h2>Needs attention</h2><p>Active parts at or below their minimum stock.</p></div><span class="badge warn">${data.low_stock.length} low</span></div>
${data.low_stock.length ? data.low_stock.slice(0, 5).map(p => `<div class="attention-row"><div><button class="part-id" data-part="${esc(p.part_number)}">${esc(p.part_number)}</button><div class="part-description description">${esc(p.description)}</div></div><div class="stock-meter"><strong>${p.quantity}</strong> / ${p.minimum_quantity} min</div><span aria-hidden="true">→</span></div>`).join('') : status('No low-stock parts.')} ${data.low_stock.length > 5 ? '<div class="panel-body"><button class="text-link" data-low-stock>View all low-stock parts →</button></div>' : ''}</div>
<div class="panel"><div class="panel-head"><h2>Quick actions</h2></div><div class="panel-body"><button class="btn primary" data-new>Create a part</button><div class="system-note">Receive, Ship, Move, Adjust, BOM, History, catalog editing, and operational Settings are deferred in this slice. Use the original application for these workflows.</div></div></div></div>
<div class="stats" style="margin-top:24px"><div class="panel stat"><div class="stat-title">Active parts</div><div class="stat-value">${data.active_parts}</div></div><div class="panel stat warning"><div class="stat-title">Low-stock parts</div><div class="stat-value">${data.low_stock.length}</div></div><div class="panel stat"><div class="stat-title">Recorded shipments</div><div class="stat-value">${data.shipment_count}</div></div></div>
<div class="panel activity-panel"><div class="panel-head"><h2>Recent activity</h2><span class="muted">History inspection is deferred</span></div>${data.activity.length ? data.activity.map(tx => `<div class="activity-item"><span class="badge">${esc(tx.tx_type)}</span><div><strong>${esc(tx.part_number)} · ${tx.quantity_change > 0 ? '+' : ''}${tx.quantity_change}</strong><p>${esc(tx.operator)} · Lot ${esc(tx.lot_number || '—')} · ${esc(tx.location_from || tx.location_to)}</p></div><time>${esc(tx.timestamp)}</time></div>`).join('') : status('No inventory activity yet.')}</div>`;
  } catch (error) { if (version === dashboardVersion) $('#dashboard-data').innerHTML = status(message(error), true); }
}
async function loadParts() {
  const version = ++searchVersion;
  $('#filter-state').textContent = `Status: ${search.status} · ${search.low_stock ? 'Low stock only' : 'All stock levels'} · Search: ${search.query || 'Any'} · Sort: ${search.sort.replaceAll('_', ' ')} ${search.descending ? 'descending' : 'ascending'}`;
  $('#parts-data').innerHTML = status('Loading parts…');
  try {
    const parts = await read(api.search_parts({ ...search }));
    if (version !== searchVersion) return;
    if (uncertain && !$<HTMLDialogElement>('#create-dialog').open) await reconcileCreation();
    if (version !== searchVersion) return;
    $('#parts-data').innerHTML = parts.length ? `<div class="table-wrap"><table><thead><tr><th>Part</th><th>Description</th><th class="num">Stock</th><th class="num">Minimum</th><th>State</th></tr></thead><tbody>${parts.map(p => `<tr ${selected === p.part_number ? 'class="selected"' : ''}><td><button class="part-id" data-part="${esc(p.part_number)}">${esc(p.part_number)}</button></td><td class="description">${esc(p.description)}</td><td class="num">${p.quantity}</td><td class="num">${p.minimum_quantity}</td><td>${badges(p)}</td></tr>`).join('')}</tbody></table></div><div class="table-footer">${parts.length} parts</div>` : status('No parts match these filters. Clear filters or create a part.');
  } catch (error) { if (version === searchVersion) $('#parts-data').innerHTML = status(message(error), true); }
}
async function reconcileCreation() {
  const number = submittedNumber;
  try {
    const part = await read(api.part_detail(number));
    notice(`${part.part_number} exists. Inspect it before creating another part.`);
  } catch (error) {
    if (!(error instanceof RequestError) || error.code !== 'NOT_FOUND') return;
    notice('The part was not created. You can correct or resubmit the preserved form.');
  }
  uncertain = false;
  $<HTMLButtonElement>('#create-submit').disabled = false;
  $('#create-error').textContent = '';
}
function detailHTML(part: PartDetail) {
  return `<div class="dialog-body"><div class="review-part">${esc(part.part_number)}</div><p class="description">${esc(part.description)}</p><p style="margin-top:16px">${badges(part)}</p>
${[['Total stock', part.quantity], ['Minimum quantity', part.minimum_quantity], ['Default location', part.location]].map(([label, value]) => `<div class="detail-pair"><span>${label}</span><strong>${esc(value)}</strong></div>`).join('')}
<h3>Stock by location</h3>${Object.entries(part.location_balances).map(([location, qty]) => `<div class="detail-pair"><span>${esc(location)}</span><strong>${qty}</strong></div>`).join('') || status('No locations.')}
<h3>Lot balances</h3>${part.balances.length ? `<div class="table-wrap"><table><thead><tr><th>Lot</th><th>Location</th><th class="num">Stock</th></tr></thead><tbody>${part.balances.map(b => `<tr><td>${esc(b.lot_number)}</td><td>${esc(b.location)}</td><td class="num">${b.quantity}</td></tr>`).join('')}</tbody></table></div>` : status('No lots received yet.')}
<div class="system-note">Receive, Ship, editing, and deactivation are available in the original application. These actions are deferred here.</div></div>`;
}
async function openPart(number: string, focus: HTMLElement | null = document.activeElement as HTMLElement) {
  selected = number;
  returnFocus = focus;
  document.querySelectorAll('#parts-data tr').forEach(row => row.classList.toggle('selected', row.querySelector<HTMLElement>('[data-part]')?.dataset.part === number));
  const version = ++detailVersion;
  $('#drawer-data').innerHTML = status('Loading part…');
  if (!$<HTMLDialogElement>('#drawer').open) { drawerScroll = { x: scrollX, y: scrollY }; $<HTMLDialogElement>('#drawer').showModal(); }
  try { const part = await read(api.part_detail(number)); if (version === detailVersion) $('#drawer-data').innerHTML = detailHTML(part); }
  catch (error) { if (version === detailVersion) $('#drawer-data').innerHTML = `${status(message(error), true)}<button id="retry-detail" class="btn">Retry</button>`; }
}
function restoreFocus() {
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
  else Array.from(document.querySelectorAll<HTMLElement>('[data-part]')).find(b => b.dataset.part === selected)?.focus({ preventScroll: true });
}
function openCreate(trigger: HTMLElement = document.activeElement as HTMLElement) {
  if (!api) return;
  createReturnFocus = trigger;
  $<HTMLDialogElement>('#create-dialog').showModal();
  $<HTMLInputElement>('#number').focus();
}
$<HTMLDialogElement>('#drawer').addEventListener('close', () => { ++detailVersion; restoreFocus(); window.scrollTo(drawerScroll.x, drawerScroll.y); });
$('#close-drawer').onclick = () => $<HTMLDialogElement>('#drawer').close();
$('#add-part').onclick = () => openCreate($('#add-part'));
$<HTMLDialogElement>('#create-dialog').addEventListener('close', () => { if (createReturnFocus?.isConnected) createReturnFocus.focus({ preventScroll: true }); });
$('#close-create').onclick = () => { if (!creating) $<HTMLDialogElement>('#create-dialog').close(); };
$<HTMLDialogElement>('#create-dialog').addEventListener('cancel', event => { if (creating) event.preventDefault(); });
$('#app').addEventListener('click', event => {
  const target = (event.target as HTMLElement).closest<HTMLElement>('button');
  if (!target) return;
  if (target.dataset.page) navigate(target.dataset.page as typeof page);
  if (target.dataset.part && api) void openPart(target.dataset.part, target);
  if (target.hasAttribute('data-new')) openCreate(target);
  if (target.hasAttribute('data-low-stock')) {
    search.query = ''; search.status = 'all'; search.low_stock = true;
    $<HTMLInputElement>('#query').value = ''; $<HTMLSelectElement>('#filter-status').value = 'all';
    $<HTMLInputElement>('#filter-low').checked = true; navigate('parts');
  }
  if (target.classList.contains('refresh') && api) void (page === 'dashboard' ? loadDashboard() : loadParts());
});
$('#drawer-data').onclick = event => { if ((event.target as HTMLElement).id === 'retry-detail') void openPart(selected, returnFocus); };
$('#global-search').onclick = () => { navigate('parts'); $('#query').focus(); };
document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !document.querySelector('dialog[open]')) { event.preventDefault(); $('#global-search').click(); } });
let debounce: ReturnType<typeof setTimeout>;
$('#query').addEventListener('input', () => {
  search.query = $<HTMLInputElement>('#query').value; ++searchVersion;
  clearTimeout(debounce); debounce = setTimeout(() => { if (api) void loadParts(); }, 150);
});
for (const id of ['filter-status', 'filter-low', 'sort', 'descending']) {
  $(`#${id}`).addEventListener('change', () => {
    search.status = $<HTMLSelectElement>('#filter-status').value as Search['status'];
    search.low_stock = $<HTMLInputElement>('#filter-low').checked;
    search.sort = $<HTMLSelectElement>('#sort').value as Search['sort'];
    search.descending = $<HTMLInputElement>('#descending').checked;
    if (api) void loadParts();
  });
}
$('#clear').onclick = () => {
  Object.assign(search, { query: '', status: 'all', low_stock: false, sort: 'part_number', descending: false });
  $<HTMLInputElement>('#query').value = ''; $<HTMLSelectElement>('#filter-status').value = 'all';
  $<HTMLInputElement>('#filter-low').checked = false; $<HTMLSelectElement>('#sort').value = 'part_number';
  $<HTMLInputElement>('#descending').checked = false;
  if (api) void loadParts();
};
$('#operator-form').addEventListener('submit', async event => {
  event.preventDefault(); if ($<HTMLButtonElement>('#save-operator').disabled) return;
  $<HTMLButtonElement>('#save-operator').disabled = true;
  try { const preferences = await read(api.save_operator($<HTMLInputElement>('#operator').value)); $<HTMLInputElement>('#operator').value = preferences.operator; notice('Operator saved.'); }
  catch (error) { notice(message(error), true); }
  finally { $<HTMLButtonElement>('#save-operator').disabled = false; }
});
function applyTheme() {
  document.documentElement.dataset.theme = theme;
  $('#theme').innerHTML = `${icon(theme === 'light' ? 'moon' : 'sun')}<span>${theme === 'light' ? 'Dark' : 'Light'} mode</span>`;
  $('#theme').setAttribute('aria-label', `Switch to ${theme === 'light' ? 'dark' : 'light'} mode`); icons();
}
$('#theme').onclick = async () => {
  $<HTMLButtonElement>('#theme').disabled = true;
  try { const preferences = await read(api.save_theme(theme === 'light' ? 'dark' : 'light')); theme = preferences.theme; applyTheme(); }
  catch (error) { notice(message(error), true); }
  finally { $<HTMLButtonElement>('#theme').disabled = false; }
};
$('#new-part').addEventListener('submit', async event => {
  event.preventDefault(); if (creating || uncertain) return;
  creating = true; $<HTMLButtonElement>('#create-submit').disabled = true;
  $<HTMLButtonElement>('#close-create').disabled = true; $('#create-error').textContent = '';
  const form = $<HTMLFormElement>('#new-part');
  const fields = new FormData(form);
  submittedNumber = String(fields.get('part_number'));
  form.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select').forEach(field => { field.disabled = true; });
  try {
    const part = await read(api.create_part({ part_number: String(fields.get('part_number')), description: String(fields.get('description')), minimum_quantity: Number(fields.get('minimum_quantity')), location: String(fields.get('location')) }));
    form.reset(); $<HTMLDialogElement>('#create-dialog').close();
    notice(`Created ${part.part_number}.`);
    await Promise.all([loadParts(), loadDashboard()]);
    navigate('parts', false);
    await openPart(part.part_number, $('#add-part'));
  } catch (error) {
    uncertain = error instanceof RequestError && ['TRANSPORT', 'INTERNAL'].includes(error.code);
    $('#create-error').innerHTML = status(message(error) + (uncertain ? ' Close this form and refresh the catalog to verify whether the part was created. Your entries are preserved.' : ''), true);
  } finally {
    form.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select').forEach(field => { field.disabled = false; });
    creating = false; $<HTMLButtonElement>('#create-submit').disabled = uncertain;
    $<HTMLButtonElement>('#close-create').disabled = false;
  }
});
async function start() {
  try {
    api = await ready();
    const [preferences, locations] = await Promise.all([read(api.preferences()), read(api.locations())]);
    $<HTMLInputElement>('#operator').value = preferences.operator;
    theme = preferences.theme; applyTheme();
    $('#location').innerHTML = locations.map(l => `<option ${l === 'Stock' ? 'selected' : ''}>${esc(l)}</option>`).join('');
    document.querySelectorAll<HTMLButtonElement | HTMLInputElement>('button[disabled], input[disabled]').forEach(control => { control.disabled = false; });
    await Promise.all([loadDashboard(), loadParts()]);
  } catch (error) {
    notice(message(error), true);
    $('#dashboard-data').innerHTML = status(message(error), true);
    $('#parts-data').innerHTML = status(message(error), true);
    $('#notice').insertAdjacentHTML('beforeend', ' <button id="reconnect" class="btn small">Reconnect</button>');
    $('#reconnect').onclick = () => { $('#notice').textContent = ''; void start(); };
  }
}
void start();
