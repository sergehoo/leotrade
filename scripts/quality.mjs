import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

const candidates = [
  process.env.LEOTRADE_PYTHON,
  "python3",
  ".venv/bin/python",
  "venv/bin/python",
].filter(Boolean);
const python = candidates.find((candidate) =>
  candidate.includes("/") ? existsSync(candidate) : true,
);

if (!python) {
  console.error("Python introuvable. Définissez LEOTRADE_PYTHON.");
  process.exit(2);
}

const environment = {
  ...process.env,
  FERNET_SECRET_KEY:
    process.env.FERNET_SECRET_KEY ??
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
};

function run(args) {
  const result = spawnSync(python, args, {
    cwd: process.cwd(),
    env: environment,
    stdio: "inherit",
  });
  if (result.error) {
    console.error(result.error.message);
    process.exit(2);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

const gate = process.argv[2];
if (gate === "check") {
  run(["-m", "compileall", "-q", "leoTrade", "api", "brokers", "portfolio", "trading", "wallet", "ai_assistant"]);
  run(["manage.py", "check", "--settings=leoTrade.settings.test"]);
  run(["manage.py", "makemigrations", "--check", "--dry-run", "--settings=leoTrade.settings.test"]);
} else if (gate === "test") {
  run(["-m", "pytest", "tests_phase", "-q"]);
} else {
  console.error("Usage: node scripts/quality.mjs <check|test>");
  process.exit(2);
}
