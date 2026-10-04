/**
 * The interchange types, re-exported from the schema package.
 *
 * These are `import type` only, so zod never reaches the plugin bundle — the
 * plugin *produces* documents and does not need to validate them, and shipping
 * a validator into a sandboxed iframe would cost size for nothing. Keeping the
 * types pointed at the schema package means the contract cannot drift: a change
 * there breaks the plugin's typecheck immediately.
 */
export type {
  Asset,
  BlendMode,
  DesignNode,
  Diagnostic,
  Effect,
  FontRef,
  GradientStop,
  InterchangeDocument,
  LayoutSpec,
  LineHeight,
  LetterSpacing,
  Matrix2D,
  NodeKind,
  Paint,
  RGBA,
  Rect,
  SourceInfo,
  StrokeStyle,
  TextPayload,
  TextSegment,
  TransferOptions,
  Vec2,
} from '../../schema/src/index.js';
