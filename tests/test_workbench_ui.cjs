'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const readAsset = file => fs.readFileSync(path.join(__dirname, '..', 'app', 'static', file), 'utf8');

function makeElement() {
  return {
    dataset: {}, handlers: {}, textContent: '', hidden: false, disabled: false,
    addEventListener(name, handler) { this.handlers[name] = handler; },
    replaceChildren(...children) { this.children = children; },
  };
}

function snapshot(count, status = 'no_device', states = {}, transports = 0) {
  return {
    usb: {status: 'ok', non_root_hub_count: count},
    adb: {status: 'ok', states, usb_transports: transports},
    health_status: status,
  };
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test('live USB and ADB changes update the picker without auto-running health', async () => {
  const html = readAsset('workbench.html');
  const elements = Object.fromEntries(Array.from(html.matchAll(/\bid="([\w-]+)"/g), ([, id]) => [id, makeElement()]));
  elements.platform.value = 'android';
  elements.action.value = 'connection';
  elements.metrics.hidden = true;
  const document = Object.assign(makeElement(), {getElementById: id => elements[id], createElement: makeElement});
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  let connection = snapshot(2);
  vm.runInNewContext(readAsset('workbench.js'), {
    document,
    async fetch(url) {
      requests.push(url);
      const response = url === '/api/connection' ? connection : {
        status: 'partial', android_version: '16', battery: {percent: 64},
      };
      return {ok: true, async json() { return response; }};
    },
    setTimeout(callback, delay) {
      assert.equal(delay, 3000);
      timers.set(++timerId, callback);
      return timerId;
    },
    clearTimeout(id) { timers.delete(id); },
  });
  async function poll(next) {
    connection = next;
    assert.equal(timers.size, 1);
    const [id, callback] = timers.entries().next().value;
    timers.delete(id);
    await callback();
  }
  function choose(task) {
    elements.action.value = task;
    elements.action.handlers.change();
  }

  await flush();
  assert.deepEqual(requests, ['/api/connection']);
  assert.equal(elements['connection-badge'].textContent, 'No phone confirmed');
  for (const platform of ['android', 'iphone']) {
    elements.platform.value = platform;
    for (const guide of ['connection', 'power', 'boot', 'storage', 'screen', 'audio', 'backup', 'account']) {
      choose(guide);
      assert.equal(elements['guide-panel'].hidden, false);
      assert.equal(elements.steps.children.length, 3);
    }
  }
  assert.match(elements.support.href, /^https:\/\/support\.apple\.com\//);
  choose('health');
  assert.equal(elements['health-panel'].hidden, false);
  assert.equal(elements.health.disabled, true);
  await poll(snapshot(3));
  assert.equal(elements['connection-badge'].textContent, 'USB device added');
  await poll(snapshot(3, 'unauthorized', {unauthorized: 1}, 1));
  assert.equal(elements['connection-badge'].textContent, 'Approval needed on Android');
  assert.equal(elements.health.disabled, true);
  await poll(snapshot(3, 'ready', {authorized: 1}, 1));
  assert.equal(elements['connection-badge'].textContent, 'Android connected via USB');
  assert.equal(elements.health.disabled, false);
  assert.ok(!requests.includes('/api/health'));
  await elements.health.handlers.click();
  await flush();
  assert.equal(requests.filter(url => url === '/api/health').length, 1);
  assert.equal(elements.metrics.hidden, false);
  assert.ok(elements.metrics.children.some(node => node.textContent === '64%'));
  await poll(snapshot(2));
  assert.equal(elements['connection-badge'].textContent, 'USB device removed');
  assert.equal(elements.metrics.hidden, true);
  assert.equal(elements.health.disabled, true);
  document.hidden = true;
  document.handlers.visibilitychange();
  assert.equal(timers.size, 0);
});
