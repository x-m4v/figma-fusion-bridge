/**
 * Messages between the plugin controller and its UI.
 *
 * The split is forced by Figma's sandbox: only the UI iframe can reach the
 * network, and only the controller can read the document. So the controller
 * extracts and hands the result to the UI, which does the talking.
 */
import type { InterchangeDocument, Diagnostic } from './interchange.js';

export interface SelectionSummary {
  count: number;
  /** Layer names, capped — a 900-layer selection should not build a huge string. */
  names: string[];
  layerCount: number;
  rootName: string;
  width: number;
  height: number;
}

export type ControllerToUi =
  | { type: 'selection'; summary: SelectionSummary }
  | { type: 'progress'; phase: string; done: number; total: number }
  | { type: 'document'; document: InterchangeDocument; assets: TransferAsset[] }
  | { type: 'validation'; diagnostics: Diagnostic[] }
  | { type: 'settings'; settings: PluginSettings }
  | { type: 'error'; message: string; detail?: string };

export type UiToController =
  | { type: 'ready' }
  | { type: 'send' }
  | { type: 'validate' }
  | { type: 'cancel' }
  | { type: 'settings'; settings: Partial<PluginSettings> }
  | { type: 'liveSync'; enabled: boolean }
  | { type: 'transferResult'; ok: boolean; message: string; detail?: string }
  | { type: 'resize'; height: number };

/** An asset plus its bytes, passed from controller to UI for upload. */
export interface TransferAsset {
  id: string;
  mimeType: string;
  suggestedName: string;
  bytes: Uint8Array;
}

export interface PluginSettings {
  vectorStrategy: 'NATIVE' | 'AUTO' | 'RASTER';
  clipFrames: 'AUTO' | 'ON' | 'OFF';
  includeHidden: boolean;
  preserveHierarchy: boolean;
  flattenUnsupported: boolean;
  imageExportScale: number;
  colorHandling: 'MATCH_SRGB' | 'PROJECT_MANAGED' | 'ADVANCED';
  liveSync: boolean;
  port: number;
  /**
   * The pairing token, persisted through `figma.clientStorage`.
   *
   * Not `localStorage`: a plugin's UI iframe runs on an opaque origin, and
   * Chromium throws a SecurityError on any storage access from one. Reading it
   * took the whole connection routine down before it reached the network.
   */
  bridgeToken: string;
}

export const DEFAULT_SETTINGS: PluginSettings = {
  vectorStrategy: 'AUTO',
  clipFrames: 'AUTO',
  // Off by default: a designer's hidden layers are usually hidden on purpose,
  // and importing them silently doubles the node count.
  includeHidden: false,
  preserveHierarchy: true,
  flattenUnsupported: true,
  imageExportScale: 2,
  colorHandling: 'MATCH_SRGB',
  liveSync: false,
  port: 8787,
  bridgeToken: '',
};
