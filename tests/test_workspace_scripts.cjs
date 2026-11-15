'use strict';
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const ui = path.join(root, 'src', 'tactics_ui');
const html = fs.readFileSync(path.join(ui, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script src="\/([^"]+)"/g)].map(match => match[1]);
assert.ok(scripts.length > 0, 'index.html must load scripts');
const source = scripts.map(name => fs.readFileSync(path.join(ui, name), 'utf8'))
  .join('\n;\n');
new vm.Script(source, { filename: 'concatenated-ui.js' });

const squad = fs.readFileSync(path.join(ui, 'squad-editor.js'), 'utf8');
assert.match(squad, /function showSquadSelection\(/, 'squad selection must be declared');
assert.doesNotMatch(squad, /^showSquadSelection\s*=/m, 'strict mode assignment is invalid');
console.log('workspace scripts compile and squad selection is declared');
