import {
  rm,
  readdir,
  readFile,
  writeFile,
  mkdir,
  copyFile,
  chmod,
} from "node:fs/promises"
import { join } from "node:path"

await rm("dist", { recursive: true, force: true })
const declarations = Bun.spawn(
  ["bun", "x", "tsc", "-p", "tsconfig.build.json"],
  { stdout: "inherit", stderr: "inherit" },
)
if ((await declarations.exited) !== 0)
  throw new Error("Declaration build failed")

// ESM declaration specifiers must also resolve with TypeScript's NodeNext mode.
async function fixDeclarations(directory: string): Promise<void> {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) await fixDeclarations(path)
    else if (entry.name.endsWith(".d.ts")) {
      const text = await readFile(path, "utf8")
      await writeFile(
        path,
        text.replace(
          /((?:from\s+|import\s*\()["'])(\.{1,2}\/[^"']+)(["'])/g,
          (match, before: string, specifier: string, after: string) =>
            /\.(?:js|json)$/.test(specifier)
              ? match
              : `${before}${specifier}.js${after}`,
        ),
      )
    }
  }
}
await fixDeclarations("dist")
for (const [entry, filename] of [
  ["lib/index.ts", "index.js"],
  ["lib/palace.ts", "palace.js"],
  ["cli/index.ts", "cli.js"],
]) {
  const built = await Bun.build({
    entrypoints: [entry],
    outdir: "dist",
    naming: filename,
    target: "node",
    format: "esm",
    packages: "external",
  })
  if (!built.success) throw new Error(`Build failed: ${built.logs.join("\n")}`)
}
await mkdir("dist/python", { recursive: true })
for (const filename of await readdir("lib/palace/python"))
  if (filename.endsWith(".py") || filename.endsWith(".txt"))
    await copyFile(
      join("lib/palace/python", filename),
      join("dist/python", filename),
    )
await chmod("dist/cli.js", 0o755)
