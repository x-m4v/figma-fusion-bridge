/**
 * Plugin controller — the sandboxed half.
 *
 * It can read the document but has no network access, so it extracts and hands
 * the result to the UI iframe, which does the talking. Everything expensive
 * happens here and is chunked so the Figma UI never locks up.
 */
import { CancelledError, Extractor, boundsOf, countNodes } from './extract.js';
import {
  DEFAULT_SETTINGS,
  type ControllerToUi,
  type PluginSettings,
  type SelectionSummary,
  type UiToController,
} from './messages.js';

const SETTINGS_KEY = 'ffbridge.settings';
/** Live Sync waits this long after the last edit before sending. */
const LIVE_SYNC_DEBOUNCE_MS = 900;
/** Names shown in the UI summary. Enough to recognise, not enough to bloat. */
const MAX_SUMMARY_NAMES = 6;

let settings: PluginSettings = { ...DEFAULT_SETTINGS };
let busy = false;
let cancelRequested = false;
let liveSyncTimer: number | null = null;

figma.showUI(__html__, { width: 340, height: 480, themeColors: true });

function post(message: ControllerToUi): void {
  figma.ui.postMessage(message);
}

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

function summarise(): SelectionSummary {
  const sel = figma.currentPage.selection;
  const box = boundsOf(sel);
  return {
    count: sel.length,
    names: sel.slice(0, MAX_SUMMARY_NAMES).map((n) => n.name),
    layerCount: countNodes(sel, settings.includeHidden),
    rootName: sel.length === 1 ? sel[0]!.name : `${sel.length} layers`,
    width: Math.round(box.width),
    height: Math.round(box.height),
  };
}

function publishSelection(): void {
  post({ type: 'selection', summary: summarise() });
}

figma.on('selectionchange', publishSelection);

// ---------------------------------------------------------------------------
// Live Sync
// ---------------------------------------------------------------------------

/**
 * Debounced auto-send.
 *
 * Debounced rather than throttled on purpose: a designer dragging a layer emits
 * a continuous stream of changes, and what they want sent is where the layer
 * ended up, not thirty intermediate positions. Sending on the trailing edge
 * also keeps Fusion from being asked to rebuild a graph many times a second.
 *
 * Listening on the *page* rather than the document is deliberate. This plugin
 * declares `documentAccess: "dynamic-page"`, under which `documentchange`
 * requires `loadAllPagesAsync()` — which loads every page in the file and
 * stalls the plugin on a large one. `nodechange` on the current page needs no
 * such load, and it is the right scope anyway: a selection is always on the
 * current page, so changes elsewhere are none of Live Sync's business.
 *
 * The handler is attached only while Live Sync is on, and re-attached when the
 * user switches page, since it is bound to one page object.
 */
function onPageChanged(): void {
  if (!settings.liveSync || busy) return;
  if (liveSyncTimer !== null) clearTimeout(liveSyncTimer);
  liveSyncTimer = setTimeout(() => {
    liveSyncTimer = null;
    if (figma.currentPage.selection.length > 0) void send();
  }, LIVE_SYNC_DEBOUNCE_MS) as unknown as number;
}

/** The page the handler is currently attached to, if any. */
let watchedPage: PageNode | null = null;

function attachLiveSync(): void {
  if (watchedPage === figma.currentPage) return;
  detachLiveSync();
  figma.currentPage.on('nodechange', onPageChanged);
  watchedPage = figma.currentPage;
}

function detachLiveSync(): void {
  if (watchedPage === null) return;
  try {
    watchedPage.off('nodechange', onPageChanged);
  } catch {
    // The page can already be gone if the user deleted it. Nothing to undo.
  }
  watchedPage = null;
  if (liveSyncTimer !== null) {
    clearTimeout(liveSyncTimer);
    liveSyncTimer = null;
  }
}

function syncLiveSyncBinding(): void {
  if (settings.liveSync) attachLiveSync();
  else detachLiveSync();
}

// The listener is bound to one page object, so follow the user across pages.
figma.on('currentpagechange', () => {
  syncLiveSyncBinding();
  publishSelection();
});

// ---------------------------------------------------------------------------
// Sending
// ---------------------------------------------------------------------------

async function send(): Promise<void> {
  if (busy) return;
  const selection = figma.currentPage.selection;
  if (selection.length === 0) {
    post({
      type: 'error',
      message: 'Select a frame, group or layer in Figma first.',
    });
    return;
  }

  busy = true;
  cancelRequested = false;
  try {
    const extractor = new Extractor({
      settings,
      onProgress: (phase, done, total) => post({ type: 'progress', phase, done, total }),
      isCancelled: () => cancelRequested,
    });
    const { document, assets } = await extractor.extract(selection);
    post({ type: 'document', document, assets });
  } catch (err) {
    if (err instanceof CancelledError) {
      post({ type: 'error', message: 'Transfer cancelled.' });
    } else {
      post({
        type: 'error',
        message: 'The selection could not be read. Try selecting fewer layers.',
        detail: String(err),
      });
    }
  } finally {
    busy = false;
  }
}

/**
 * A dry run: extract, report the warnings, throw the document away.
 *
 * Worth the duplicated work because it lets a designer see "2 unsupported
 * effects, 1 missing font" *before* switching to Resolve, which is when the
 * information is cheap to act on.
 */
async function validate(): Promise<void> {
  const selection = figma.currentPage.selection;
  if (selection.length === 0) {
    post({ type: 'validation', diagnostics: [] });
    return;
  }
  busy = true;
  cancelRequested = false;
  try {
    const extractor = new Extractor({
      settings,
      onProgress: (phase, done, total) => post({ type: 'progress', phase, done, total }),
      isCancelled: () => cancelRequested,
    });
    const { document } = await extractor.extract(selection);
    post({ type: 'validation', diagnostics: document.diagnostics });
  } catch (err) {
    post({
      type: 'validation',
      diagnostics: [
        {
          severity: 'ERROR',
          code: 'VALIDATION_FAILED',
          message: 'The selection could not be checked.',
          detail: String(err),
        },
      ],
    });
  } finally {
    busy = false;
  }
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

async function loadSettings(): Promise<void> {
  try {
    const stored = await figma.clientStorage.getAsync(SETTINGS_KEY);
    if (stored && typeof stored === 'object') {
      settings = { ...DEFAULT_SETTINGS, ...(stored as Partial<PluginSettings>) };
    }
  } catch {
    // A failed read must not stop the plugin; defaults are fine.
  }
  syncLiveSyncBinding();
  post({ type: 'settings', settings });
}

async function saveSettings(patch: Partial<PluginSettings>): Promise<void> {
  settings = { ...settings, ...patch };
  if ('liveSync' in patch) syncLiveSyncBinding();
  post({ type: 'settings', settings });
  try {
    await figma.clientStorage.setAsync(SETTINGS_KEY, settings);
  } catch {
    // Settings are a convenience; failing to persist them is not an error
    // worth interrupting the user for.
  }
}

// ---------------------------------------------------------------------------
// Messages from the UI
// ---------------------------------------------------------------------------

figma.ui.onmessage = async (msg: UiToController) => {
  switch (msg.type) {
    case 'ready':
      await loadSettings();
      publishSelection();
      break;
    case 'send':
      await send();
      break;
    case 'validate':
      await validate();
      break;
    case 'cancel':
      cancelRequested = true;
      break;
    case 'settings':
      await saveSettings(msg.settings);
      if ('includeHidden' in msg.settings) publishSelection();
      break;
    case 'liveSync':
      await saveSettings({ liveSync: msg.enabled });
      break;
    case 'transferResult':
      figma.notify(msg.message, { error: !msg.ok, timeout: msg.ok ? 2500 : 6000 });
      break;
    case 'resize':
      figma.ui.resize(340, Math.max(320, Math.min(720, Math.round(msg.height))));
      break;
  }
};

// Release the page listener when the plugin closes, so a re-run starts clean.
figma.on('close', () => {
  detachLiveSync();
});
