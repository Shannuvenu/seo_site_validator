/** Backend API models mirrored as TypeScript types. */

export type Severity = "ERROR" | "WARNING" | "INFO";

export interface SourceLocation {
  html_line: number;
  html_column: number;
  start_offset?: number | null;
  end_offset?: number | null;
  json_path?: string | null;
  json_line?: number | null;
  json_column?: number | null;
  block_index?: number | null;
  script_line?: number | null;
}

export interface ValidationFinding {
  id: string;
  severity: Severity;
  message: string;
  error_code?: string | null;
  detail?: string | null;
  item_type?: string | null;
  item_index?: number | null;
  block_index: number;
  json_path?: string | null;
  property?: string | null;
  expected?: string | null;
  actual?: string | null;
  source?: SourceLocation | null;
}

export interface DetectedItem {
  type: string;
  id?: string | null;
  index: number;
  block_index: number;
  json_path: string;
  errors: number;
  warnings: number;
  infos: number;
  status: "PASS" | "WARN" | "FAIL";
  properties: string[];
  source_start_line: number;
  source_end_line: number;
  source_start_offset?: number | null;
  source_end_offset?: number | null;
}

export interface JsonLdBlock {
  index: number;
  parsed: boolean;
  malformed: boolean;
  error?: string | null;
  error_detail?: string | null;
  entities: DetectedItem[];
  html_start_line: number;
  html_end_line: number;
  text_start_line: number;
  json_error_line?: number | null;
  json_error_column?: number | null;
}

export interface StructuredDataResult {
  status: "PASS" | "WARN" | "FAIL" | "SKIPPED" | "UNKNOWN";
  item_count: number;
  error_count: number;
  warning_count: number;
  info_count: number;
  blocks: JsonLdBlock[];
  items: DetectedItem[];
  findings: ValidationFinding[];
}

export interface TechnicalSeoFinding {
  category: string;
  name: string;
  severity: Severity;
  message: string;
  detail?: string | null;
}

export interface TechnicalSeoResult {
  url: string;
  final_url: string;
  status_code: number;
  content_type: string;
  fetch_duration_ms: number;
  title?: string | null;
  title_length?: number | null;
  meta_description?: string | null;
  meta_description_length?: number | null;
  canonical?: string | null;
  robots_meta?: string | null;
  robots_directives: string[];
  viewport?: string | null;
  h1: string[];
  h2: string[];
  h3: string[];
  image_count: number;
  images_missing_alt: number;
  link_count: number;
  internal_links: number;
  external_links: number;
  broken_anchors: number;
  og_tags: Record<string, string>;
  twitter_tags: Record<string, string>;
  hreflang_tags: string[];
  canonical_https: boolean;
  has_jsonld: boolean;
  structured_data_blocks: number;
  findings: TechnicalSeoFinding[];
}

export interface UrlScanResult {
  url: string;
  final_url: string;
  status_code: number;
  content_type: string;
  fetch_duration_ms: number;
  fetch_error?: string | null;
  fetch_error_type?: string | null;
  technical_seo?: TechnicalSeoResult | null;
  structured_data?: StructuredDataResult | null;
  html?: string | null;
  html_size?: number | null;
}

export interface ScanResponse {
  results: UrlScanResult[];
  scan_id: string;
}

// Data Layer
export type DataLayerRecordType = "dataLayer" | "interaction" | "navigation" | "page";

export interface DataLayerRecord {
  seq: number;
  type: DataLayerRecordType;
  timestamp?: string | null;
  url: string;
  data: Record<string, unknown>;
  page_title?: string | null;
}

export interface DataLayerStartResponse {
  session_id: string;
  url: string;
  status: string;
}

export interface DataLayerStatusResponse {
  session_id: string;
  status: string;
  url: string;
  current_url: string;
  page_title?: string | null;
  data_layer_found: boolean;
  instrumented: boolean;
  events: DataLayerRecord[];
  event_count: number;
  started_at?: string | null;
  message?: string | null;
  error?: string | null;
}

export interface DataLayerClickResponse {
  session_id: string;
  clicked: boolean;
  message: string;
}

export interface DataLayerExportResponse {
  session_id: string;
  started_at?: string | null;
  url: string;
  current_url: string;
  page_title?: string | null;
  data_layer_found: boolean;
  events: DataLayerRecord[];
  event_count: number;
}

export interface DataLayerSourceResponse {
  url: string;
  html: string;
  html_size: number;
  page_title?: string | null;
  error?: string | null;
}

// Site Structure
export interface SiteNode {
  section_id: string;
  name: string;
  slug: string;
  parent_id?: string | null;
  children: SiteNode[];
  collection_type?: string | null;
  display_name?: string | null;
}

export interface SiteStructureResult {
  site: string;
  config_url: string;
  root?: SiteNode | null;
  nodes: SiteNode[];
  node_count: number;
  error?: string | null;
  fetched_at?: string | null;
}
