// Release gate for the built desktop assets (run after `npm run build:assets`).
//
// The desktop shell loads dist/ over file:// with no HTTP server, so the build
// must be self-contained: the three expected files, wired together by relative
// paths, with no network references, inside a size budget. Exits non-zero with
// every violation listed, and appends a table to the GitHub job summary.
import { appendFileSync, readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const DIST = new URL('../dist/', import.meta.url);

// Gzipped byte budgets: roughly 1.6x the current build. Raising one is a
// reviewed decision in a PR, not a way to make CI pass.
const BUDGETS = { 'app.js': 25_000, 'style.css': 8_000, 'index.html': 1_000 };

// XML namespace identifiers are inert strings, not fetches.
const ALLOWED_URLS = new Set(['http://www.w3.org/2000/svg']);

const failures = [];
const rows = [];

for (const [name, budget] of Object.entries(BUDGETS)) {
  const url = new URL(name, DIST);
  let raw;
  try {
    raw = readFileSync(url);
  } catch {
    failures.push(`${name} is missing`);
    continue;
  }
  if (raw.length === 0) failures.push(`${name} is empty`);
  const gz = gzipSync(raw, { level: 9 }).length;
  if (gz > budget) failures.push(`${name} is ${gz} B gzipped; budget is ${budget} B`);
  rows.push(`| \`${name}\` | ${raw.length} | ${gz} | ${budget} | ${gz <= budget ? 'pass' : '**over**'} |`);

  const text = raw.toString('utf8');
  for (const match of text.matchAll(/(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}[^\s"'`)]*/gi)) {
    const found = match[0];
    if (![...ALLOWED_URLS].some((allowed) => found.startsWith(allowed))) {
      failures.push(`${name} references a network URL: ${found}`);
    }
  }
}

const html = (() => {
  try {
    return readFileSync(new URL('index.html', DIST), 'utf8');
  } catch {
    return '';
  }
})();
for (const ref of ['./app.js', './style.css']) {
  if (!html.includes(ref)) failures.push(`index.html does not load ${ref}`);
}
if (html.includes('/src/main.ts')) failures.push('index.html still points at the dev entry /src/main.ts');
if (/type="module"/.test(html)) failures.push('index.html uses a module script, which file:// blocks');

const summary = [
  '### Frontend bundle',
  '',
  '| File | Bytes | Gzipped | Budget | Result |',
  '| --- | ---: | ---: | ---: | --- |',
  ...rows,
  '',
  failures.length ? `**${failures.length} problem(s):**\n${failures.map((f) => `- ${f}`).join('\n')}` : 'Self-contained and within budget.',
  '',
].join('\n');

console.log(summary);
if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary);
if (failures.length) process.exit(1);
