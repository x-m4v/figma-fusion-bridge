import { z } from 'zod';

/**
 * Geometry and colour primitives.
 *
 * Everything spatial in this schema is expressed in **source design pixels**
 * with the origin at the top-left of the document canvas and +Y pointing down
 * (the convention Figma, Sketch, Illustrator and SVG all share).
 *
 * Nothing here is normalised. Normalisation into Fusion's coordinate space is
 * the exclusive job of the CoordinateMapper in the Fusion builder, so that a
 * single well-tested module owns the conversion and it can be unit-tested
 * without either Figma or Resolve present.
 */

/** Linear, non-premultiplied RGBA. Components are 0..1, never 0..255. */
export const RGBA = z.object({
  r: z.number(),
  g: z.number(),
  b: z.number(),
  a: z.number().min(0).max(1).default(1),
});
export type RGBA = z.infer<typeof RGBA>;

export const Vec2 = z.object({ x: z.number(), y: z.number() });
export type Vec2 = z.infer<typeof Vec2>;

export const Rect = z.object({
  x: z.number(),
  y: z.number(),
  width: z.number(),
  height: z.number(),
});
export type Rect = z.infer<typeof Rect>;

/**
 * A 2D affine transform as two rows of three numbers:
 *
 *   | a c e |     x' = a*x + c*y + e
 *   | b d f |     y' = b*x + d*y + f
 *
 * Stored row-major as [[a, c, e], [b, d, f]] — the same shape Figma's
 * `absoluteTransform` and `gradientTransform` use, so no transposition happens
 * at the producer. Consumers must not assume the matrix is a pure
 * rotate+translate: skew and non-uniform scale are legal and must round-trip.
 */
export const Matrix2D = z.tuple([
  z.tuple([z.number(), z.number(), z.number()]),
  z.tuple([z.number(), z.number(), z.number()]),
]);
export type Matrix2D = z.infer<typeof Matrix2D>;

export const IDENTITY_MATRIX: Matrix2D = [
  [1, 0, 0],
  [0, 1, 0],
];

/**
 * Blend modes, named after the source design tool's vocabulary.
 * Mapping onto Fusion `ApplyMode` values happens in the builder, which also
 * emits a warning for any mode Fusion cannot reproduce exactly.
 */
export const BlendMode = z.enum([
  'PASS_THROUGH',
  'NORMAL',
  'DARKEN',
  'MULTIPLY',
  'LINEAR_BURN',
  'COLOR_BURN',
  'LIGHTEN',
  'SCREEN',
  'LINEAR_DODGE',
  'COLOR_DODGE',
  'OVERLAY',
  'SOFT_LIGHT',
  'HARD_LIGHT',
  'DIFFERENCE',
  'EXCLUSION',
  'HUE',
  'SATURATION',
  'COLOR',
  'LUMINOSITY',
]);
export type BlendMode = z.infer<typeof BlendMode>;
