import { message, pair, $, esc, status } from './presentation';
import { read, type ready, type BOMExploration, type BOMExploreNode, type BOMExploreRequest, type CapacityLevel } from './bridge';

// Read-only BOM explorer. Python supplies structure, requirements and capacity;
// this module only lays out and displays them. Nothing here writes inventory.
type API = Awaited<ReturnType<typeof ready>>;
interface Placed { id: number; node: BOMExploreNode; x: number; y: number; parent: number; children: number[] }
interface View { x: number; y: number; k: number }

const NODE_W = 236, NODE_H = 112, COL_GAP = 96, ROW_GAP = 20, MARGIN = 32;
const MIN_ZOOM = 0.02, MAX_ZOOM = 3, PAN_STEP = 64;
const LEVELS: Record<CapacityLevel, { label: string; glyph: string }> = {
  critical: { label: 'Critical', glyph: '▲' },
  low: { label: 'Low', glyph: '◆' },
  ready: { label: 'Ready', glyph: '●' },
};
const short = (text: string, length: number) => text.length > length ? `${text.slice(0, length - 1)}…` : text;
const levelText = (level: CapacityLevel, builds: number) => `${LEVELS[level].glyph} ${LEVELS[level].label} capacity · ${builds.toLocaleString()} ${builds === 1 ? 'build' : 'builds'}`;
const levelBadge = (level: CapacityLevel) => `<span class="badge ${level === 'critical' ? 'bad' : level === 'low' ? 'warn' : 'good'}">${LEVELS[level].glyph} ${LEVELS[level].label} capacity</span>`;

export function bomExploreWorkflow(getAPI: () => API, openHistory: (partNumber: string) => void) {
  let version = 0, searchVersion = 0, debounce: ReturnType<typeof setTimeout> | undefined;
  let placed: Placed[] = [];
  let result: BOMExploration | null = null;
  let requirements = new Map<string, BOMExploration['requirements'][number]>();
  let view: View = { x: 0, y: 0, k: 1 };
  let fitted = true, suppressClick = false;
  let contentW = 0, contentH = 0;

  $('main').insertAdjacentHTML('beforeend', `<section id="bom-explore" hidden><div class="page-heading"><div><h1>BOM explorer</h1><p>Read-only structure, Leaf materials and Build capacity by Location.</p></div><button id="bomx-refresh" class="btn" disabled>Refresh</button></div>
<form id="bomx-form" class="panel panel-body bomx-form"><div class="field"><label for="bomx-part">Assembly part <span class="required">*</span></label><input id="bomx-part" name="part_number" list="bomx-parts" autocomplete="off" required><datalist id="bomx-parts"></datalist></div>
<div class="field"><label for="bomx-location">Location <span class="required">*</span></label><select id="bomx-location" name="location" required></select></div>
<div class="field"><label for="bomx-quantity">Build quantity <span class="required">*</span></label><input id="bomx-quantity" name="quantity" type="number" min="1" max="2147483647" step="1" value="1" required></div>
<button id="bomx-submit" class="btn primary" disabled>Explore BOM</button></form>
<div id="bomx-error" role="alert"></div><div id="bomx-result">${status('Choose an assembly, Location and quantity.')}</div></section>`);

  const form = () => $<HTMLFormElement>('#bomx-form');
  const viewport = () => document.querySelector<HTMLElement>('#bomx-viewport');
  const canvas = () => document.querySelector<SVGGElement>('#bomx-canvas');

  function request(): BOMExploreRequest | null {
    const part = $<HTMLInputElement>('#bomx-part').value.trim();
    const quantityText = $<HTMLInputElement>('#bomx-quantity').value.trim();
    const quantity = Number(quantityText);
    const location = $<HTMLSelectElement>('#bomx-location').value;
    const problem = !part ? 'Enter an assembly part number.' : !location ? 'Choose a Location.'
      : !/^\d+$/.test(quantityText) || quantity < 1 || quantity > 2147483647 ? 'Enter a whole build quantity from 1 to 2147483647.' : '';
    $('#bomx-error').innerHTML = problem ? status(problem, true) : '';
    return problem ? null : { part_number: part, quantity, location };
  }

  // A superseded read must not touch the controls or the current result.
  async function loadLocations(current: number) {
    const locations = await read(getAPI().locations());
    if (current !== version) return;
    const previous = $<HTMLSelectElement>('#bomx-location').value;
    $('#bomx-location').innerHTML = locations.map(l => `<option ${l === (previous || 'Stock') ? 'selected' : ''}>${esc(l)}</option>`).join('');
  }

  async function load() {
    const current = ++version;
    try {
      await loadLocations(current);
      if (current !== version) return;
      const fields = request();
      if (!fields) { placed = []; result = null; $('#bomx-result').innerHTML = status('Correct the form to explore.'); return; }
      placed = []; result = null;
      $('#bomx-result').innerHTML = status('Loading current BOM and stock…');
      const data = await read(getAPI().explore_bom(fields));
      if (current !== version) return;
      render(data);
    } catch (error) {
      // An unavailable read must not leave a graph on screen that looks current.
      if (current !== version) return;
      result = null; placed = [];
      $('#bomx-result').innerHTML = `${status(message(error, 'Unable to read the BOM.'), true)}`;
    }
  }

  // Layout: one column per depth, leaves stacked, parents centred on their children.
  function layout(root: BOMExploreNode) {
    const items: Placed[] = [];
    let row = MARGIN;
    const place = (node: BOMExploreNode, depth: number, parent: number): { id: number; center: number } => {
      const id = items.length;
      const item: Placed = { id, node, x: MARGIN + depth * (NODE_W + COL_GAP), y: 0, parent, children: [] };
      items.push(item);
      const kids = node.children.map(child => place(child, depth + 1, id));
      item.children = kids.map(kid => kid.id);
      const center = kids.length ? ((kids[0]!.center + kids[kids.length - 1]!.center) / 2) : row + NODE_H / 2;
      if (!kids.length) row += NODE_H + ROW_GAP;
      item.y = center - NODE_H / 2;
      return { id, center };
    };
    place(root, 0, -1);
    placed = items;
    contentW = Math.max(...items.map(item => item.x)) + NODE_W + MARGIN;
    contentH = Math.max(...items.map(item => item.y)) + NODE_H + MARGIN;
  }

  const nodeLabel = (item: Placed) => {
    const { node } = item;
    return `${node.children.length ? 'Assembly' : 'Material'} ${node.part_number}, ${node.description}. Requires ${node.quantity_required}, ${node.stock_available} available. ${levelText(node.level, node.capacity)}.`;
  };

  function nodeSVG(item: Placed) {
    const { node } = item;
    const leafShort = !node.children.length ? requirements.get(node.part_number)?.shortage ?? 0 : 0;
    const stockLine = node.children.length ? `Stock ${node.stock_available.toLocaleString()} · not consumed` : `Need ${node.quantity_required.toLocaleString()} · Have ${node.stock_available.toLocaleString()}${leafShort ? ` · Short ${leafShort.toLocaleString()}` : ''}`;
    return `<g class="bomx-node level-${node.level}" data-id="${item.id}" transform="translate(${item.x} ${item.y})" tabindex="${item.id === 0 ? 0 : -1}" role="button" aria-pressed="false" aria-label="${esc(nodeLabel(item))}">
<rect class="bomx-card" width="${NODE_W}" height="${NODE_H}" rx="10"/><rect class="bomx-accent" x="0" y="14" width="5" height="${NODE_H - 28}"/>
<text class="bomx-kind" x="18" y="22">${node.children.length ? 'ASSEMBLY' : 'MATERIAL'}</text><text class="bomx-part" x="18" y="44">${esc(short(node.part_number, 24))}</text>
<text class="bomx-desc" x="18" y="62">${esc(short(node.description, 30))}</text><text class="bomx-stock${leafShort ? ' short' : ''}" x="18" y="82">${esc(stockLine)}</text>
<text class="bomx-level" x="18" y="101">${esc(levelText(node.level, node.capacity))}</text><title>${esc(`${node.part_number} — ${node.description}`)}</title></g>`;
  }

  function edgesSVG() {
    return placed.flatMap(parent => parent.children.map(id => {
      const child = placed[id]!;
      const x1 = parent.x + NODE_W, y1 = parent.y + NODE_H / 2, x2 = child.x, y2 = child.y + NODE_H / 2, bend = (x1 + x2) / 2;
      return `<path class="bomx-edge level-${child.node.level}" d="M${x1} ${y1} C${bend} ${y1} ${bend} ${y2} ${x2} ${y2}"/><text class="bomx-qty" x="${x2 - 8}" y="${y2 - 8}" text-anchor="end">×${child.node.quantity_per_parent}</text>`;
    })).join('');
  }

  function render(data: BOMExploration) {
    result = data;
    requirements = new Map(data.requirements.map(req => [req.part_number, req]));
    const { request: asked } = data;
    const builds = (count: number) => `${count.toLocaleString()} ${count === 1 ? 'build' : 'builds'}`;
    const summary = `<div class="bomx-summary" role="status"><div class="panel panel-body"><span class="eyebrow">Build capacity at ${esc(asked.location)}</span><div class="bomx-figure">${data.has_bom ? `<strong>${data.buildable.toLocaleString()}</strong><span>final ${data.buildable === 1 ? 'build' : 'builds'}</span>${levelBadge(data.level)}` : '<strong>No BOM</strong>'}</div></div>
<div class="panel panel-body"><span class="eyebrow">Requested ${esc(builds(asked.quantity))}</span><div class="bomx-figure"><strong>${data.has_bom ? (data.shortage_count ? `${data.shortage_count} short` : 'No shortage') : 'Nothing to expand'}</strong>${data.has_bom ? `<span class="badge ${data.shortage_count ? 'bad' : 'good'}">${data.shortage_count ? '✕ Material shortage' : '✓ No material shortage'}</span>` : ''}</div></div></div>`;
    if (!data.has_bom) {
      $('#bomx-result').innerHTML = `${summary}${status(`${data.tree.part_number} has no BOM components. ${data.tree.stock_available.toLocaleString()} on hand at ${asked.location}.`)}`;
      placed = []; return;
    }
    layout(data.tree);
    fitted = true;
    const leaves = data.requirements.length;
    $('#bomx-result').innerHTML = `${summary}<div class="bomx-layout"><div class="panel"><div class="panel-head"><h2>Structure</h2><div class="bomx-tools" role="group" aria-label="Graph view controls"><button class="btn small" data-bomx="out" aria-label="Zoom out">−</button><output id="bomx-zoom" aria-label="Zoom level">100%</output><button class="btn small" data-bomx="in" aria-label="Zoom in">+</button><button class="btn small" data-bomx="fit">Fit</button><button class="btn small" data-bomx="reset">100%</button></div></div>
<div id="bomx-viewport" class="bomx-viewport" tabindex="0" role="group" aria-label="BOM graph, ${placed.length} nodes" aria-describedby="bomx-hint"><svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg"><g id="bomx-canvas">${edgesSVG()}${placed.map(nodeSVG).join('')}</g></svg></div>
<p id="bomx-hint" class="help bomx-hint">Capacity: Critical ≤100 builds, Low ≤500; shortages use the requested quantity. Pan: drag or graph arrow keys. Zoom: Ctrl + wheel or +/−. Fit: 0. Nodes: arrows navigate, Enter selects. ${placed.length} nodes, ${leaves} Leaf ${leaves === 1 ? 'material' : 'materials'}.</p></div>
<aside id="bomx-inspector" class="panel panel-body" aria-label="Selected node">${status('Select a node to inspect it.')}</aside></div>
<div class="panel"><div class="panel-head"><h2>Leaf material requirements</h2><span class="badge neutral">Aggregated across all paths</span></div>${requirementsTable(data)}</div>`;
    fit(); select(0, false);
  }

  function requirementsTable(data: BOMExploration) {
    const capacity = new Map<string, number>();
    const walk = (node: BOMExploreNode) => { if (node.children.length) node.children.forEach(walk); else capacity.set(node.part_number, node.capacity); };
    walk(data.tree);
    return `<div class="table-wrap"><table><thead><tr><th>Material</th><th>Description</th><th class="num">Required</th><th class="num">Available</th><th>Shortage</th><th class="num">Builds supported</th></tr></thead><tbody>${data.requirements.map(req => {
      const builds = capacity.get(req.part_number) ?? 0;
      return `<tr><td><button class="part-id" data-part="${esc(req.part_number)}">${esc(req.part_number)}</button></td><td class="description">${esc(req.description)}</td><td class="num">${req.quantity_required.toLocaleString()}</td><td class="num">${req.stock_available.toLocaleString()}</td><td>${req.shortage ? `<span class="badge bad">✕ Short ${req.shortage.toLocaleString()}</span>` : '<span class="badge good">✓ None</span>'}</td><td class="num">${builds.toLocaleString()}</td></tr>`;
    }).join('')}</tbody></table></div>`;
  }

  function select(id: number, focus = true) {
    const item = placed[id];
    if (!item) return;
    document.querySelectorAll<SVGElement>('#bomx-canvas .bomx-node').forEach(element => {
      const own = Number(element.dataset.id);
      element.classList.toggle('selected', own === id);
      element.setAttribute('aria-pressed', String(own === id));
      element.setAttribute('tabindex', own === id ? '0' : '-1');
    });
    const { node } = item;
    const req = node.children.length ? undefined : requirements.get(node.part_number);
    $('#bomx-inspector').innerHTML = `<h2>${esc(node.part_number)}</h2><p class="description">${esc(node.description)}</p><p style="margin:12px 0">${levelBadge(node.level)} <span class="badge neutral">${node.children.length ? 'Assembly' : 'Leaf material'}</span></p>
${pair('Quantity per parent', node.quantity_per_parent)}${pair('Required on this path', node.quantity_required)}${pair(`Available at ${result?.request.location ?? ''}`, node.stock_available)}${pair('Build capacity', `${node.capacity.toLocaleString()} ${node.capacity === 1 ? 'build' : 'builds'}`)}
${req ? `${pair('Required across all paths', req.quantity_required)}${pair('Shortage for requested quantity', req.shortage ? `Short ${req.shortage}` : 'None')}` : '<p class="help">Capacity follows the limiting Leaf material; only Leaf stock is consumed.</p>'}
<div class="stock-context-actions"><button class="btn" data-part="${esc(node.part_number)}">Open part</button> <button class="btn" data-bomx-history="${esc(node.part_number)}">View History</button></div>`;
    if (focus) { ensureVisible(item); document.querySelector<SVGElement>(`#bomx-canvas [data-id="${id}"]`)?.focus({ preventScroll: true }); }
  }

  function apply() {
    canvas()?.setAttribute('transform', `translate(${view.x} ${view.y}) scale(${view.k})`);
    const zoom = document.querySelector('#bomx-zoom');
    if (zoom) zoom.textContent = `${Math.round(view.k * 100)}%`;
  }
  function fit() {
    const box = viewport()?.getBoundingClientRect();
    if (!box?.width || !box.height) return;
    const k = Math.min(1, Math.max(MIN_ZOOM, Math.min(box.width / contentW, box.height / contentH)));
    view = { k, x: Math.max(0, (box.width - contentW * k) / 2), y: Math.max(0, (box.height - contentH * k) / 2) };
    fitted = true; apply();
  }
  function zoomAt(factor: number, cx?: number, cy?: number) {
    const box = viewport()?.getBoundingClientRect();
    if (!box) return;
    const px = cx ?? box.width / 2, py = cy ?? box.height / 2;
    const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.k * factor));
    view = { k, x: px - (px - view.x) * k / view.k, y: py - (py - view.y) * k / view.k };
    fitted = false; apply();
  }
  function ensureVisible(item: Placed) {
    const box = viewport()?.getBoundingClientRect();
    if (!box) return;
    const left = view.x + item.x * view.k, top = view.y + item.y * view.k, w = NODE_W * view.k, h = NODE_H * view.k, pad = 16;
    if (left < pad) view.x += pad - left; else if (left + w > box.width - pad) view.x -= left + w - (box.width - pad);
    if (top < pad) view.y += pad - top; else if (top + h > box.height - pad) view.y -= top + h - (box.height - pad);
    fitted = false; apply();
  }
  const reset = () => zoomAt(1 / view.k);

  // Drag-to-pan. A drag must not also select the node it started on.
  let drag: { x: number; y: number; vx: number; vy: number; moved: boolean } | null = null;
  document.addEventListener('pointerdown', event => {
    const target = event.target as HTMLElement;
    if (event.button !== 0 || !target.closest?.('#bomx-viewport')) return;
    drag = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y, moved: false };
  });
  document.addEventListener('pointermove', event => {
    if (!drag) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    if (!drag.moved) { drag.moved = true; viewport()?.classList.add('dragging'); }
    view = { ...view, x: drag.vx + dx, y: drag.vy + dy }; fitted = false; apply();
  });
  const endDrag = () => {
    if (drag?.moved) { suppressClick = true; setTimeout(() => { suppressClick = false; }, 0); }
    drag = null; document.querySelector('#bomx-viewport')?.classList.remove('dragging');
  };
  document.addEventListener('pointerup', endDrag);
  document.addEventListener('pointercancel', endDrag);
  document.addEventListener('wheel', event => {
    if (!(event.ctrlKey || event.metaKey) || !(event.target as HTMLElement).closest?.('#bomx-viewport')) return;
    event.preventDefault();
    const box = viewport()!.getBoundingClientRect();
    zoomAt(event.deltaY < 0 ? 1.15 : 1 / 1.15, event.clientX - box.left, event.clientY - box.top);
  }, { passive: false });
  new ResizeObserver(() => { if (fitted && placed.length && !$('#bom-explore').hidden) fit(); }).observe(document.body);

  $('#bomx-result').addEventListener('click', event => {
    const target = event.target as HTMLElement;
    const control = target.closest<HTMLElement>('[data-bomx]')?.dataset.bomx;
    if (control === 'in') zoomAt(1.25); else if (control === 'out') zoomAt(1 / 1.25); else if (control === 'fit') fit(); else if (control === 'reset') reset();
    const history = target.closest<HTMLElement>('[data-bomx-history]')?.dataset.bomxHistory;
    if (history) openHistory(history);
    const node = target.closest<SVGElement>('.bomx-node');
    if (node && !suppressClick) select(Number(node.dataset.id));
  });
  $('#bomx-result').addEventListener('keydown', event => {
    const target = event.target as HTMLElement;
    if (!target.closest('#bomx-viewport')) return;
    const node = target.closest<SVGElement>('.bomx-node');
    const item = node ? placed[Number(node.dataset.id)] : undefined;
    if (event.key === '+' || event.key === '=') zoomAt(1.25);
    else if (event.key === '-' || event.key === '_') zoomAt(1 / 1.25);
    else if (event.key === '0') fit();
    else if (item && (event.key === 'Enter' || event.key === ' ')) select(item.id);
    else if (item && event.key.startsWith('Arrow')) {
      const siblings = item.parent < 0 ? [item.id] : placed[item.parent]!.children;
      const index = siblings.indexOf(item.id);
      const next = event.key === 'ArrowLeft' ? item.parent : event.key === 'ArrowRight' ? item.children[0] : siblings[index + (event.key === 'ArrowDown' ? 1 : -1)];
      if (next === undefined || next < 0) { event.preventDefault(); return; }
      const other = placed[next]!; ensureVisible(other);
      document.querySelectorAll('#bomx-canvas .bomx-node').forEach(element => element.setAttribute('tabindex', Number((element as SVGElement).dataset.id) === next ? '0' : '-1'));
      document.querySelector<SVGElement>(`#bomx-canvas [data-id="${next}"]`)?.focus({ preventScroll: true });
    } else if (target.id === 'bomx-viewport' && event.key.startsWith('Arrow')) {
      view = { ...view, x: view.x + (event.key === 'ArrowLeft' ? PAN_STEP : event.key === 'ArrowRight' ? -PAN_STEP : 0), y: view.y + (event.key === 'ArrowUp' ? PAN_STEP : event.key === 'ArrowDown' ? -PAN_STEP : 0) };
      fitted = false; apply();
    } else return;
    event.preventDefault();
  });
  form().addEventListener('submit', event => { event.preventDefault(); if (getAPI()) void load(); });
  $('#bomx-refresh').onclick = () => { if (getAPI()) void load(); };
  $('#bomx-part').addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(async () => {
      const current = ++searchVersion;
      try {
        const parts = await read(getAPI().search_parts({ query: $<HTMLInputElement>('#bomx-part').value, status: 'all', low_stock: false, sort: 'part_number', descending: false }));
        if (current === searchVersion) $('#bomx-parts').innerHTML = parts.slice(0, 50).map(part => `<option value="${esc(part.part_number)}">${esc(part.description)}</option>`).join('');
      } catch { /* Suggestions are optional; submitting still validates in Python. */ }
    }, 150);
  });

  return {
    /** Open the page, optionally pre-filling a part, and re-read authoritative data. */
    open(partNumber?: string) {
      if (partNumber) $<HTMLInputElement>('#bomx-part').value = partNumber;
      if ($<HTMLInputElement>('#bomx-part').value.trim()) void load(); else { const current = ++version; void loadLocations(current).catch(error => { if (current === version) $('#bomx-error').innerHTML = status(message(error, 'Unable to read the BOM.'), true); }); }
      $('#bomx-part').focus();
    },
    /** Drop any in-flight read when the operator leaves the page. */
    leave() { ++version; },
  };
}
