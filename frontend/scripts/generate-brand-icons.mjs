import sharp from 'sharp';
import { readFile, writeFile } from 'node:fs/promises';

// Rebuild app icons from the editable vector master, without a remote service.
const source = new URL('../public/smart-ward-mark.svg', import.meta.url);
for (const size of [180, 192, 512]) {
  await sharp(await readFile(source)).resize(size, size).png()
    .toFile(new URL(`../public/smart-ward-${size}.png`, import.meta.url).pathname);
}
// A PNG-backed ICO replaces the framework favicon with the same identity.
const png = await sharp(await readFile(source)).resize(32, 32).png().toBuffer();
const header = Buffer.alloc(22);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(1, 4);
header[6] = 32;
header[7] = 32;
header.writeUInt16LE(1, 10);
header.writeUInt16LE(32, 12);
header.writeUInt32LE(png.length, 14);
header.writeUInt32LE(22, 18);
await writeFile(new URL('../app/favicon.ico', import.meta.url), Buffer.concat([header, png]));
