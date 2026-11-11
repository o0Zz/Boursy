import { execSync } from "node:child_process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Same rule as CI and the Dockerfile: branch release/X.Y.Z gives X.Y.Z+<commit count>, tag vX.Y.Z
// gives X.Y.Z, any other branch gives 0.0.0-<branch>+<commit count>. Null outside a git checkout.
function gitVersion(): string | null {
  try {
    const git = (args: string) => execSync(`git ${args}`, { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
    const count = git("rev-list --count HEAD");
    const branch = git("rev-parse --abbrev-ref HEAD");
    const release = /^release\/(\d+)\.(\d+)(?:\.(\d+))?/.exec(branch);
    return release
      ? `${release[1]}.${release[2]}.${release[3] ?? 0}+${count}`
      : `0.0.0-${branch.replace(/[^0-9A-Za-z-]/g, "-")}+${count}`;
  } catch {
    return null;
  }
}

export default defineConfig({
  build: { chunkSizeWarningLimit: 900 },
  plugins: [react(), tailwindcss()],
  define: {
    // APP_VERSION is passed in by the Docker build, where there is no git binary.
    __APP_VERSION__: JSON.stringify(process.env.APP_VERSION || gitVersion() || "0.0.0-dev"),
  },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
