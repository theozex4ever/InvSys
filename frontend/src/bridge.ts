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
export interface HistoryRecord extends Activity { transaction_id: number; shipment_number: string }
export interface HistorySearch { query: string; tx_type: string; page: number }
export interface HistoryResults { records: HistoryRecord[]; types: string[]; total: number; matching: number; page: number }
export interface Consumption { part_number: string; lot_number: string; location: string; quantity: number }
export interface ShipmentDetail extends Shipment { reference: string; consumed_components: Consumption[]; transactions: HistoryRecord[] }
export interface HistoryDetail { transaction: HistoryRecord; shipment: ShipmentDetail | null }
export interface BOMRequirement { part_number: string; description: string; quantity_required: number; stock_available: number; shortage: number }
export interface BOMLine { part_number: string; lot_number: string; location: string; quantity_required: number; quantity_allocated: number; lot_stock: number }
export interface BOMPlan { part_number: string; quantity: number; location: string; requirements: BOMRequirement[]; lines: BOMLine[]; ready: boolean }
export type BOMRequest = Omit<ShipmentRequest, 'lot_number'>;
export interface BOMPreview { request: BOMRequest; plan: BOMPlan; review_id: string; buildable: number; context: StockContext }
export interface Dashboard { active_parts: number; low_stock: Part[]; shipment_count: number; activity: HistoryRecord[] }
export type Theme = 'light' | 'dark';
export interface Preferences { operator: string; theme: Theme }
export interface Search {
  query: string; status: 'all' | 'active' | 'inactive'; low_stock: boolean;
  sort: 'part_number' | 'description' | 'quantity' | 'minimum_quantity'; descending: boolean;
}
export interface NewPart { part_number: string; description: string; minimum_quantity: number; location: string }
export type UpdatePart = NewPart;
export interface SetActive { part_number: string; active: boolean; confirm_stock?: boolean }
export interface Receipt {
  part_number: string; quantity: number; location: string; lot_number: string;
  operator: string; reference: string; notes: string;
}
export interface ShipmentRequest extends Omit<Receipt, 'notes'> { recipient: string; carrier: string; tracking: string }
export interface Shipment {
  shipment_number: string; timestamp: string; part_number: string; quantity: number;
  recipient: string; carrier: string; tracking_number: string;
}
export interface StockContext { part: PartDetail; locations: string[]; has_bom: boolean; transactions: Activity[]; shipments: Shipment[] }
export interface ShipmentPreview { request: ShipmentRequest; lot_stock: number; location_stock: number; remaining: number; context: StockContext }
export interface BackupInfo { name: string; path: string; size_bytes: number; modified: string }
export interface UtilityContext {
  database: string; database_exists: boolean; backup_dir: string; export_dir: string; log_dir: string;
  latest_backup: BackupInfo | null; backup_count: number; backup_retention: number; backup_error: string | null;
}
export type Folder = 'backups' | 'exports';
// `location` is the source Location, matching the other stock requests.
export interface MoveRequest extends Omit<Receipt, 'notes'> { destination: string }
export interface MovePreview {
  request: MoveRequest;
  source_lot_before: number; source_lot_after: number; destination_lot_before: number; destination_lot_after: number;
  source_location_before: number; source_location_after: number; destination_location_before: number; destination_location_after: number;
  context: StockContext;
}
export type Response<T> = { ok: true; data: T } | { ok: false; error: { code: 'VALIDATION' | 'DUPLICATE' | 'CONFIRMATION_REQUIRED' | 'NOT_FOUND' | 'INTERNAL' | 'PLAN_CHANGED' | 'FILE_ERROR' | 'UNAVAILABLE'; message: string } };
interface API {
  history(search: HistorySearch): Promise<Response<HistoryResults>>;
  history_detail(id: number): Promise<Response<HistoryDetail>>;
  shipment_detail(number: string): Promise<Response<ShipmentDetail>>;
  preview_bom_ship(request: BOMRequest): Promise<Response<BOMPreview>>;
  ship_bom(request: BOMRequest & { review_id: string }): Promise<Response<{ shipment_number: string; context: StockContext }>>;
  dashboard(): Promise<Response<Dashboard>>;
  preferences(): Promise<Response<Preferences>>;
  save_operator(operator: string): Promise<Response<Preferences>>;
  save_theme(theme: Theme): Promise<Response<Preferences>>;
  locations(): Promise<Response<string[]>>;
  search_parts(search: Search): Promise<Response<Part[]>>;
  part_detail(number: string): Promise<Response<PartDetail>>;
  create_part(part: NewPart): Promise<Response<PartDetail>>;
  update_part(part: UpdatePart): Promise<Response<PartDetail>>;
  set_part_active(request: SetActive): Promise<Response<PartDetail>>;
  stock_context(number: string): Promise<Response<StockContext>>;
  receive(request: Receipt): Promise<Response<StockContext>>;
  preview_ship(request: ShipmentRequest): Promise<Response<ShipmentPreview>>;
  ship(request: ShipmentRequest): Promise<Response<{ shipment_number: string; context: StockContext }>>;
  utility_context(): Promise<Response<UtilityContext>>;
  create_backup(): Promise<Response<{ created: BackupInfo; context: UtilityContext }>>;
  open_folder(kind: Folder): Promise<Response<{ folder: string }>>;
  preview_move(request: MoveRequest): Promise<Response<MovePreview>>;
  move(request: MoveRequest): Promise<Response<StockContext>>;
}
declare global { interface Window { pywebview?: { api: API } } }
export class RequestError extends Error {
  constructor(public code: string, message: string) { super(message); }
}
export function ready(): Promise<API> {
  return new Promise((resolve, reject) => {
    const loaded = () => {
      const api = window.pywebview?.api;
      if (api && ['dashboard', 'preferences', 'save_operator', 'save_theme', 'locations', 'search_parts', 'part_detail', 'create_part', 'update_part', 'set_part_active', 'stock_context', 'receive', 'preview_ship', 'ship', 'history', 'history_detail', 'shipment_detail', 'preview_bom_ship', 'ship_bom', 'preview_move', 'move', 'utility_context', 'create_backup', 'open_folder'].every(method => typeof api[method as keyof API] === 'function')) { cleanup(); resolve(api); }
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
