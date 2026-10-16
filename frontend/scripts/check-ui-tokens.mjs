import { readdir, readFile } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const sourceDirectory = join(scriptDirectory, '..', 'src');
const violations = [];

async function inspect(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      await inspect(path);
      continue;
    }
    if (!/\.(?:tsx?|css)$/.test(entry.name) || entry.name === 'theme.css') continue;
    const source = await readFile(path, 'utf8');
    const lines = source.split(/\r?\n/);
    lines.forEach((line, index) => {
      if (/#(?:[0-9a-f]{3,8})\b|rgba?\s*\(|hsla?\s*\(/i.test(line)) {
        violations.push(`${relative(sourceDirectory, path)}:${index + 1}: hardcoded color`);
      }
      if (/\bclassName\s*=\s*["'`][^"'`]*\[[^\]]+\]/.test(line)) {
        violations.push(`${relative(sourceDirectory, path)}:${index + 1}: arbitrary Tailwind value`);
      }
    });
  }
}

await inspect(sourceDirectory);
if (violations.length) {
  console.error(`Design tokens are required for UI literals:\n${violations.join('\n')}`);
  process.exitCode = 1;
} else {
  console.log('UI token check passed: no hardcoded colors or arbitrary Tailwind values.');
}
