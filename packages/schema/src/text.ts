import { z } from 'zod';
import { Paint, StrokeStyle } from './paint.js';

/**
 * Text.
 *
 * The goal is that text arrives in Fusion as real, re-typable Text+ — never as
 * a picture of text. Everything here exists to make that possible, which is why
 * font identity is carried as structured metadata (family + style + weight +
 * PostScript name) rather than a single display string: resolving a font to
 * something installed on the target machine is a matching problem, and matching
 * needs more than one signal.
 */

export const FontRef = z.object({
  family: z.string(),
  /** The source tool's style name, e.g. "Bold Italic", "Display Medium". */
  style: z.string(),
  /** Numeric weight 100..1000 when the source knows it. */
  weight: z.number().optional(),
  italic: z.boolean().default(false),
  /** PostScript name when available — the strongest matching signal. */
  postScriptName: z.string().optional(),
});
export type FontRef = z.infer<typeof FontRef>;

/** Line height, kept in the unit it was authored in. Converting early loses intent. */
export const LineHeight = z.discriminatedUnion('unit', [
  z.object({ unit: z.literal('PIXELS'), value: z.number() }),
  z.object({ unit: z.literal('PERCENT'), value: z.number() }),
  z.object({ unit: z.literal('AUTO') }),
]);
export type LineHeight = z.infer<typeof LineHeight>;

export const LetterSpacing = z.discriminatedUnion('unit', [
  z.object({ unit: z.literal('PIXELS'), value: z.number() }),
  z.object({ unit: z.literal('PERCENT'), value: z.number() }),
]);
export type LetterSpacing = z.infer<typeof LetterSpacing>;

/**
 * A run of characters sharing identical styling.
 *
 * Single-style text produces exactly one segment. Mixed-style text produces
 * several, and the builder decides — per the document's vector/text strategy —
 * whether to represent them with Text+ per-character styling or with several
 * Text+ nodes laid out side by side. Either way the text stays editable.
 */
export const TextSegment = z.object({
  /** Character offsets into `characters`, half-open [start, end). */
  start: z.number().int().min(0),
  end: z.number().int().min(0),
  font: FontRef,
  fontSize: z.number(),
  letterSpacing: LetterSpacing,
  lineHeight: LineHeight,
  fills: z.array(Paint).default([]),
  textCase: z.enum(['ORIGINAL', 'UPPER', 'LOWER', 'TITLE', 'SMALL_CAPS']).default('ORIGINAL'),
  textDecoration: z.enum(['NONE', 'UNDERLINE', 'STRIKETHROUGH']).default('NONE'),
});
export type TextSegment = z.infer<typeof TextSegment>;

export const TextPayload = z.object({
  characters: z.string(),
  /** Style of the whole node; always present, equals segment 0 for uniform text. */
  font: FontRef,
  fontSize: z.number(),
  letterSpacing: LetterSpacing,
  lineHeight: LineHeight,
  paragraphSpacing: z.number().default(0),
  paragraphIndent: z.number().default(0),
  alignHorizontal: z.enum(['LEFT', 'CENTER', 'RIGHT', 'JUSTIFIED']).default('LEFT'),
  alignVertical: z.enum(['TOP', 'CENTER', 'BOTTOM']).default('TOP'),
  autoResize: z.enum(['NONE', 'WIDTH_AND_HEIGHT', 'HEIGHT', 'TRUNCATE']).default('NONE'),
  /** True when segments differ; lets consumers take the fast path when false. */
  hasMixedStyles: z.boolean().default(false),
  segments: z.array(TextSegment).default([]),
  stroke: StrokeStyle.optional(),
});
export type TextPayload = z.infer<typeof TextPayload>;
