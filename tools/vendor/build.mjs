// Bundle ProseMirror + markdown-it into maxbook/web/vendor/prosemirror/.
// Writes PACKAGES.txt listing exactly the packages whose code is in the bundle
// (from esbuild's metafile) and copies their licence files next to it.
import { build } from "esbuild";
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "..", "maxbook", "web", "vendor", "prosemirror");
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const result = await build({
  entryPoints: [join(here, "entry.mjs")],
  bundle: true,
  format: "esm",
  minify: true,
  target: "es2020",
  legalComments: "eof",
  metafile: true,
  outfile: join(out, "prosemirror.mjs"),
});

const names = new Set();
for (const input of Object.keys(result.metafile.inputs)) {
  const m = input.match(/node_modules\/((?:@[^/]+\/)?[^/]+)\//);
  if (m) names.add(m[1]);
}
const lines = ["Packages whose code is in prosemirror.mjs (built by tools/vendor/build.mjs):", ""];
for (const name of [...names].sort()) {
  const dir = join(here, "node_modules", name);
  const meta = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  lines.push(`${name}@${meta.version}  license: ${meta.license}`);
  const lic = readdirSync(dir).find((f) => /^licen[cs]e/i.test(f));
  if (lic) copyFileSync(join(dir, lic), join(out, `LICENSE-${name.replace("/", "_")}`));
  else lines.push(`  (no licence file in the package; licence per package.json: ${meta.license})`);
}
writeFileSync(join(out, "PACKAGES.txt"), lines.join("\n") + "\n");
console.log("built", join(out, "prosemirror.mjs"), [...names].length, "packages");
