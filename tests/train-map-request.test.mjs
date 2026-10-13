import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext, runInNewContext } from 'node:vm';

const page = readFileSync(new URL('../src/app.html', import.meta.url), 'utf8');
const pmtilesBundle = readFileSync(new URL('../vendor/pmtiles.js', import.meta.url), 'utf8');
const baseURI = 'https://private.example/projects/rail/index.html?tab=trains#map';
const remoteArchive = 'https://rail-globe.github.io/data/tiles/cn.pmtiles';
const localArchive = 'https://private.example/projects/rail/data/tiles/cn.pmtiles';

function pageRequests() {
  // Execute the real inline callbacks so these tests catch changes to the page,
  // including accidentally feeding a nested PMTiles URL through new URL().
  const abs = page.match(/^\s*const abs\s*=\s*(.+);\s*$/m);
  const transformRequest = page.match(/^\s*transformRequest:\s*(.+),\s*$/m);
  assert.ok(abs, 'app.html must expose the inline abs declaration to this regression test');
  assert.ok(transformRequest, 'app.html must expose the MapLibre transformRequest callback');
  return runInNewContext(
    `const abs = ${abs[1]};\n({ abs, transformRequest: ${transformRequest[1]} });`,
    { URL, document: { baseURI } },
    { filename: 'app-request-callbacks.js' },
  );
}

test('the page preserves PMTiles archive and XYZ URLs, including the embedded HTTPS scheme', () => {
  const { abs, transformRequest } = pageRequests();
  for (const archive of [remoteArchive, localArchive]) {
    for (const url of [`pmtiles://${archive}`, `pmtiles://${archive}/3/6/3`]) {
      assert.equal(abs(url), url);
      assert.equal(transformRequest(url, 'Source').url, url);
      assert.equal(transformRequest(url, 'Tile').url, url);
    }
  }
});

test('the page preserves localglyph templates, font names, and range requests verbatim', () => {
  const { abs, transformRequest } = pageRequests();
  for (const url of [
    'localglyph://{fontstack}/{range}',
    'localglyph://sans/0-255',
    'localglyph://Noto Sans CJK SC/19968-20223',
  ]) {
    assert.equal(abs(url), url);
    assert.equal(transformRequest(url, 'Glyphs').url, url);
  }
});

test('ordinary relative URLs resolve against the page and HTTPS URLs retain their destination', () => {
  const { abs, transformRequest } = pageRequests();
  for (const [url, expected] of [
    ['data/glyphs.json', 'https://private.example/projects/rail/data/glyphs.json'],
    ['../data/lines.json', 'https://private.example/projects/data/lines.json'],
    ['/data/rail_hsr.geojson', 'https://private.example/data/rail_hsr.geojson'],
    [remoteArchive, remoteArchive],
    ['https://example.net/tiles/3/6/3.pbf?style=rail', 'https://example.net/tiles/3/6/3.pbf?style=rail'],
  ]) {
    assert.equal(abs(url), expected);
    assert.equal(transformRequest(url, 'Source').url, expected);
  }
});

test('MapLibre requests explicitly retain same-origin authentication without requiring cross-origin cookies', () => {
  const { transformRequest } = pageRequests();
  for (const url of [
    'data/rail_hsr.geojson',
    'data/glyphs.json',
    remoteArchive,
    `pmtiles://${remoteArchive}`,
    'localglyph://sans/0-255',
  ]) {
    assert.equal(transformRequest(url, 'Source').credentials, 'same-origin');
  }
});

function bundledProtocol() {
  const unexpectedFetches = [];
  const context = createContext({
    AbortController,
    Headers,
    TextDecoder,
    console,
    fetch: async url => {
      unexpectedFetches.push(String(url));
      throw new Error(`Unexpected PMTiles fetch: ${url}`);
    },
  });
  runInContext(pmtilesBundle, context, { filename: 'vendor/pmtiles.js' });
  return { protocol: new context.pmtiles.Protocol(), unexpectedFetches };
}

for (const [name, archiveURL] of [['remote', remoteArchive], ['same-origin', localArchive]]) {
  test(`the bundled PMTiles Protocol uses the registered ${name} archive after the page callback`, async () => {
    const { transformRequest } = pageRequests();
    const { protocol, unexpectedFetches } = bundledProtocol();
    const requestedTiles = [];
    const tileBytes = new Uint8Array([8, 1, 18, 0]);
    const archive = {
      source: { getKey: () => archiveURL },
      getHeader: async () => ({
        minZoom: 0, maxZoom: 13,
        minLon: 70, minLat: 15, maxLon: 138, maxLat: 55,
        tileType: 1,
      }),
      getZxy: async (z, x, y) => {
        requestedTiles.push([z, x, y]);
        return { data: tileBytes.buffer };
      },
    };
    protocol.add(archive);

    const sourceURL = `pmtiles://${archiveURL}`;
    const metadata = await protocol.tile(
      { ...transformRequest(sourceURL, 'Source'), type: 'json' },
      new AbortController(),
    );
    assert.equal(metadata.data.tiles[0], `${sourceURL}/{z}/{x}/{y}`);
    const tileURL = metadata.data.tiles[0].replace('{z}', '3').replace('{x}', '6').replace('{y}', '3');
    const tile = await protocol.tile(
      { ...transformRequest(tileURL, 'Tile'), type: 'arrayBuffer' },
      new AbortController(),
    );

    assert.equal(protocol.get(archiveURL), archive);
    assert.deepEqual(requestedTiles, [[3, 6, 3]]);
    assert.deepEqual(Array.from(tile.data), Array.from(tileBytes));
    assert.deepEqual(unexpectedFetches, [], 'a valid URL must not create a second, incorrectly addressed archive');
  });
}
