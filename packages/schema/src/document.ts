import { z } from 'zod';
import { Rect } from './primitives.js';
import { DesignNode } from './node.js';
import { FontRef } from './text.js';
import { SCHEMA_VERSION } from './version.js';

/**
 * The interchange document — the single contract between the producer plugin,
 * the bridge and the Fusion builder.
 *
 * Nothing in here mentions Figma except as a value of `source.app`. That is the
 * whole point: adding Sketch, Illustrator or plain SVG later means writing a new
 * producer, not touching the builder.
 */

export const AssetKind = z.enum(['IMAGE', 'SVG']);

export const Asset = z.object({
  /** Content-addressed: the lowercase hex SHA-256 of the bytes. */
  id: z.string(),
  kind: AssetKind,
  /** SHA-256 of the payload; equals `id` but stated explicitly for clarity. */
  sha256: z.string(),
  mimeType: z.string(),
  byteLength: z.number().int().min(0),
  /** Pixel dimensions for IMAGE; viewBox dimensions for SVG. */
  width: z.number().optional(),
  height: z.number().optional(),
  /** Name suggestion for the cache file. Sanitised by the bridge before use. */
  suggestedName: z.string().default(''),
  /**
   * Bytes are NOT inlined here. They travel over the HTTP asset channel and are
   * stored content-addressed by the bridge, so the same image used twenty times
   * is transferred and stored once.
   */
  uploaded: z.boolean().default(false),
});
export type Asset = z.infer<typeof Asset>;

export const Severity = z.enum(['INFO', 'WARNING', 'ERROR']);

/**
 * A diagnostic. Every unsupported or approximated thing produces one of these.
 * Nothing is ever dropped silently — that rule is enforced by making the
 * builder's fallback paths require a diagnostic argument.
 */
export const Diagnostic = z.object({
  severity: Severity,
  /** Stable machine code, e.g. "FONT_MISSING", "EFFECT_APPROXIMATED". */
  code: z.string(),
  /** One sentence a designer can act on. No stack traces here. */
  message: z.string(),
  nodeId: z.string().optional(),
  nodeName: z.string().optional(),
  /** Optional technical detail, shown only under "Advanced". */
  detail: z.string().optional(),
});
export type Diagnostic = z.infer<typeof Diagnostic>;

export const VectorStrategy = z.enum(['NATIVE', 'AUTO', 'RASTER']);
export const ClipFramesMode = z.enum(['AUTO', 'ON', 'OFF']);
export const ColorHandling = z.enum(['MATCH_SRGB', 'PROJECT_MANAGED', 'ADVANCED']);

/** Producer-side options that change how the document was built. */
export const TransferOptions = z.object({
  vectorStrategy: VectorStrategy.default('AUTO'),
  clipFrames: ClipFramesMode.default('AUTO'),
  includeHidden: z.boolean().default(false),
  preserveHierarchy: z.boolean().default(true),
  flattenUnsupported: z.boolean().default(true),
  imageExportScale: z.number().default(2),
  colorHandling: ColorHandling.default('MATCH_SRGB'),
  /** Experimental: try to rebuild Auto Layout with live expressions. */
  preserveAutoLayout: z.boolean().default(false),
});
export type TransferOptions = z.infer<typeof TransferOptions>;

export const SourceInfo = z.object({
  app: z.enum(['figma', 'sketch', 'illustrator', 'svg', 'other']).default('figma'),
  appVersion: z.string().default(''),
  producerVersion: z.string(),
  documentId: z.string(),
  documentName: z.string().default(''),
  pageId: z.string().default(''),
  pageName: z.string().default(''),
});
export type SourceInfo = z.infer<typeof SourceInfo>;

export const InterchangeDocument = z.object({
  schemaVersion: z.string().default(SCHEMA_VERSION),
  /** New for every send. Ties logs, assets and Fusion node metadata together. */
  transferId: z.string(),
  createdAt: z.string(),
  source: SourceInfo,

  /**
   * The canvas the design is described against, in design pixels.
   *
   * `frame` is the bounding box of the selection in document coordinates; the
   * builder subtracts its origin so a selection anywhere on a huge Figma page
   * lands centred rather than thousands of pixels off-screen.
   */
  canvas: z.object({
    frame: Rect,
    /** Set when the selection is a single frame, so the comp can adopt its size. */
    rootFrameId: z.string().nullable().default(null),
  }),

  /** Ids of the nodes the user actually selected, in selection order. */
  selection: z.array(z.string()).default([]),
  nodes: z.array(DesignNode).default([]),
  assets: z.array(Asset).default([]),
  /** Every distinct font the document needs, for up-front resolution. */
  fonts: z.array(FontRef).default([]),
  options: TransferOptions,
  diagnostics: z.array(Diagnostic).default([]),
  extra: z.record(z.unknown()).default({}),
});
export type InterchangeDocument = z.infer<typeof InterchangeDocument>;

/**
 * Structural checks that a per-field schema cannot express.
 *
 * Kept separate from `InterchangeDocument.parse` so that a document can be
 * parsed and inspected (to show the user *what* is wrong) even when it is not
 * internally consistent.
 */
export function validateReferentialIntegrity(doc: InterchangeDocument): Diagnostic[] {
  const out: Diagnostic[] = [];
  const nodeIds = new Set(doc.nodes.map((n) => n.id));
  const assetIds = new Set(doc.assets.map((a) => a.id));

  if (nodeIds.size !== doc.nodes.length) {
    const seen = new Set<string>();
    for (const n of doc.nodes) {
      if (seen.has(n.id)) {
        out.push({
          severity: 'ERROR',
          code: 'DUPLICATE_NODE_ID',
          message: `Two layers share the id "${n.id}". Identity must be unique.`,
          nodeId: n.id,
          nodeName: n.name,
        });
      }
      seen.add(n.id);
    }
  }

  for (const n of doc.nodes) {
    if (n.parentId !== null && !nodeIds.has(n.parentId)) {
      out.push({
        severity: 'ERROR',
        code: 'ORPHAN_NODE',
        message: `Layer "${n.name}" refers to a parent that is not in this transfer.`,
        nodeId: n.id,
        nodeName: n.name,
        detail: `parentId=${n.parentId}`,
      });
    }
    if (n.fallback && !assetIds.has(n.fallback.assetId)) {
      out.push({
        severity: 'ERROR',
        code: 'MISSING_ASSET',
        message: `Layer "${n.name}" was exported as an image, but the image is missing.`,
        nodeId: n.id,
        nodeName: n.name,
        detail: `assetId=${n.fallback.assetId}`,
      });
    }
    for (const p of n.fills) {
      if (p.type === 'IMAGE' && !assetIds.has(p.assetId)) {
        out.push({
          severity: 'ERROR',
          code: 'MISSING_ASSET',
          message: `Image fill on "${n.name}" refers to an image that is missing.`,
          nodeId: n.id,
          nodeName: n.name,
          detail: `assetId=${p.assetId}`,
        });
      }
    }
  }

  for (const id of doc.selection) {
    if (!nodeIds.has(id)) {
      out.push({
        severity: 'WARNING',
        code: 'SELECTION_NOT_IN_NODES',
        message: 'A selected layer was not included in the transfer.',
        nodeId: id,
      });
    }
  }

  // Cycle detection: a malformed producer could create one and hang the builder.
  const parentOf = new Map(doc.nodes.map((n) => [n.id, n.parentId]));
  for (const n of doc.nodes) {
    const seen = new Set<string>([n.id]);
    let cur = n.parentId;
    while (cur != null) {
      if (seen.has(cur)) {
        out.push({
          severity: 'ERROR',
          code: 'HIERARCHY_CYCLE',
          message: `Layer "${n.name}" is part of a circular parent chain.`,
          nodeId: n.id,
          nodeName: n.name,
        });
        break;
      }
      seen.add(cur);
      cur = parentOf.get(cur) ?? null;
    }
  }

  return out;
}

/** Children of a node, in paint order (bottom first). */
export function childrenOf(doc: InterchangeDocument, parentId: string | null): DesignNode[] {
  return doc.nodes
    .filter((n) => n.parentId === parentId)
    .sort((a, b) => a.childIndex - b.childIndex);
}

/** Root nodes, in paint order. */
export function rootsOf(doc: InterchangeDocument): DesignNode[] {
  const ids = new Set(doc.nodes.map((n) => n.id));
  return doc.nodes
    .filter((n) => n.parentId === null || !ids.has(n.parentId))
    .sort((a, b) => a.childIndex - b.childIndex);
}
