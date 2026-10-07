import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const output = resolve(root, "dist");
const apiBaseUrl = (process.env.VITE_API_BASE_URL || "").trim().replace(/\/$/, "");

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

for (const file of ["index.html", "admin.html", "styles.css", "app.js", "admin.js"]) {
  try {
    await cp(resolve(root, file), resolve(output, file));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}

await writeFile(
  resolve(output, "runtime-config.js"),
  `window.CINEVERSE_CONFIG = { API_BASE_URL: ${JSON.stringify(apiBaseUrl)} };\n`,
  "utf8"
);

console.log(`Built CineVerse frontend in dist/ (API: ${apiBaseUrl || "same origin"})`);