export interface Part {
  part_number: string; description: string; minimum_quantity: number;
  location: string; active: boolean; quantity: number; low_stock: boolean;
}
export interface Balance { part_number: string; location: string; lot_number: string; quantity: number }
export interface PartDetail extends Part { balances: Balance[]; location_balances: Record<string, number> }
export interface Activity {
  timestamp: string; tx_type: string; part_number: string; quantity_change: number;
  operator: string; lot_number: string; location_from: string; location_to: string;
  reference: string; notes: string;
}
export interface Dashboard { active_parts: number; low_stock: Part[]; shipment_count: number; activity: Activity[] }
export type Theme = 'light' | 'dark';
export interface Preferences { operator: string; theme: Theme }
export interface Search {
  query: string; status: 'all' | 'active' | 'inactive'; low_stock: boolean;
  sort: 'part_number' | 'description' | 'quantity' | 'minimum_quantity'; descending: boolean;
}
export interface NewPart { part_number: string; description: string; minimum_quantity: number; location: string }
export type Response<T> = { ok: true; data: T } | { ok: false; error: { code: 'VALIDATION' | 'DUPLICATE' | 'NOT_FOUND' | 'INTERNAL'; message: string } };
interface API {
  dashboard(): Promise<Response<Dashboard>>;
  preferences(): Promise<Response<Preferences>>;
  save_operator(operator: string): Promise<Response<Preferences>>;
  save_theme(theme: Theme): Promise<Response<Preferences>>;
  locations(): Promise<Response<string[]>>;
  search_parts(search: Search): Promise<Response<Part[]>>;
  part_detail(number: string): Promise<Response<PartDetail>>;
  create_part(part: NewPart): Promise<Response<PartDetail>>;
}
declare global { interface Window { pywebview?: { api: API } } }
export class RequestError extends Error {
  constructor(public code: string, message: string) { super(message); }
}
export function ready(): Promise<API> {
  return new Promise((resolve, reject) => {
    const loaded = () => {
      const api = window.pywebview?.api;
      if (api && ['dashboard', 'preferences', 'save_operator', 'save_theme', 'locations', 'search_parts', 'part_detail', 'create_part'].every(method => typeof api[method as keyof API] === 'function')) { cleanup(); resolve(api); }
    };
    const cleanup = () => { clearTimeout(timer); window.removeEventListener('pywebviewready', loaded); };
    const timer = setTimeout(() => {
      cleanup(); reject(new RequestError('UNAVAILABLE', 'The desktop connection is unavailable. Open this page with the InvSys desktop launcher.'));
    }, 8000);
    window.addEventListener('pywebviewready', loaded);
    loaded();
  });
}
export async function read<T>(request: Promise<Response<T>>): Promise<T> {
  let response: Response<T>;
  try { response = await request; }
  catch { throw new RequestError('TRANSPORT', 'Connection interrupted. Refresh to check current data before trying again.'); }
  if (!response.ok) throw new RequestError(response.error.code, response.error.message);
  return response.data;
}
