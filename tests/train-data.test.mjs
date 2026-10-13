import test from 'node:test';
import assert from 'node:assert/strict';
import { getJSON } from '../src/train-data.mjs';

const siteURL = 'https://rail-globe.example/data/trains/index.json';
const railGoURL = 'https://api.railgo.dev/query/train/G1';

// Spy on real timers: the tests exercise the exported function and fetch
// options, response parsing, rejection and abort events, never source text.
function timers(t) {
  const scheduled = t.mock.method(globalThis, 'setTimeout');
  const cleared = t.mock.method(globalThis, 'clearTimeout');
  return {
    scheduled,
    cleared,
    assertCleared() {
      assert.equal(scheduled.mock.callCount(), 1);
      assert.equal(cleared.mock.callCount(), 1);
      assert.equal(cleared.mock.calls[0].arguments[0], scheduled.mock.calls[0].result);
    },
  };
}

test('same-origin site JSON uses session credentials, revalidates cache and returns parsed data', async t => {
  const clock = timers(t);
  const payload = { schemaVersion: 1, trips: [{ number: 'G1' }] };
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(payload));

  assert.deepEqual(await getJSON(siteURL), payload);
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, siteURL);
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.cache, 'no-cache');
  assert.ok(options.signal instanceof AbortSignal);
  assert.equal(options.signal.aborted, false);
  assert.equal(clock.scheduled.mock.calls[0].arguments[1], 30000);
  clock.assertCleared();
});

test('cross-origin RailGo keeps same-origin credential scope and never requests include', async t => {
  const clock = timers(t);
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ delay: 0 }));
  const target = new URL(railGoURL);
  assert.notEqual(target.origin, new URL(siteURL).origin);

  assert.deepEqual(await getJSON(target, 5000), { delay: 0 });
  const [url, options] = fetch.mock.calls[0].arguments;
  assert.equal(url, target);
  // The browser's same-origin mode excludes credentials on this different
  // origin; do not broaden it to include to repair the site's authenticated URL.
  assert.equal(new Request(url, options).credentials, 'same-origin');
  assert.notEqual(options.credentials, 'include');
  assert.equal(options.headers, undefined);
  assert.equal(clock.scheduled.mock.calls[0].arguments[1], 5000);
  clock.assertCleared();
});

test('HTTP 401 preserves its numeric status and clears the timer without parsing an error body', async t => {
  const clock = timers(t);
  const response = new Response('Unauthorized', { status: 401 });
  const parse = t.mock.method(response, 'json');
  t.mock.method(globalThis, 'fetch', async () => response);

  await assert.rejects(getJSON(siteURL), error => {
    assert.equal(error.message, 'HTTP 401');
    assert.equal(error.status, 401);
    return true;
  });
  assert.equal(parse.mock.callCount(), 0);
  clock.assertCleared();
});

test('malformed JSON propagates its parsing error and clears the timer', async t => {
  const clock = timers(t);
  t.mock.method(globalThis, 'fetch', async () => new Response('{broken json'));

  await assert.rejects(getJSON(siteURL), SyntaxError);
  clock.assertCleared();
});

test('a network failure is preserved and clears the timer', async t => {
  const clock = timers(t);
  const failure = new TypeError('Failed to fetch');
  t.mock.method(globalThis, 'fetch', async () => { throw failure; });

  await assert.rejects(getJSON(siteURL), error => error === failure);
  clock.assertCleared();
});

test('deadline aborts a pending fetch before response headers and clears the timer', async t => {
  const clock = timers(t);
  let signal;
  t.mock.method(globalThis, 'fetch', (_, options) => {
    signal = options.signal;
    return new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    });
  });

  await assert.rejects(getJSON(siteURL, 10), { name: 'AbortError' });
  assert.equal(signal.aborted, true);
  clock.assertCleared();
});

test('deadline stays active while JSON response bytes are still arriving', async t => {
  const clock = timers(t);
  let signal;
  let bodyStarted = false;
  t.mock.method(globalThis, 'fetch', async (_, options) => {
    signal = options.signal;
    const body = new ReadableStream({
      start(controller) {
        bodyStarted = true;
        controller.enqueue(new TextEncoder().encode('{"trips":'));
        // Model fetch's response body being interrupted by its abort signal.
        signal.addEventListener('abort', () => controller.error(signal.reason), { once: true });
      },
    });
    return new Response(body, { headers: { 'Content-Type': 'application/json' } });
  });

  await assert.rejects(getJSON(siteURL, 10), { name: 'AbortError' });
  assert.equal(bodyStarted, true);
  assert.equal(signal.aborted, true);
  clock.assertCleared();
});

test('the timer is cleared only after a successful streamed JSON body completes', async t => {
  const clock = timers(t);
  let bodyController;
  t.mock.method(globalThis, 'fetch', async () => new Response(new ReadableStream({
    start(controller) { bodyController = controller; },
  })));

  const result = getJSON(siteURL);
  await Promise.resolve();
  assert.equal(clock.cleared.mock.callCount(), 0);
  bodyController.enqueue(new TextEncoder().encode('{"ready":true}'));
  bodyController.close();
  assert.deepEqual(await result, { ready: true });
  clock.assertCleared();
});
