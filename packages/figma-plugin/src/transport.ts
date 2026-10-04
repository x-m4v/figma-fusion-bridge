/**
 * Talking to the local bridge.
 *
 * This runs in the plugin's UI iframe, which is the only part of a Figma plugin
 * with network access, and only to origins listed in `manifest.json`.
 *
 * Security model: a loopback port is reachable from *any* web page the user has
 * open, so the port alone is not a permission. The bridge shows a short pairing
 * code; the user types it once; the plugin stores the resulting token. Without
 * it every request is refused, so a hostile page cannot drive Resolve even
 * though it can reach the port.
 *
 * Host name, not IP: Figma's manifest rejects literal addresses in
 * `allowedDomains`, so requests must go to `localhost`. That resolves to both
 * `127.0.0.1` and `::1` and Chromium may try either first, which is why the
 * bridge binds both loopback families.
 *
 * Assets go over plain HTTP rather than through the WebSocket. Base64 on a
 * socket inflates binary by a third and forces the whole payload through one
 * message; a POST per asset streams, parallelises, and lets the bridge skip
 * anything it already has cached.
 */
const PORTS = [8787, 8788, 8789, 8790, 8791];

export interface BridgeStatus {
  version: string;
  paired: boolean;
  resolveConnected: boolean;
  fusionReady: boolean;
  lastTransferAt?: string;
}

export class TransportError extends Error {
  constructor(
    message: string,
    readonly detail?: string,
  ) {
    super(message);
  }
}

export class BridgeTransport {
  private port: number | null = null;
  private token: string | null = null;

  get connected(): boolean {
    return this.port !== null && this.token !== null;
  }

  get currentPort(): number | null {
    return this.port;
  }

  setToken(token: string | null): void {
    this.token = token;
  }

  /** Find the bridge by trying each allowed port. */
  async discover(preferred?: number): Promise<number | null> {
    const order = preferred ? [preferred, ...PORTS.filter((p) => p !== preferred)] : PORTS;
    for (const port of order) {
      try {
        const res = await fetch(`http://localhost:${port}/api/hello`, {
          method: 'GET',
          // A short deadline: the bridge is on this machine, so a port that
          // does not answer immediately is not the bridge.
          signal: timeout(700),
        });
        if (!res.ok) continue;
        const body = (await res.json()) as { app?: string };
        if (body.app === 'figma-fusion-bridge') {
          this.port = port;
          return port;
        }
      } catch {
        // Nothing listening, or something else is. Try the next port.
      }
    }
    this.port = null;
    return null;
  }

  private url(path: string): string {
    if (this.port === null) throw new TransportError('Not connected to the bridge.');
    return `http://localhost:${this.port}${path}`;
  }

  private headers(extra?: Record<string, string>): Record<string, string> {
    return {
      ...(this.token ? { 'X-FFBridge-Token': this.token } : {}),
      'X-FFBridge-Client': 'figma',
      ...extra,
    };
  }

  /** Exchange the code shown in the bridge app for a durable token. */
  async pair(code: string): Promise<string> {
    const res = await fetch(this.url('/api/pair'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: code.trim().toUpperCase() }),
      signal: timeout(8000),
    });
    if (res.status === 403) {
      throw new TransportError('That code is not right. Check the Figma Fusion Bridge app.');
    }
    if (!res.ok) {
      throw new TransportError('Pairing failed.', `HTTP ${res.status}`);
    }
    const body = (await res.json()) as { token?: string };
    if (!body.token) throw new TransportError('The bridge did not return a token.');
    this.token = body.token;
    return body.token;
  }

  async status(): Promise<BridgeStatus> {
    const res = await fetch(this.url('/api/status'), {
      headers: this.headers(),
      signal: timeout(3000),
    });
    if (res.status === 401) throw new TransportError('unpaired');
    if (!res.ok) throw new TransportError('The bridge did not respond.', `HTTP ${res.status}`);
    return (await res.json()) as BridgeStatus;
  }

  /** Ask which of these assets the bridge already has, so we upload only new ones. */
  async filterKnownAssets(ids: string[]): Promise<Set<string>> {
    if (ids.length === 0) return new Set();
    try {
      const res = await fetch(this.url('/api/asset/known'), {
        method: 'POST',
        headers: this.headers({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ ids }),
        signal: timeout(5000),
      });
      if (!res.ok) return new Set();
      const body = (await res.json()) as { known?: string[] };
      return new Set(body.known ?? []);
    } catch {
      // If the check fails, upload everything. Slower, never wrong.
      return new Set();
    }
  }

  async uploadAsset(
    id: string,
    mimeType: string,
    suggestedName: string,
    bytes: Uint8Array,
  ): Promise<void> {
    const res = await fetch(this.url(`/api/asset/${id}`), {
      method: 'PUT',
      headers: this.headers({
        'Content-Type': mimeType || 'application/octet-stream',
        'X-FFBridge-Filename': encodeURIComponent(suggestedName),
      }),
      body: bytes as BodyInit,
      signal: timeout(120000),
    });
    if (!res.ok) {
      throw new TransportError(
        `The image "${suggestedName}" could not be uploaded.`,
        `HTTP ${res.status}`,
      );
    }
  }

  async sendDocument(document: unknown): Promise<{ transferId: string }> {
    const res = await fetch(this.url('/api/transfer'), {
      method: 'POST',
      headers: this.headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(document),
      signal: timeout(60000),
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        detail = (await res.text()).slice(0, 300) || detail;
      } catch {
        /* keep the status code */
      }
      throw new TransportError('The bridge rejected the transfer.', detail);
    }
    return (await res.json()) as { transferId: string };
  }
}

/** AbortSignal.timeout is not available in every Figma iframe runtime. */
function timeout(ms: number): AbortSignal {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}
