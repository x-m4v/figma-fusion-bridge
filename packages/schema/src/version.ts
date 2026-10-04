/**
 * Interchange schema versioning.
 *
 * The interchange document is the contract between three independently
 * versioned components (Figma plugin, macOS bridge, Resolve/Fusion builder).
 * They ship separately, so every document carries the schema version it was
 * written against and consumers decide compatibility explicitly.
 *
 * Semantics:
 *   MAJOR - breaking. A consumer must refuse a document with an unknown major.
 *   MINOR - additive. Older consumers must ignore fields they do not know.
 *   PATCH - clarification only. Never affects parsing.
 */

export const SCHEMA_VERSION = '1.0.0' as const;

/** Majors this build can read. Extend, never silently widen. */
export const SUPPORTED_MAJORS: readonly number[] = [1];

export interface SemVer {
  major: number;
  minor: number;
  patch: number;
}

export function parseSemVer(value: string): SemVer | null {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(value.trim());
  if (!m) return null;
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]) };
}

export type CompatibilityVerdict =
  | { kind: 'ok' }
  /** Document is older than us; migrations will be applied on read. */
  | { kind: 'migrate'; from: SemVer; to: SemVer }
  /** Document is newer within the same major; unknown fields will be ignored. */
  | { kind: 'forward'; documentVersion: SemVer; readerVersion: SemVer }
  | { kind: 'unsupported'; reason: string };

/**
 * Decide whether this build can read a document.
 *
 * Deliberately explicit rather than a boolean: the UI must be able to tell the
 * user *why* a transfer was refused, and "forward" is a warning, not an error.
 */
export function checkCompatibility(documentVersion: string): CompatibilityVerdict {
  const doc = parseSemVer(documentVersion);
  if (!doc) {
    return { kind: 'unsupported', reason: `Malformed schema version "${documentVersion}"` };
  }
  const reader = parseSemVer(SCHEMA_VERSION)!;

  if (!SUPPORTED_MAJORS.includes(doc.major)) {
    return {
      kind: 'unsupported',
      reason:
        `Document uses schema ${documentVersion}; this build reads major ` +
        `${SUPPORTED_MAJORS.join(', ')}. Update the component that is behind.`,
    };
  }
  if (doc.minor > reader.minor) {
    return { kind: 'forward', documentVersion: doc, readerVersion: reader };
  }
  if (doc.minor < reader.minor) {
    return { kind: 'migrate', from: doc, to: reader };
  }
  return { kind: 'ok' };
}
