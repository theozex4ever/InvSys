import { readFileSync, writeFileSync } from 'node:fs';
const html = readFileSync('index.html', 'utf8').replace(
  '<script type="module" src="/src/main.ts"></script>',
  '<link rel="stylesheet" href="./style.css"><script defer src="./app.js"></script>',
);
writeFileSync('dist/index.html', html);
