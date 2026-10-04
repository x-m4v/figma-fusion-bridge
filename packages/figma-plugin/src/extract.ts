/**
 * Reads a Figma selection and produces an interchange document.
 *
 * This is the only file that knows Figma exists. Everything downstream — the
 * bridge, the Fusion builder — consumes the neutral interchange format, which
 * is what makes adding a Sketch or Illustrator producer later a matter of
 * writing a sibling to this file rather than touching the graph builder.
 *
 * Two Figma-specific hazards shape the code:
 *
 * `figma.mixed`
 *     Any property can come back as the `figma.mixed` symbol when a node's
 *     children or character ranges disagree. Reading it as a number gives
 *     `NaN`, which propagates silently into geometry. Every read of a
 *     mixed-capable property goes through a guard.
 *
 * Async everything
 *     Exports, image bytes and font metadata are all promises, and the plugin
 *     must stay responsive while they resolve. Work is chunked and yields to
 *     the event loop so the UI can show progress and honour Cancel.
 */
import type {
  Asset,
  BlendMode,
  DesignNode,
  Diagnostic,
  Effect as IcEffect,
  FontRef,
  InterchangeDocument,
  LetterSpacing,
  LineHeight,
  Matrix2D,
  NodeKind,
  Paint as IcPaint,
  StrokeStyle,
  TextPayload,
  TextSegment,
} from './interchange.js';
import type { PluginSettings, TransferAsset } from './messages.js';

const SCHEMA_VERSION = '1.0.0';
const PRODUCER_VERSION = '0.1.0';

/** How many nodes to process before yielding, so Cancel stays responsive. */
const CHUNK = 40;

export class CancelledError extends Error {
  constructor() {
    super('Transfer cancelled');
  }
}

export interface ExtractionResult {
  document: InterchangeDocument;
  assets: TransferAsset[];
}

export interface ExtractContext {
  settings: PluginSettings;
  onProgress?: (phase: string, done: number, total: number) => void;
  isCancelled?: () => boolean;
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function isMixed(value: unknown): value is symbol {
  return typeof value === 'symbol';
}

/** Read a possibly-mixed number, falling back rather than yielding NaN. */
function num(value: number | symbol | undefined, fallback = 0): number {
  if (value === undefined || isMixed(value)) return fallback;
  return Number.isFinite(value) ? value : fallback;
}

function toMatrix(t: Transform): Matrix2D {
  return [
    [t[0][0], t[0][1], t[0][2]],
    [t[1][0], t[1][1], t[1][2]],
  ];
}

const IDENTITY: Matrix2D = [
  [1, 0, 0],
  [0, 1, 0],
];

function invert(m: Matrix2D): Matrix2D | null {
  const [[a, c, e], [b, d, f]] = m;
  const det = a * d - b * c;
  if (Math.abs(det) < 1e-12) return null;
  const ia = d / det;
  const ib = -b / det;
  const ic = -c / det;
  const id = a / det;
  return [
    [ia, ic, -(ia * e + ic * f)],
    [ib, id, -(ib * e + id * f)],
  ];
}

function apply(m: Matrix2D, x: number, y: number): { x: number; y: number } {
  return { x: m[0][0] * x + m[0][1] * y + m[0][2], y: m[1][0] * x + m[1][1] * y + m[1][2] };
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  // The plugin sandbox has no WebCrypto, so the digest is computed here.
  // It only ever runs over image bytes, and it runs once per unique image
  // because the caller memoises on the result.
  return sha256(bytes);
}

/** Minimal SHA-256. Present because the plugin sandbox has no `crypto.subtle`. */
function sha256(data: Uint8Array): string {
  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  const H = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);

  const len = data.length;
  const bitLen = len * 8;
  const padded = new Uint8Array((((len + 8) >> 6) + 1) << 6);
  padded.set(data);
  padded[len] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 4, bitLen >>> 0, false);
  view.setUint32(padded.length - 8, Math.floor(bitLen / 0x100000000), false);

  const w = new Uint32Array(64);
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));

  for (let i = 0; i < padded.length; i += 64) {
    for (let t = 0; t < 16; t++) w[t] = view.getUint32(i + t * 4, false);
    for (let t = 16; t < 64; t++) {
      const s0 = rotr(w[t - 15]!, 7) ^ rotr(w[t - 15]!, 18) ^ (w[t - 15]! >>> 3);
      const s1 = rotr(w[t - 2]!, 17) ^ rotr(w[t - 2]!, 19) ^ (w[t - 2]! >>> 10);
      w[t] = (w[t - 16]! + s0 + w[t - 7]! + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let t = 0; t < 64; t++) {
      const S1 = rotr(e!, 6) ^ rotr(e!, 11) ^ rotr(e!, 25);
      const ch = (e! & f!) ^ (~e! & g!);
      const t1 = (h! + S1 + ch + K[t]! + w[t]!) >>> 0;
      const S0 = rotr(a!, 2) ^ rotr(a!, 13) ^ rotr(a!, 22);
      const maj = (a! & b!) ^ (a! & c!) ^ (b! & c!);
      const t2 = (S0 + maj) >>> 0;
      h = g; g = f; f = e;
      e = (d! + t1) >>> 0;
      d = c; c = b; b = a;
      a = (t1 + t2) >>> 0;
    }
    H[0] = (H[0]! + a!) >>> 0; H[1] = (H[1]! + b!) >>> 0;
    H[2] = (H[2]! + c!) >>> 0; H[3] = (H[3]! + d!) >>> 0;
    H[4] = (H[4]! + e!) >>> 0; H[5] = (H[5]! + f!) >>> 0;
    H[6] = (H[6]! + g!) >>> 0; H[7] = (H[7]! + h!) >>> 0;
  }
  return Array.from(H, (v) => v.toString(16).padStart(8, '0')).join('');
}

// ---------------------------------------------------------------------------
// The extractor
// ---------------------------------------------------------------------------

export class Extractor {
  private readonly nodes: DesignNode[] = [];
  private readonly assets = new Map<string, Asset>();
  private readonly assetBytes = new Map<string, TransferAsset>();
  private readonly fonts = new Map<string, FontRef>();
  private readonly diagnostics: Diagnostic[] = [];
  private processed = 0;
  private total = 0;

  constructor(private readonly ctx: ExtractContext) {}

  private check(): void {
    if (this.ctx.isCancelled?.()) throw new CancelledError();
  }

  private async tick(phase: string): Promise<void> {
    this.processed += 1;
    if (this.processed % CHUNK === 0) {
      this.ctx.onProgress?.(phase, this.processed, this.total);
      // Yield so the UI thread can paint and the Cancel button can be heard.
      await new Promise((r) => setTimeout(r, 0));
      this.check();
    }
  }

  private warn(code: string, message: string, node?: BaseNode, detail?: string): void {
    this.diagnostics.push({
      severity: 'WARNING',
      code,
      message,
      ...(node ? { nodeId: node.id, nodeName: node.name } : {}),
      ...(detail ? { detail } : {}),
    });
  }

  private info(code: string, message: string, node?: BaseNode): void {
    this.diagnostics.push({
      severity: 'INFO',
      code,
      message,
      ...(node ? { nodeId: node.id, nodeName: node.name } : {}),
    });
  }

  // -- entry point ---------------------------------------------------------

  async extract(selection: readonly SceneNode[]): Promise<ExtractionResult> {
    this.total = countNodes(selection, this.ctx.settings.includeHidden);

    for (let i = 0; i < selection.length; i++) {
      this.check();
      await this.visit(selection[i]!, null, i);
    }

    const frame = boundsOf(selection);
    const rootFrameId =
      selection.length === 1 && selection[0]!.type === 'FRAME' ? selection[0]!.id : null;

    const document: InterchangeDocument = {
      schemaVersion: SCHEMA_VERSION,
      transferId: makeTransferId(),
      createdAt: new Date().toISOString(),
      source: {
        app: 'figma',
        appVersion: '',
        producerVersion: PRODUCER_VERSION,
        documentId: figma.fileKey ?? figma.root.id,
        documentName: figma.root.name,
        pageId: figma.currentPage.id,
        pageName: figma.currentPage.name,
      },
      canvas: { frame, rootFrameId },
      selection: selection.map((n) => n.id),
      nodes: this.nodes,
      assets: Array.from(this.assets.values()),
      fonts: Array.from(this.fonts.values()),
      options: {
        vectorStrategy: this.ctx.settings.vectorStrategy,
        clipFrames: this.ctx.settings.clipFrames,
        includeHidden: this.ctx.settings.includeHidden,
        preserveHierarchy: this.ctx.settings.preserveHierarchy,
        flattenUnsupported: this.ctx.settings.flattenUnsupported,
        imageExportScale: this.ctx.settings.imageExportScale,
        colorHandling: this.ctx.settings.colorHandling,
        preserveAutoLayout: false,
      },
      diagnostics: this.diagnostics,
      extra: {},
    };

    return { document, assets: Array.from(this.assetBytes.values()) };
  }

  // -- traversal -----------------------------------------------------------

  private async visit(node: SceneNode, parentId: string | null, index: number): Promise<void> {
    if (!node.visible && !this.ctx.settings.includeHidden) return;
    this.check();

    const kind = mapKind(node);
    if (kind === null) {
      this.warn(
        'UNSUPPORTED_LAYER_TYPE',
        `"${node.name}" is a ${node.type.toLowerCase().replace(/_/g, ' ')} layer, which cannot be imported.`,
        node,
      );
      return;
    }

    const record = await this.buildNode(node, kind, parentId, index);
    if (record === null) return;
    this.nodes.push(record);
    await this.tick('Reading layers');

    if (this.ctx.settings.preserveHierarchy && 'children' in node && !record.fallback) {
      const children = node.children;
      for (let i = 0; i < children.length; i++) {
        await this.visit(children[i]!, node.id, i);
      }
    }
  }

  private async buildNode(
    node: SceneNode,
    kind: NodeKind,
    parentId: string | null,
    index: number,
  ): Promise<DesignNode | null> {
    const transform = 'absoluteTransform' in node ? toMatrix(node.absoluteTransform) : IDENTITY;
    const relative = 'relativeTransform' in node ? toMatrix(node.relativeTransform) : IDENTITY;
    const width = 'width' in node ? node.width : 0;
    const height = 'height' in node ? node.height : 0;

    const record: DesignNode = {
      id: node.id,
      parentId,
      childIndex: index,
      kind,
      name: node.name,
      visible: node.visible,
      locked: 'locked' in node ? node.locked : false,
      opacity: 'opacity' in node ? num(node.opacity, 1) : 1,
      blendMode: ('blendMode' in node ? node.blendMode : 'PASS_THROUGH') as BlendMode,
      bounds: { x: transform[0][2], y: transform[1][2], width, height },
      absoluteTransform: transform,
      relativeTransform: relative,
      rotation: 'rotation' in node ? num(node.rotation, 0) : 0,
      clipsContent: 'clipsContent' in node ? node.clipsContent : false,
      isMask: 'isMask' in node ? node.isMask : false,
      fills: [],
      effects: [],
      extra: {},
    };

    if ('maskType' in node && node.isMask) {
      record.maskType = node.maskType as DesignNode['maskType'];
    }

    // Paints, strokes, effects.
    if ('fills' in node) record.fills = await this.readPaints(node.fills, node);
    if ('strokes' in node) {
      const stroke = await this.readStroke(node);
      if (stroke) record.stroke = stroke;
    }
    if ('effects' in node) record.effects = this.readEffects(node.effects, node);

    // Geometry.
    const geometry = this.readGeometry(node);
    if (geometry) record.geometry = geometry;

    // Text.
    if (node.type === 'TEXT') {
      record.text = await this.readText(node);
    }

    // Auto Layout, captured so a later release can rebuild it live.
    if ('layoutMode' in node && node.layoutMode !== 'NONE') {
      record.layout = this.readLayout(node);
    }

    // Component provenance.
    if (node.type === 'COMPONENT' || node.type === 'COMPONENT_SET') {
      record.component = { componentId: node.id, componentKey: node.key, isExposedInstance: false };
    } else if (node.type === 'INSTANCE') {
      const main = await node.getMainComponentAsync().catch(() => null);
      record.component = {
        ...(main ? { mainComponentId: main.id, componentKey: main.key } : {}),
        isExposedInstance: node.isExposedInstance ?? false,
      };
    }

    // Anything that cannot be rebuilt natively is exported instead.
    const fallback = await this.maybeExport(node, kind);
    if (fallback) record.fallback = fallback;

    return record;
  }

  // -- paints --------------------------------------------------------------

  private async readPaints(
    paints: readonly Paint_[] | symbol,
    node: SceneNode,
  ): Promise<IcPaint[]> {
    if (isMixed(paints)) {
      this.warn(
        'MIXED_FILLS',
        `"${node.name}" has different fills on different parts, so only its first fill was used.`,
        node,
      );
      return [];
    }
    const out: IcPaint[] = [];
    for (const p of paints) {
      const converted = await this.readPaint(p, node);
      if (converted) out.push(converted);
    }
    return out;
  }

  private async readPaint(paint: Paint_, node: SceneNode): Promise<IcPaint | null> {
    const common = {
      visible: paint.visible !== false,
      opacity: paint.opacity ?? 1,
      blendMode: (paint.blendMode ?? 'NORMAL') as BlendMode,
    };

    if (paint.type === 'SOLID') {
      return {
        type: 'SOLID',
        ...common,
        color: { r: paint.color.r, g: paint.color.g, b: paint.color.b, a: paint.opacity ?? 1 },
      };
    }

    if (
      paint.type === 'GRADIENT_LINEAR' ||
      paint.type === 'GRADIENT_RADIAL' ||
      paint.type === 'GRADIENT_ANGULAR' ||
      paint.type === 'GRADIENT_DIAMOND'
    ) {
      const transform = toMatrix(paint.gradientTransform);
      // Handles are computed here as well as in the builder. The builder is
      // authoritative; these let it cross-check its own decomposition, and they
      // are the only thing available if a future producer cannot supply a matrix.
      const inv = invert(transform);
      const handles = inv
        ? { start: apply(inv, 0, 0.5), end: apply(inv, 1, 0.5), width: apply(inv, 0, 1) }
        : undefined;
      if (!inv) {
        this.warn(
          'GRADIENT_DEGENERATE',
          `A gradient on "${node.name}" has no usable direction and may look different.`,
          node,
        );
      }
      return {
        type: paint.type,
        ...common,
        stops: paint.gradientStops.map((s) => ({
          position: s.position,
          color: { r: s.color.r, g: s.color.g, b: s.color.b, a: s.color.a },
        })),
        transform,
        ...(handles ? { handles } : {}),
      };
    }

    if (paint.type === 'IMAGE') {
      const assetId = await this.captureImage(paint, node);
      if (!assetId) return null;
      return {
        type: 'IMAGE',
        ...common,
        assetId,
        scaleMode: paint.scaleMode,
        ...(paint.imageTransform ? { imageTransform: toMatrix(paint.imageTransform) } : {}),
        ...(paint.scalingFactor !== undefined ? { scalingFactor: paint.scalingFactor } : {}),
        rotation: paint.rotation ?? 0,
      };
    }

    if (paint.type === 'VIDEO') {
      this.warn(
        'VIDEO_FILL_UNSUPPORTED',
        `"${node.name}" uses a video fill, which cannot be transferred. Add the video in Resolve instead.`,
        node,
      );
      return null;
    }

    // Figma keeps adding paint kinds. Naming the type in the message means a
    // user hitting a brand-new one gets something actionable rather than
    // "something was skipped".
    this.warn(
      'UNKNOWN_PAINT',
      `"${node.name}" uses a ${String(paint.type).toLowerCase().replace(/_/g, ' ')} fill, which cannot be transferred yet.`,
      node,
    );
    return null;
  }

  private async captureImage(paint: ImagePaint, node: SceneNode): Promise<string | null> {
    if (!paint.imageHash) return null;
    try {
      const image = figma.getImageByHash(paint.imageHash);
      if (!image) {
        this.warn('IMAGE_MISSING', `An image on "${node.name}" could not be read.`, node);
        return null;
      }
      const bytes = await image.getBytesAsync();
      const digest = await sha256Hex(bytes);
      if (!this.assets.has(digest)) {
        const size = await image.getSizeAsync().catch(() => null);
        this.assets.set(digest, {
          id: digest,
          kind: 'IMAGE',
          sha256: digest,
          mimeType: sniffMime(bytes),
          byteLength: bytes.length,
          ...(size ? { width: size.width, height: size.height } : {}),
          suggestedName: `${sanitiseName(node.name)}.${extensionFor(sniffMime(bytes))}`,
          uploaded: false,
        });
        this.assetBytes.set(digest, {
          id: digest,
          mimeType: sniffMime(bytes),
          suggestedName: `${sanitiseName(node.name)}.${extensionFor(sniffMime(bytes))}`,
          bytes,
        });
      }
      return digest;
    } catch (err) {
      this.warn(
        'IMAGE_READ_FAILED',
        `An image on "${node.name}" could not be exported.`,
        node,
        String(err),
      );
      return null;
    }
  }

  // -- strokes -------------------------------------------------------------

  private async readStroke(node: SceneNode & MinimalStrokesMixin): Promise<StrokeStyle | null> {
    const strokes = node.strokes;
    if (isMixed(strokes) || !strokes.length) return null;

    const weight = 'strokeWeight' in node ? num(node.strokeWeight, 0) : 0;
    if (weight <= 0) return null;

    if ('strokeWeight' in node && isMixed(node.strokeWeight)) {
      this.warn(
        'MIXED_STROKE_WEIGHT',
        `"${node.name}" has different stroke widths on different sides. A single width was used.`,
        node,
      );
    }

    const paints = await this.readPaints(strokes, node);
    return {
      paints,
      weight,
      align: ('strokeAlign' in node ? node.strokeAlign : 'CENTER') as StrokeStyle['align'],
      cap: ('strokeCap' in node && !isMixed(node.strokeCap)
        ? node.strokeCap
        : 'NONE') as StrokeStyle['cap'],
      join: ('strokeJoin' in node && !isMixed(node.strokeJoin)
        ? node.strokeJoin
        : 'MITER') as StrokeStyle['join'],
      miterLimit: 'strokeMiterLimit' in node ? num(node.strokeMiterLimit, 4) : 4,
      dashPattern: 'dashPattern' in node ? Array.from(node.dashPattern) : [],
    };
  }

  // -- effects -------------------------------------------------------------

  private readEffects(effects: readonly Effect_[] | symbol, node: SceneNode): IcEffect[] {
    if (isMixed(effects)) return [];
    const out: IcEffect[] = [];
    for (const e of effects) {
      if (e.type === 'DROP_SHADOW' || e.type === 'INNER_SHADOW') {
        out.push({
          type: e.type,
          visible: e.visible,
          color: { r: e.color.r, g: e.color.g, b: e.color.b, a: e.color.a },
          offset: { x: e.offset.x, y: e.offset.y },
          radius: e.radius,
          spread: e.spread ?? 0,
          blendMode: e.blendMode ?? 'NORMAL',
          showShadowBehindNode:
            e.type === 'DROP_SHADOW' ? (e.showShadowBehindNode ?? true) : true,
        });
      } else if (e.type === 'LAYER_BLUR' || e.type === 'BACKGROUND_BLUR') {
        out.push({ type: e.type, visible: e.visible, radius: e.radius });
        if (e.type === 'BACKGROUND_BLUR' && e.visible) {
          this.info(
            'BACKGROUND_BLUR_EXPERIMENTAL',
            `"${node.name}" uses background blur, which Fusion reproduces approximately.`,
            node,
          );
        }
      } else {
        this.warn(
          'EFFECT_UNSUPPORTED',
          `The "${String((e as { type: string }).type).toLowerCase().replace(/_/g, ' ')}" effect on "${node.name}" has no Fusion equivalent and was skipped.`,
          node,
        );
      }
    }
    return out;
  }

  // -- geometry ------------------------------------------------------------

  private readGeometry(node: SceneNode): DesignNode['geometry'] | null {
    const geo: NonNullable<DesignNode['geometry']> = { cornerSmoothing: 0 };
    let any = false;

    if ('cornerRadius' in node) {
      const r = node.cornerRadius;
      if (isMixed(r) && 'topLeftRadius' in node) {
        geo.cornerRadii = [
          num(node.topLeftRadius),
          num(node.topRightRadius),
          num(node.bottomRightRadius),
          num(node.bottomLeftRadius),
        ];
        any = true;
      } else if (typeof r === 'number' && r > 0) {
        geo.cornerRadii = [r, r, r, r];
        any = true;
      }
    }
    if ('cornerSmoothing' in node && num(node.cornerSmoothing) > 0) {
      geo.cornerSmoothing = num(node.cornerSmoothing);
      any = true;
    }
    if (node.type === 'POLYGON' || node.type === 'STAR') {
      geo.pointCount = num(node.pointCount, 3);
      any = true;
    }
    if (node.type === 'STAR') {
      geo.innerRadiusRatio = num(node.innerRadius, 0.5);
    }
    if (node.type === 'ELLIPSE') {
      const arc = node.arcData;
      if (arc && (arc.startingAngle !== 0 || Math.abs(arc.endingAngle - Math.PI * 2) > 1e-6 || arc.innerRadius > 0)) {
        geo.arc = {
          startAngle: arc.startingAngle,
          endAngle: arc.endingAngle,
          innerRadius: arc.innerRadius,
        };
        any = true;
      }
    }
    if (node.type === 'BOOLEAN_OPERATION') {
      geo.booleanOperation = node.booleanOperation as NonNullable<DesignNode['geometry']>['booleanOperation'];
      any = true;
    }
    return any ? geo : null;
  }

  private readLayout(node: SceneNode & BaseFrameMixin): NonNullable<DesignNode['layout']> {
    return {
      mode: node.layoutMode as 'HORIZONTAL' | 'VERTICAL' | 'NONE',
      spacing: num(node.itemSpacing, 0),
      paddingTop: num(node.paddingTop, 0),
      paddingRight: num(node.paddingRight, 0),
      paddingBottom: num(node.paddingBottom, 0),
      paddingLeft: num(node.paddingLeft, 0),
      primaryAxisAlign: node.primaryAxisAlignItems as 'MIN' | 'CENTER' | 'MAX' | 'SPACE_BETWEEN',
      counterAxisAlign: node.counterAxisAlignItems as 'MIN' | 'CENTER' | 'MAX' | 'BASELINE',
      primaryAxisSizing: node.primaryAxisSizingMode as 'FIXED' | 'AUTO',
      counterAxisSizing: node.counterAxisSizingMode as 'FIXED' | 'AUTO',
      itemReverseZIndex: node.itemReverseZIndex ?? false,
    };
  }

  // -- text ----------------------------------------------------------------

  private async readText(node: TextNode): Promise<TextPayload> {
    const font = this.readFont(node.fontName, node.fontWeight);
    const segments = this.readSegments(node);
    const mixed =
      isMixed(node.fontName) ||
      isMixed(node.fontSize) ||
      segments.length > 1;

    if (mixed) {
      this.info(
        'TEXT_MIXED_STYLES',
        `"${node.name}" mixes styles within one text layer. It stays editable, but may need re-styling in Fusion.`,
        node,
      );
    }

    return {
      characters: node.characters,
      font,
      fontSize: num(node.fontSize, 16),
      letterSpacing: this.readLetterSpacing(node.letterSpacing),
      lineHeight: this.readLineHeight(node.lineHeight),
      paragraphSpacing: num(node.paragraphSpacing, 0),
      paragraphIndent: num(node.paragraphIndent, 0),
      alignHorizontal: node.textAlignHorizontal,
      alignVertical: node.textAlignVertical,
      autoResize: node.textAutoResize as TextPayload['autoResize'],
      hasMixedStyles: mixed,
      segments,
    };
  }

  private readFont(fontName: FontName | symbol, weight: number | symbol): FontRef {
    if (isMixed(fontName)) {
      return { family: 'Mixed', style: 'Regular', italic: false };
    }
    const ref: FontRef = {
      family: fontName.family,
      style: fontName.style,
      italic: /italic|oblique/i.test(fontName.style),
    };
    if (!isMixed(weight)) ref.weight = weight;
    this.fonts.set(`${ref.family}|${ref.style}`, ref);
    return ref;
  }

  private readSegments(node: TextNode): TextSegment[] {
    try {
      const raw = node.getStyledTextSegments([
        'fontName',
        'fontSize',
        'fills',
        'letterSpacing',
        'lineHeight',
        'textCase',
        'textDecoration',
      ]);
      return raw.map((s) => ({
        start: s.start,
        end: s.end,
        font: this.readFont(s.fontName, 400),
        fontSize: s.fontSize,
        letterSpacing: this.readLetterSpacing(s.letterSpacing),
        lineHeight: this.readLineHeight(s.lineHeight),
        fills: (s.fills as Paint_[])
          .filter((p) => p.type === 'SOLID')
          .map((p) => ({
            type: 'SOLID' as const,
            visible: p.visible !== false,
            opacity: p.opacity ?? 1,
            blendMode: 'NORMAL' as BlendMode,
            color: {
              r: (p as SolidPaint).color.r,
              g: (p as SolidPaint).color.g,
              b: (p as SolidPaint).color.b,
              a: p.opacity ?? 1,
            },
          })),
        textCase: s.textCase as TextSegment['textCase'],
        textDecoration: s.textDecoration as TextSegment['textDecoration'],
      }));
    } catch {
      // Segment reading is a refinement; text still transfers without it.
      return [];
    }
  }

  private readLetterSpacing(value: LetterSpacing_ | symbol): LetterSpacing {
    if (isMixed(value)) return { unit: 'PERCENT', value: 0 };
    return value.unit === 'PIXELS'
      ? { unit: 'PIXELS', value: value.value }
      : { unit: 'PERCENT', value: value.value };
  }

  private readLineHeight(value: LineHeight_ | symbol): LineHeight {
    if (isMixed(value)) return { unit: 'AUTO' };
    if (value.unit === 'AUTO') return { unit: 'AUTO' };
    return value.unit === 'PIXELS'
      ? { unit: 'PIXELS', value: value.value }
      : { unit: 'PERCENT', value: value.value };
  }

  // -- fallback export -----------------------------------------------------

  private async maybeExport(
    node: SceneNode,
    kind: NodeKind,
  ): Promise<DesignNode['fallback'] | null> {
    const strategy = this.ctx.settings.vectorStrategy;
    const isVector = kind === 'VECTOR' || kind === 'BOOLEAN_OPERATION';

    // NATIVE never exports; AUTO exports only what it cannot rebuild; RASTER
    // exports everything that is not a container.
    if (strategy === 'NATIVE') return null;
    const shouldExport =
      strategy === 'RASTER'
        ? kind !== 'FRAME' && kind !== 'GROUP' && kind !== 'COMPONENT' && kind !== 'INSTANCE'
        : isVector;
    if (!shouldExport) return null;
    if (!('exportAsync' in node)) return null;

    // SVG first: it stays resolution independent, and Fusion can consume it.
    const wantSvg = strategy !== 'RASTER' && isVector;
    try {
      if (wantSvg) {
        const svg = await node.exportAsync({ format: 'SVG_STRING' });
        const bytes = encodeUtf8(svg);
        const digest = await sha256Hex(bytes);
        this.registerAsset(digest, 'SVG', 'image/svg+xml', bytes, `${sanitiseName(node.name)}.svg`);
        this.info(
          'VECTOR_EXPORTED_AS_SVG',
          `"${node.name}" is a custom vector shape, so it was exported as SVG to keep it sharp at any resolution.`,
          node,
        );
        return { reason: 'custom vector path', format: 'SVG', assetId: digest, exportScale: 1 };
      }

      const scale = Math.max(1, this.ctx.settings.imageExportScale);
      const bytes = await node.exportAsync({
        format: 'PNG',
        constraint: { type: 'SCALE', value: scale },
      });
      const digest = await sha256Hex(bytes);
      this.registerAsset(digest, 'IMAGE', 'image/png', bytes, `${sanitiseName(node.name)}.png`);
      return {
        reason: strategy === 'RASTER' ? 'raster mode' : 'unsupported geometry',
        format: 'PNG',
        assetId: digest,
        exportScale: scale,
      };
    } catch (err) {
      this.warn(
        'EXPORT_FAILED',
        `"${node.name}" could not be exported and was skipped.`,
        node,
        String(err),
      );
      return null;
    }
  }

  private registerAsset(
    digest: string,
    kind: 'IMAGE' | 'SVG',
    mime: string,
    bytes: Uint8Array,
    name: string,
  ): void {
    if (this.assets.has(digest)) return;
    this.assets.set(digest, {
      id: digest,
      kind,
      sha256: digest,
      mimeType: mime,
      byteLength: bytes.length,
      suggestedName: name,
      uploaded: false,
    });
    this.assetBytes.set(digest, { id: digest, mimeType: mime, suggestedName: name, bytes });
  }
}

// ---------------------------------------------------------------------------
// Free functions
// ---------------------------------------------------------------------------

type Paint_ = Paint;   // Figma's own union — includes members we do not handle
type Effect_ = Effect; // Figma's own union — includes members we do not handle
type LetterSpacing_ = { unit: 'PIXELS' | 'PERCENT'; value: number };
type LineHeight_ = { unit: 'PIXELS' | 'PERCENT'; value: number } | { unit: 'AUTO' };

export function mapKind(node: SceneNode): NodeKind | null {
  switch (node.type) {
    case 'FRAME':
    case 'COMPONENT':
    case 'COMPONENT_SET':
    case 'INSTANCE':
    case 'GROUP':
    case 'SECTION':
    case 'RECTANGLE':
    case 'ELLIPSE':
    case 'POLYGON':
    case 'STAR':
    case 'LINE':
    case 'VECTOR':
    case 'BOOLEAN_OPERATION':
    case 'TEXT':
      return node.type as NodeKind;
    default:
      return null;
  }
}

export function countNodes(nodes: readonly SceneNode[], includeHidden: boolean): number {
  let n = 0;
  const walk = (list: readonly SceneNode[]) => {
    for (const node of list) {
      if (!node.visible && !includeHidden) continue;
      n += 1;
      if ('children' in node) walk(node.children);
    }
  };
  walk(nodes);
  return n;
}

export function boundsOf(nodes: readonly SceneNode[]): {
  x: number;
  y: number;
  width: number;
  height: number;
} {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of nodes) {
    const box = 'absoluteBoundingBox' in node ? node.absoluteBoundingBox : null;
    if (!box) continue;
    minX = Math.min(minX, box.x);
    minY = Math.min(minY, box.y);
    maxX = Math.max(maxX, box.x + box.width);
    maxY = Math.max(maxY, box.y + box.height);
  }
  if (!Number.isFinite(minX)) return { x: 0, y: 0, width: 0, height: 0 };
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

function makeTransferId(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `${Date.now().toString(36)}-${rand}`;
}

function sanitiseName(name: string): string {
  return name.replace(/[^\w\-. ]+/g, '').trim().slice(0, 60) || 'layer';
}

function sniffMime(bytes: Uint8Array): string {
  if (bytes.length > 8 && bytes[0] === 0x89 && bytes[1] === 0x50) return 'image/png';
  if (bytes.length > 3 && bytes[0] === 0xff && bytes[1] === 0xd8) return 'image/jpeg';
  if (bytes.length > 12 && bytes[8] === 0x57 && bytes[9] === 0x45) return 'image/webp';
  if (bytes.length > 4 && bytes[0] === 0x47 && bytes[1] === 0x49) return 'image/gif';
  return 'application/octet-stream';
}

function extensionFor(mime: string): string {
  return mime === 'image/png'
    ? 'png'
    : mime === 'image/jpeg'
      ? 'jpg'
      : mime === 'image/webp'
        ? 'webp'
        : mime === 'image/gif'
          ? 'gif'
          : 'bin';
}

function encodeUtf8(text: string): Uint8Array {
  const out: number[] = [];
  for (let i = 0; i < text.length; i++) {
    let c = text.charCodeAt(i);
    if (c < 0x80) out.push(c);
    else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
    else if (c >= 0xd800 && c <= 0xdbff && i + 1 < text.length) {
      const c2 = text.charCodeAt(++i);
      c = 0x10000 + ((c & 0x3ff) << 10) + (c2 & 0x3ff);
      out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    } else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
  }
  return new Uint8Array(out);
}
