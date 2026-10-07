import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

const python = process.env.PYTHON || (process.platform === "win32" ? "py" : "python3");
const install = spawnSync(python, ["-m", "pip", "install", "-r", "requirements.txt"], { stdio: "inherit" });
if (install.error || install.status !== 0) {
  console.error("Could not install Python requirements. Set PYTHON to your Python executable and retry.");
  process.exit(install.status || 1);
}
if (!existsSync("server.py")) {
  console.error("Run npm run dev from the project root.");
  process.exit(1);
}
const server = spawn(python, ["server.py"], { stdio: "inherit" });
server.on("exit", (code) => process.exit(code ?? 0));
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.kill(signal));
}
