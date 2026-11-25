import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { crc32, inflateSync } from "node:zlib";

import { variantManifest } from "../../build.mjs";

const SIZES = [48, 96, 128];
const SYMBOL = new URL("../../../assets/brand/utubot-symbol.svg", import.meta.url);
const TILE = [0x4b, 0x3f, 0xe0];
const DOT = [0xc8, 0xf2, 0x3a];
const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function iconUrl(size) {
  return new URL(`../../assets/icons/icon-${size}.png`, import.meta.url);
}

function decode(bytes) {
  assert.deepEqual(bytes.subarray(0, 8), PNG_SIGNATURE, "a PNG");
  const chunks = [];
  let at = 8;
  while (at < bytes.length) {
    const length = bytes.readUInt32BE(at);
    const type = bytes.toString("latin1", at + 4, at + 8);
    const data = bytes.subarray(at + 8, at + 8 + length);
    const crc = bytes.readUInt32BE(at + 8 + length);
    assert.equal(crc32(bytes.subarray(at + 4, at + 8 + length)), crc, `${type} crc`);
    chunks.push({ type, data });
    at += 12 + length;
  }
  const header = chunks.find((chunk) => chunk.type === "IHDR").data;
  const width = header.readUInt32BE(0);
  const height = header.readUInt32BE(4);
  const depth = header[8];
  const color = header[9];
  const interlace = header[12];
  assert.deepEqual([depth, color, interlace], [8, 6, 0], "8-bit RGBA, not interlaced");
  const raw = inflateSync(Buffer.concat(chunks.filter((chunk) => chunk.type === "IDAT").map((chunk) => chunk.data)));
  const stride = width * 4;
  assert.equal(raw.length, (stride + 1) * height, "every row fits");
  const pixels = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)];
    const row = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let x = 0; x < stride; x += 1) {
      const left = x >= 4 ? pixels[y * stride + x - 4] : 0;
      const up = y > 0 ? pixels[(y - 1) * stride + x] : 0;
      const upLeft = x >= 4 && y > 0 ? pixels[(y - 1) * stride + x - 4] : 0;
      const add = { 0: 0, 1: left, 2: up, 3: Math.floor((left + up) / 2), 4: paeth(left, up, upLeft) }[filter];
      assert.notEqual(add, undefined, `filter ${filter} is known`);
      pixels[y * stride + x] = (row[x] + add) & 0xff;
    }
  }
  return { width, height, pixels, stride };
}

function paeth(left, up, upLeft) {
  const guess = left + up - upLeft;
  const dl = Math.abs(guess - left);
  const du = Math.abs(guess - up);
  const dul = Math.abs(guess - upLeft);
  return dl <= du && dl <= dul ? left : du <= dul ? up : upLeft;
}

function pixel(image, x, y) {
  const at = y * image.stride + x * 4;
  return [...image.pixels.subarray(at, at + 4)];
}

function near([r, g, b, a], [dr, dg, db]) {
  return a > 250 && Math.abs(r - dr) <= 3 && Math.abs(g - dg) <= 3 && Math.abs(b - db) <= 3;
}

test("the icon sizes are the ones the manifest asks for", () => {
  const manifest = variantManifest("firefox-unlisted");
  for (const size of SIZES) {
    assert.equal(manifest.icons[String(size)], `assets/icons/icon-${size}.png`, size);
    assert.equal(manifest.action.default_icon[String(size)], `assets/icons/icon-${size}.png`, size);
  }
});

test("every icon is the brand symbol rendered at its size", () => {
  for (const size of SIZES) {
    const image = decode(readFileSync(iconUrl(size)));
    assert.deepEqual([image.width, image.height], [size, size], `${size}px is square`);
    assert.equal(image.pixels[0], 0, `${size}px rows start with a filter byte`);
    assert.equal(pixel(image, 0, 0)[3], 0, `${size}px is transparent in the corner`);
    assert.equal(near(pixel(image, Math.round(size * 0.06), Math.round(size / 2)), TILE), true, `${size}px is the tile`);
    assert.equal(near(pixel(image, Math.round(size * 0.773), Math.round(size / 2)), DOT), true, `${size}px has the dot`);
  }
});

test("the icons come from the brand symbol", () => {
  const symbol = readFileSync(SYMBOL, "utf8");
  for (const shape of ["#4B3FE0", "#C8F23A"]) {
    assert.equal(symbol.toUpperCase().includes(shape), true, `the symbol draws ${shape}`);
  }
  const render = readFileSync(new URL("../../../assets/brand/render.py", import.meta.url), "utf8");
  for (const size of SIZES) {
    assert.equal(render.includes(`"icon-${size}.png"`), true, `render.py writes icon-${size}.png`);
  }
});
