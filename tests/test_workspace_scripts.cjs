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

const launcher = fs.readFileSync(path.join(root, 'Launcher.cs'), 'utf8');
assert.ok(launcher.includes('/workspace-controls.js'), 'launcher self-test must include workspace controls');
assert.ok(launcher.includes('/workspace.css'), 'launcher self-test must include workspace styles');
assert.ok(!launcher.includes('/save-mode.js'), 'launcher self-test must not request removed assets');
console.log('workspace scripts compile and retirement assets are wired');
