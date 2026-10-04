import { z } from 'zod';
import { RGBA, Vec2, Matrix2D, BlendMode } from './primitives.js';

/**
 * Paints (fills and strokes).
 *
 * A deliberate design point: `opacity` on a paint is kept separate from the
 * owning node's `opacity`. Design tools treat these as two different things and
 * so must we — a 40% fill inside a 70% layer is not the same as a 28% fill,
 * because the layer opacity also scales the stroke, the shadow and every
 * sibling inside a group. Collapsing them is the single most common way a
 * design-to-motion bridge silently changes a design, so the schema forbids it
 * structurally by never providing a place to store the product.
 */

export const GradientStop = z.object({
  /** 0..1 along the gradient axis. */
  position: z.number(),
  color: RGBA,
});
export type GradientStop = z.infer<typeof GradientStop>;

export const SolidPaint = z.object({
  type: z.literal('SOLID'),
  visible: z.boolean().default(true),
  opacity: z.number().min(0).max(1).default(1),
  blendMode: BlendMode.default('NORMAL'),
  color: RGBA,
});

export const GradientPaint = z.object({
  type: z.enum([
    'GRADIENT_LINEAR',
    'GRADIENT_RADIAL',
    'GRADIENT_ANGULAR',
    'GRADIENT_DIAMOND',
  ]),
  visible: z.boolean().default(true),
  opacity: z.number().min(0).max(1).default(1),
  blendMode: BlendMode.default('NORMAL'),
  stops: z.array(GradientStop).min(1),
  /**
   * Maps the unit gradient space onto the node's bounding box.
   *
   * The unit square is [0,1]x[0,1]; a linear gradient runs from (0, 0.5) to
   * (1, 0.5) in that space before the transform is applied. Angle, length and
   * skew are all encoded here rather than being pre-decomposed, because
   * decomposing early loses information for non-uniform transforms. The builder
   * decomposes once, in one tested place.
   */
  transform: Matrix2D,
  /**
   * Pre-decomposed endpoints in the node's local pixel space, supplied by the
   * producer as a convenience and a cross-check. Consumers should prefer
   * `transform` and use these only to validate their own decomposition.
   */
  handles: z
    .object({ start: Vec2, end: Vec2, width: Vec2.optional() })
    .optional(),
});

export const ImagePaintScaleMode = z.enum(['FILL', 'FIT', 'CROP', 'TILE', 'STRETCH']);

export const ImagePaint = z.object({
  type: z.literal('IMAGE'),
  visible: z.boolean().default(true),
  opacity: z.number().min(0).max(1).default(1),
  blendMode: BlendMode.default('NORMAL'),
  /** References `Asset.id` in the document's asset table. */
  assetId: z.string(),
  scaleMode: ImagePaintScaleMode.default('FILL'),
  /** Present for CROP mode; maps the image onto the node's box. */
  imageTransform: Matrix2D.optional(),
  /** Present for TILE mode. */
  scalingFactor: z.number().optional(),
  rotation: z.number().default(0),
});

export const Paint = z.discriminatedUnion('type', [
  SolidPaint,
  GradientPaint.extend({ type: z.literal('GRADIENT_LINEAR') }),
  GradientPaint.extend({ type: z.literal('GRADIENT_RADIAL') }),
  GradientPaint.extend({ type: z.literal('GRADIENT_ANGULAR') }),
  GradientPaint.extend({ type: z.literal('GRADIENT_DIAMOND') }),
  ImagePaint,
]);
export type Paint = z.infer<typeof Paint>;
export type SolidPaint = z.infer<typeof SolidPaint>;
export type ImagePaint = z.infer<typeof ImagePaint>;
export type GradientPaintT = z.infer<typeof GradientPaint>;

export function isGradient(p: Paint): p is GradientPaintT & { type: GradientPaintT['type'] } {
  return p.type.startsWith('GRADIENT_');
}

/** Where a stroke sits relative to the path. Reproduced geometrically in Fusion. */
export const StrokeAlign = z.enum(['INSIDE', 'OUTSIDE', 'CENTER']);
export type StrokeAlign = z.infer<typeof StrokeAlign>;

export const StrokeCap = z.enum(['NONE', 'ROUND', 'SQUARE', 'ARROW_LINES', 'ARROW_EQUILATERAL']);
export const StrokeJoin = z.enum(['MITER', 'BEVEL', 'ROUND']);

export const StrokeStyle = z.object({
  /** Each entry is an independent paint layer, painted bottom-up. */
  paints: z.array(Paint).default([]),
  weight: z.number().default(0),
  align: StrokeAlign.default('CENTER'),
  cap: StrokeCap.default('NONE'),
  join: StrokeJoin.default('MITER'),
  miterLimit: z.number().default(4),
  dashPattern: z.array(z.number()).default([]),
});
export type StrokeStyle = z.infer<typeof StrokeStyle>;
