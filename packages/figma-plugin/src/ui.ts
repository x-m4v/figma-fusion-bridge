/**
 * Plugin UI.
 *
 * Deliberately small and hand-rolled — a framework would be most of the bundle
 * for a panel with one button. The layout follows Figma's own plugin
 * conventions so it does not look like a foreign object inside the editor.
 */
import { BridgeTransport, TransportError, type BridgeStatus } from './transport.js';
import {
  DEFAULT_SETTINGS,
  type ControllerToUi,
  type PluginSettings,
  type SelectionSummary,
  type TransferAsset,
  type UiToController,
} from './messages.js';
import type { Diagnostic } from './interchange.js';

const transport = new BridgeTransport();
let settings: PluginSettings = { ...DEFAULT_SETTINGS };
let selection: SelectionSummary = {
  count: 0, names: [], layerCount: 0, rootName: '', width: 0, height: 0,
};
let status: BridgeStatus | null = null;
let phase: 'idle' | 'working' | 'pairing' = 'idle';
let progress: { phase: string; done: number; total: number } | null = null;
let log: Diagnostic[] = [];
let lastResult = '';
let optionsOpen = false;
/** Why the last connection attempt failed, shown instead of a generic message. */
let connectionError = '';
/** Settings have arrived from the controller, so the token is known. */
let settingsReady = false;

function send(msg: UiToController): void {
  parent.postMessage({ pluginMessage: msg }, '*');
}

// ---------------------------------------------------------------------------
// Connection
// ---------------------------------------------------------------------------

async function connect(): Promise<void> {
  // The whole routine is guarded. Anything that throws here used to surface as
  // "Bridge not running", which sent people to restart an app that was fine.
  try {
    connectionError = '';
    transport.setToken(settings.bridgeToken || null);

    const port = await transport.discover(settings.port);
    if (port === null) {
      status = null;
      render();
      return;
    }
    try {
      status = await transport.status();
      phase = 'idle';
    } catch (err) {
      status = null;
      if (err instanceof TransportError && err.message === 'unpaired') {
        phase = 'pairing';
      } else {
        connectionError = err instanceof TransportError ? err.message : String(err);
      }
    }
  } catch (err) {
    status = null;
    connectionError = err instanceof Error ? err.message : String(err);
  }
  render();
}

async function pair(code: string): Promise<void> {
  try {
    const token = await transport.pair(code);
    // Persisted by the controller, which has clientStorage. The UI iframe has
    // no usable storage of its own.
    settings = { ...settings, bridgeToken: token };
    send({ type: 'settings', settings: { bridgeToken: token } });
    phase = 'idle';
    await connect();
  } catch (err) {
    lastResult = err instanceof TransportError ? err.message : 'Pairing failed.';
    render();
  }
}

// ---------------------------------------------------------------------------
// Transfer
// ---------------------------------------------------------------------------

async function deliver(document: unknown, assets: TransferAsset[]): Promise<void> {
  const started = performance.now();
  try {
    // Upload only what the bridge does not already have. The same logo used
    // twenty times across twenty transfers is uploaded once, ever.
    const known = await transport.filterKnownAssets(assets.map((a) => a.id));
    const pending = assets.filter((a) => !known.has(a.id));

    for (let i = 0; i < pending.length; i++) {
      const asset = pending[i]!;
      progress = { phase: 'Uploading images', done: i + 1, total: pending.length };
      render();
      await transport.uploadAsset(asset.id, asset.mimeType, asset.suggestedName, asset.bytes);
    }

    progress = null;
    await transport.sendDocument(document);

    const doc = document as { nodes?: unknown[]; diagnostics?: Diagnostic[] };
    const ms = Math.round(performance.now() - started);
    const warnings = (doc.diagnostics ?? []).filter((d) => d.severity === 'WARNING').length;
    const errors = (doc.diagnostics ?? []).filter((d) => d.severity === 'ERROR').length;

    log = doc.diagnostics ?? [];
    lastResult =
      `${doc.nodes?.length ?? 0} layers · ${assets.length} assets · ` +
      `${errors} errors · ${warnings} warnings · ${ms} ms`;

    send({
      type: 'transferResult',
      ok: errors === 0,
      message:
        errors === 0
          ? 'Sent to Fusion. Run Receive in DaVinci Resolve.'
          : `Sent with ${errors} error(s).`,
    });
  } catch (err) {
    const message = err instanceof TransportError ? err.message : 'The transfer failed.';
    const detail = err instanceof TransportError ? err.detail : String(err);
    lastResult = message;
    log = [{ severity: 'ERROR', code: 'TRANSFER_FAILED', message, ...(detail ? { detail } : {}) }];
    send({ type: 'transferResult', ok: false, message });
  } finally {
    phase = 'idle';
    progress = null;
    render();
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function h(tag: string, attrs: Record<string, unknown> = {}, ...kids: (Node | string)[]): HTMLElement {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === false || v === null) continue;
    if (k === 'class') el.className = String(v);
    else if (k.startsWith('on') && typeof v === 'function') {
      el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
    } else if (k === 'checked' || k === 'disabled' || k === 'hidden') {
      (el as unknown as Record<string, unknown>)[k] = Boolean(v);
    } else el.setAttribute(k, String(v));
  }
  for (const kid of kids) el.append(kid instanceof Node ? kid : document.createTextNode(kid));
  return el;
}

function statusRow(label: string, state: 'ok' | 'warn' | 'err' | 'busy' | 'idle', note: string) {
  return h('div', { class: 'row' },
    h('span', { class: `light ${state}` }),
    h('span', {}, label),
    h('span', { class: 'dim', style: 'margin-left:auto' }, note),
  );
}

function statusPanel(): HTMLElement {
  const bridgeState = phase === 'working' ? 'busy' : status ? 'ok' : 'err';
  const bridgeNote = status
    ? `port ${transport.currentPort}`
    : phase === 'pairing'
      ? 'needs pairing'
      : 'not running';

  return h('div', { class: 'pad status' },
    statusRow('Bridge', bridgeState, bridgeNote),
    statusRow(
      'DaVinci Resolve',
      status?.resolveConnected ? 'ok' : 'idle',
      status?.resolveConnected ? 'connected' : 'not detected',
    ),
    statusRow(
      'Fusion',
      status?.fusionReady ? 'ok' : 'idle',
      status?.fusionReady ? 'ready' : 'no composition',
    ),
  );
}

function pairingPanel(): HTMLElement {
  let value = '';
  const input = h('input', {
    class: 'code', maxlength: '8', placeholder: '••••••',
    oninput: (e: Event) => { value = (e.target as HTMLInputElement).value; },
    onkeydown: (e: KeyboardEvent) => { if (e.key === 'Enter') void pair(value); },
  });
  return h('div', { class: 'pad divider' },
    h('h2', {}, 'Connect to this Mac'),
    h('p', { class: 'dim', style: 'margin:6px 0 9px' },
      'Open the Figma Fusion Bridge app and type the code it shows.'),
    input,
    h('div', { style: 'height:8px' }),
    h('button', { class: 'primary wide', onclick: () => void pair(value) }, 'Connect'),
    h('p', { class: 'footnote', style: 'margin:9px 0 0' },
      'This pairs the plugin with the helper on your Mac. Nothing is sent anywhere else.'),
  );
}

function selectionPanel(): HTMLElement {
  if (selection.count === 0) {
    return h('div', { class: 'pad divider' },
      h('div', { class: 'card dim' }, 'Select a frame, group or layer in Figma.'),
    );
  }
  return h('div', { class: 'pad divider' },
    h('div', { class: 'card' },
      h('div', { class: 'title truncate' }, selection.rootName),
      h('div', { class: 'dim', style: 'margin-top:2px' },
        `${selection.layerCount} layers · ${selection.width} × ${selection.height}`),
    ),
  );
}

function actionPanel(): HTMLElement {
  const busy = phase === 'working';
  const canSend = selection.count > 0 && status !== null && !busy;

  const kids: (Node | string)[] = [
    h('button', {
      class: 'primary wide',
      disabled: !canSend,
      onclick: () => {
        phase = 'working';
        log = [];
        lastResult = '';
        render();
        send({ type: 'send' });
      },
    }, busy ? 'Sending…' : 'Send to Fusion'),
  ];

  if (busy) {
    const pct = progress && progress.total > 0
      ? Math.round((progress.done / progress.total) * 100)
      : 0;
    kids.push(
      h('div', { style: 'height:8px' }),
      h('div', { class: 'bar' }, h('i', { style: `width:${pct}%` })),
      h('div', { class: 'row between', style: 'margin-top:5px' },
        h('span', { class: 'dim' }, progress ? `${progress.phase}…` : 'Reading layers…'),
        h('button', { class: 'link', onclick: () => send({ type: 'cancel' }) }, 'Cancel'),
      ),
    );
  } else {
    kids.push(
      h('div', { style: 'height:7px' }),
      h('div', { class: 'row between' },
        h('label', { class: 'opt' },
          h('span', { class: 'switch' },
            h('input', {
              type: 'checkbox', checked: settings.liveSync,
              onchange: (e: Event) =>
                send({ type: 'liveSync', enabled: (e.target as HTMLInputElement).checked }),
            }),
            h('span', { class: 'track' }), h('span', { class: 'thumb' }),
          ),
          h('span', {}, 'Live Sync'),
        ),
        h('button', {
          class: 'link',
          onclick: () => { optionsOpen = !optionsOpen; render(); },
        }, optionsOpen ? 'Hide options' : 'Options'),
      ),
    );
  }
  return h('div', { class: 'pad divider' }, ...kids);
}

function optionsPanel(): HTMLElement {
  const set = (patch: Partial<PluginSettings>) => send({ type: 'settings', settings: patch });

  const select = (
    label: string, key: keyof PluginSettings, options: [string, string][],
  ) =>
    h('div', { class: 'row between', style: 'margin-top:7px' },
      h('span', {}, label),
      h('select', {
        onchange: (e: Event) =>
          set({ [key]: (e.target as HTMLSelectElement).value } as Partial<PluginSettings>),
      }, ...options.map(([v, t]) =>
        h('option', { value: v, selected: settings[key] === v }, t))),
    );

  const check = (label: string, key: keyof PluginSettings) =>
    h('label', { class: 'opt', style: 'margin-top:7px' },
      h('input', {
        type: 'checkbox', checked: Boolean(settings[key]),
        onchange: (e: Event) =>
          set({ [key]: (e.target as HTMLInputElement).checked } as Partial<PluginSettings>),
      }),
      h('span', {}, label),
    );

  return h('div', { class: 'pad divider' },
    h('h2', {}, 'Options'),
    select('Vector shapes', 'vectorStrategy', [
      ['NATIVE', 'Native only'], ['AUTO', 'Automatic'], ['RASTER', 'Always image'],
    ]),
    select('Clip frames', 'clipFrames', [
      ['AUTO', 'Follow Figma'], ['ON', 'Always'], ['OFF', 'Never'],
    ]),
    select('Colour', 'colorHandling', [
      ['MATCH_SRGB', 'Match Figma (sRGB)'], ['PROJECT_MANAGED', 'Use project colour'],
    ]),
    check('Preserve hierarchy', 'preserveHierarchy'),
    check('Include hidden layers', 'includeHidden'),
    check('Flatten unsupported layers', 'flattenUnsupported'),
  );
}

function logPanel(): HTMLElement | null {
  if (!log.length && !lastResult) return null;
  const glyph = (s: string) => (s === 'ERROR' ? '✕' : s === 'WARNING' ? '⚠' : '✓');
  const cls = (s: string) => (s === 'ERROR' ? 'err' : s === 'WARNING' ? 'warn' : 'ok');

  return h('div', { class: 'pad divider' },
    h('div', { class: 'row between' },
      h('h2', {}, 'Transfer log'),
      lastResult ? h('span', { class: 'dim mono', style: 'font-size:9.5px' }, lastResult) : '',
    ),
    h('div', { class: 'log', style: 'margin-top:7px' },
      ...(log.length
        ? log.slice(0, 60).map((d) =>
            h('div', { class: 'entry' },
              h('span', { class: `glyph ${cls(d.severity)}` }, glyph(d.severity)),
              h('span', {},
                d.nodeName ? h('b', {}, `${d.nodeName} `) : '',
                d.message),
            ))
        : [h('div', { class: 'entry dim' }, 'No warnings.')]),
    ),
  );
}

function offlinePanel(): HTMLElement {
  return h('div', { class: 'pad divider' },
    h('div', { class: 'card' },
      h('div', { class: 'title' }, 'Bridge not running'),
      h('div', { class: 'dim', style: 'margin-top:3px' },
        connectionError
          ? connectionError
          : 'Start the Figma Fusion Bridge app on this Mac, then press Retry.'),
      h('div', { style: 'height:8px' }),
      h('button', { onclick: () => void connect() }, 'Retry'),
    ),
  );
}

function render(): void {
  const app = document.getElementById('app')!;
  app.textContent = '';
  app.append(statusPanel());

  if (phase === 'pairing') {
    app.append(pairingPanel());
  } else if (!status) {
    app.append(offlinePanel());
  } else {
    app.append(selectionPanel(), actionPanel());
    if (optionsOpen) app.append(optionsPanel());
  }
  const logEl = logPanel();
  if (logEl) app.append(logEl);

  send({ type: 'resize', height: app.getBoundingClientRect().height + 2 });
}

// ---------------------------------------------------------------------------
// Controller messages
// ---------------------------------------------------------------------------

window.onmessage = (event: MessageEvent) => {
  const msg = event.data?.pluginMessage as ControllerToUi | undefined;
  if (!msg) return;

  switch (msg.type) {
    case 'selection':
      selection = msg.summary;
      render();
      break;
    case 'settings':
      settings = msg.settings;
      // First delivery carries the stored token, so connecting waits for it —
      // otherwise the first attempt always looks unpaired.
      if (!settingsReady) {
        settingsReady = true;
        void connect();
      }
      render();
      break;
    case 'progress':
      progress = { phase: msg.phase, done: msg.done, total: msg.total };
      render();
      break;
    case 'document':
      void deliver(msg.document, msg.assets);
      break;
    case 'validation':
      log = msg.diagnostics;
      phase = 'idle';
      render();
      break;
    case 'error':
      phase = 'idle';
      progress = null;
      lastResult = msg.message;
      log = [{
        severity: 'ERROR', code: 'PLUGIN_ERROR', message: msg.message,
        ...(msg.detail ? { detail: msg.detail } : {}),
      }];
      render();
      break;
  }
};

render();
send({ type: 'ready' });
// connect() runs once settings arrive, since they carry the pairing token.
// Re-check periodically so the panel notices the bridge starting or stopping
// without the user having to press anything.
setInterval(() => {
  if (settingsReady && phase === 'idle') void connect();
}, 5000);
