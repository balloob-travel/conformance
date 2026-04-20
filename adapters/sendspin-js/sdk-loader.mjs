// Node ESM resolver hook that adds ".js" or "/index.js" to extensionless
// relative specifiers. The published sendspin-js dist/ output is emitted
// by TypeScript with `moduleResolution: bundler`, so its internal imports
// (e.g. `./core/core`) rely on a bundler to append extensions. This hook
// lets Node consume the built SDK directly without re-bundling.
import { existsSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";

const KNOWN_EXTENSIONS = new Set([".js", ".mjs", ".cjs", ".json", ".node", ".wasm"]);

function hasKnownExtension(specifier) {
  const match = /\.[a-zA-Z0-9]+$/.exec(specifier);
  return match !== null && KNOWN_EXTENSIONS.has(match[0]);
}

export function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith(".") && !hasKnownExtension(specifier)) {
    const { parentURL } = context;
    if (parentURL) {
      try {
        const filePath = fileURLToPath(new URL(specifier, parentURL));
        if (existsSync(`${filePath}.js`)) {
          return nextResolve(`${specifier}.js`, context);
        }
        if (
          existsSync(filePath) &&
          statSync(filePath).isDirectory() &&
          existsSync(`${filePath}/index.js`)
        ) {
          return nextResolve(`${specifier}/index.js`, context);
        }
      } catch {
        // Fall through to default resolution.
      }
    }
  }
  return nextResolve(specifier, context);
}
