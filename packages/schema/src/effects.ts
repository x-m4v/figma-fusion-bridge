import { z } from 'zod';
import { RGBA, Vec2 } from './primitives.js';

/**
 * Effects.
 *
 * Order matters. The array is stored in the source tool's own paint order and
 * consumers must preserve it; re-ordering blur and shadow changes the result.
 *
 * `offset` is kept as a Cartesian vector in design pixels rather than being
 * converted to the distance/angle form some compositors want. The conversion is
 * lossy in one direction (angle is undefined at zero distance) so it is done
 * once, late, in the builder, where it is tested.
 */

export const ShadowEffect = z.object({
  type: z.enum(['DROP_SHADOW', 'INNER_SHADOW']),
  visible: z.boolean().default(true),
  color: RGBA,
  /** +x right, +y down, in design pixels. */
  offset: Vec2,
  /** Gaussian-ish radius in design pixels, as authored. */
  radius: z.number(),
  /** Choke/spread in design pixels. Fusion has no direct equivalent; see builder. */
  spread: z.number().default(0),
  blendMode: z.string().default('NORMAL'),
  /** Figma-specific: whether the shadow is clipped to the shape's bounds. */
  showShadowBehindNode: z.boolean().default(true),
});

export const BlurEffect = z.object({
  type: z.enum(['LAYER_BLUR', 'BACKGROUND_BLUR']),
  visible: z.boolean().default(true),
  radius: z.number(),
});

export const Effect = z.discriminatedUnion('type', [
  ShadowEffect.extend({ type: z.literal('DROP_SHADOW') }),
  ShadowEffect.extend({ type: z.literal('INNER_SHADOW') }),
  BlurEffect.extend({ type: z.literal('LAYER_BLUR') }),
  BlurEffect.extend({ type: z.literal('BACKGROUND_BLUR') }),
]);
export type Effect = z.infer<typeof Effect>;
export type ShadowEffect = z.infer<typeof ShadowEffect>;
export type BlurEffect = z.infer<typeof BlurEffect>;
