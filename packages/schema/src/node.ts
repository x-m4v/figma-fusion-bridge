import { z } from 'zod';
import { Rect, Matrix2D, BlendMode } from './primitives.js';
import { Paint, StrokeStyle } from './paint.js';
import { Effect } from './effects.js';
import { TextPayload } from './text.js';

/**
 * The node model.
 *
 * Nodes are stored as a **flat array with parent links**, not as a nested tree.
 * Hierarchy is fully preserved by `parentId` + `childIndex`, and the flat form
 * buys three things that matter here:
 *
 *   1. Live Sync diffing is a map lookup by id instead of a tree walk.
 *   2. A 1000-node payload streams and validates incrementally.
 *   3. Re-parenting between transfers is representable without moving payloads.
 */

export const NodeKind = z.enum([
  'FRAME',
  'GROUP',
  'COMPONENT',
  'COMPONENT_SET',
  'INSTANCE',
  'SECTION',
  'RECTANGLE',
  'ELLIPSE',
  'POLYGON',
  'STAR',
  'LINE',
  'VECTOR',
  'BOOLEAN_OPERATION',
  'TEXT',
  /** Emitted when a node had to be flattened to an image (raster fallback). */
  'RASTER',
]);
export type NodeKind = z.infer<typeof NodeKind>;

export const BooleanOp = z.enum(['UNION', 'SUBTRACT', 'INTERSECT', 'EXCLUDE']);

/** Auto Layout, captured so a future release can rebuild it live in Fusion. */
export const LayoutSpec = z.object({
  mode: z.enum(['HORIZONTAL', 'VERTICAL', 'GRID', 'NONE']).default('NONE'),
  spacing: z.number().default(0),
  paddingTop: z.number().default(0),
  paddingRight: z.number().default(0),
  paddingBottom: z.number().default(0),
  paddingLeft: z.number().default(0),
  primaryAxisAlign: z.enum(['MIN', 'CENTER', 'MAX', 'SPACE_BETWEEN']).default('MIN'),
  counterAxisAlign: z.enum(['MIN', 'CENTER', 'MAX', 'BASELINE']).default('MIN'),
  primaryAxisSizing: z.enum(['FIXED', 'AUTO']).default('FIXED'),
  counterAxisSizing: z.enum(['FIXED', 'AUTO']).default('FIXED'),
  itemReverseZIndex: z.boolean().default(false),
});
export type LayoutSpec = z.infer<typeof LayoutSpec>;

export const GeometrySpec = z.object({
  /** Corner radii, always four values: top-left, top-right, bottom-right, bottom-left. */
  cornerRadii: z.tuple([z.number(), z.number(), z.number(), z.number()]).optional(),
  /** Figma's corner smoothing ("squircle-ness"), 0..1. Fusion has no equivalent. */
  cornerSmoothing: z.number().default(0),
  /** POLYGON / STAR. */
  pointCount: z.number().int().optional(),
  /** STAR only, 0..1. */
  innerRadiusRatio: z.number().optional(),
  /** ELLIPSE arc: start/end sweep in radians and inner radius ratio for donuts. */
  arc: z.object({ startAngle: z.number(), endAngle: z.number(), innerRadius: z.number() }).optional(),
  booleanOperation: BooleanOp.optional(),
});
export type GeometrySpec = z.infer<typeof GeometrySpec>;

/** Provenance for components and instances, so re-sync can reason about them. */
export const ComponentRef = z.object({
  componentId: z.string().optional(),
  componentKey: z.string().optional(),
  /** For INSTANCE: the id of the main component node when it is in this transfer. */
  mainComponentId: z.string().optional(),
  isExposedInstance: z.boolean().default(false),
});

export const DesignNode = z.object({
  /**
   * Stable identity from the source tool. This is the anchor for Live Sync and
   * it is never derived from name, index or position — all three of which the
   * user is free to change without meaning "this is a different object".
   */
  id: z.string(),
  parentId: z.string().nullable(),
  /** Position among siblings. 0 is the bottom-most / first-painted. */
  childIndex: z.number().int().min(0),
  kind: NodeKind,
  name: z.string(),

  visible: z.boolean().default(true),
  locked: z.boolean().default(false),
  /** Layer opacity. Never folded together with paint opacity. */
  opacity: z.number().min(0).max(1).default(1),
  blendMode: BlendMode.default('PASS_THROUGH'),

  /** Axis-aligned bounds in the document's coordinate space, before rotation. */
  bounds: Rect,
  /** Full absolute transform. Authoritative when it disagrees with `bounds`. */
  absoluteTransform: Matrix2D,
  /** Transform relative to the parent. */
  relativeTransform: Matrix2D,
  /** Convenience decomposition; consumers must treat the matrix as authoritative. */
  rotation: z.number().default(0),

  /** Frames only: whether children are clipped to the frame's bounds. */
  clipsContent: z.boolean().default(false),
  /** True when this node masks its later siblings. */
  isMask: z.boolean().default(false),
  maskType: z.enum(['ALPHA', 'VECTOR', 'LUMINANCE']).optional(),

  fills: z.array(Paint).default([]),
  stroke: StrokeStyle.optional(),
  effects: z.array(Effect).default([]),

  geometry: GeometrySpec.optional(),
  text: TextPayload.optional(),
  layout: LayoutSpec.optional(),
  component: ComponentRef.optional(),

  /**
   * Set when the producer decided this node cannot be rebuilt natively and
   * exported it instead. `assetId` points at an SVG or a raster in the asset
   * table. A node with a fallback still carries its real bounds and transform,
   * so it participates in layout and animation like any other.
   */
  fallback: z
    .object({
      reason: z.string(),
      format: z.enum(['SVG', 'PNG']),
      assetId: z.string(),
      /** Scale the raster was exported at, so the builder can size it back down. */
      exportScale: z.number().default(1),
    })
    .optional(),

  /** Free-form, forward-compatible. Unknown keys must be preserved, not dropped. */
  extra: z.record(z.unknown()).default({}),
});
export type DesignNode = z.infer<typeof DesignNode>;
