/**
 * Plugin build.
 *
 * Figma loads exactly two files: one script for the sandboxed controller and
 * one self-contained HTML file for the UI iframe. The iframe cannot fetch
 * anything from disk, so the UI's CSS and JS are inlined into the HTML here
 * rather than referenced.
 */
import * as esbuild from 'esbuild';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes('--watch');

const shared = {
  bundle: true,
  target: 'es2020',
  format: 'iife',
  legalComments: 'none',
  logLevel: 'info',
};

async function buildUi() {
  const result = await esbuild.build({
    ...shared,
    entryPoints: [resolve(root, 'src/ui.ts')],
    write: false,
    minify: !watch,
  });
  const js = result.outputFiles[0].text;
  const html = await readFile(resolve(root, 'src/ui.html'), 'utf8');
  await mkdir(resolve(root, 'dist'), { recursive: true });
  await writeFile(
    resolve(root, 'dist/ui.html'),
    html.replace('/* __BUNDLE__ */', () => js),
    'utf8',
  );
}

async function buildCode() {
  await esbuild.build({
    ...shared,
    entryPoints: [resolve(root, 'src/code.ts')],
    outfile: resolve(root, 'dist/code.js'),
    minify: !watch,
  });
}

if (watch) {
  const ctx = await esbuild.context({
    ...shared,
    entryPoints: [resolve(root, 'src/code.ts')],
    outfile: resolve(root, 'dist/code.js'),
    plugins: [{ name: 'ui', setup: (b) => b.onEnd(buildUi) }],
  });
  await ctx.watch();
  console.log('watching…');
} else {
  await buildCode();
  await buildUi();
  console.log('built dist/code.js and dist/ui.html');
}
