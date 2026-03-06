import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

describe('layout css constraints', () => {
  it('keeps workspace fixed and table internally scrollable', () => {
    const cssPath = path.resolve(path.dirname(new URL(import.meta.url).pathname), './styles.css');
    const css = fs.readFileSync(cssPath, 'utf-8');

    expect(css).toMatch(/\.workspace\s*\{[\s\S]*height:\s*calc\(100vh\s*-\s*104px\)/);
    expect(css).toMatch(/\.workspace\s*\{[\s\S]*overflow:\s*hidden/);
    expect(css).toMatch(/\.table-shell\s*\{[\s\S]*overflow:\s*auto/);
    expect(css).toMatch(/\.sheet-spreadsheet \.Spreadsheet__header\s*\{[\s\S]*position:\s*sticky/);
    expect(css).toMatch(/\.sheet-spreadsheet \.Spreadsheet__header,\s*[\s\S]*\.sheet-spreadsheet \.Spreadsheet__cell\s*\{[\s\S]*text-overflow:\s*ellipsis/);
  });
});
