export const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
export const status = (text: string, error = false) => `<div class="status ${error ? 'error' : ''}" role="${error ? 'alert' : 'status'}">${esc(text)}</div>`;
export const message = (error: unknown, fallback = 'Unable to complete the request.') => error instanceof Error ? error.message : fallback;
export const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
export const pair = (label: string, value: unknown) => `<div class="detail-pair"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
export const optionalPair = (label: string, value: unknown) => pair(label, value || '—');
