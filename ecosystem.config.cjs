const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const root = __dirname;
const envFile = path.join(root, ".env");

function parseDotEnv(filePath) {
  if (!fs.existsSync(filePath)) {
    return {};
  }

  return fs
    .readFileSync(filePath, "utf8")
    .split(/\r?\n/)
    .reduce((env, rawLine) => {
      const line = rawLine.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) {
        return env;
      }

      const separator = line.indexOf("=");
      const key = line.slice(0, separator).trim();
      let value = line.slice(separator + 1).trim();

      if (!key) {
        return env;
      }

      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }

      env[key] = value;
      return env;
    }, {});
}

function pythonVersion(command) {
  try {
    const output = execFileSync(
      command,
      ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
    ).trim();
    const [major, minor] = output.split(".").map(Number);

    if (Number.isInteger(major) && Number.isInteger(minor)) {
      return { major, minor };
    }
  } catch {
    return null;
  }

  return null;
}

function isAtLeast(version, minimum) {
  if (!minimum) {
    return true;
  }

  const [major, minor] = minimum;
  return version.major > major || (version.major === major && version.minor >= minor);
}

function findPython(minimum = null) {
  const venvPython =
    process.platform === "win32"
      ? path.join(root, ".venv", "Scripts", "python.exe")
      : path.join(root, ".venv", "bin", "python");
  const candidates = [
    process.env.PYTHON,
    venvPython,
    "python3.13",
    "python3.12",
    "python3.11",
    "python3",
    "python",
  ].filter(Boolean);

  for (const candidate of candidates) {
    const version = pythonVersion(candidate);
    if (version && isAtLeast(version, minimum)) {
      return candidate;
    }
  }

  return null;
}

const dotEnv = parseDotEnv(envFile);
const python = findPython([3, 11]);
const serverPython = python || findPython() || "python3";
const dashboardHost =
  process.env.QQ_VALHALLA_DASHBOARD_HOST || dotEnv.QQ_VALHALLA_DASHBOARD_HOST || "127.0.0.1";
const dashboardPort =
  process.env.QQ_VALHALLA_DASHBOARD_PORT || dotEnv.QQ_VALHALLA_DASHBOARD_PORT || "8958";
const missingPythonMessage =
  "QiE Valhalla requires Python 3.11+. Set PYTHON=/path/to/python3.11 or recreate .venv with Python 3.11+.";

const common = {
  cwd: root,
  interpreter: "none",
  exec_mode: "fork",
  instances: 1,
  time: true,
  env: {
    PYTHONUNBUFFERED: "1",
  },
};

module.exports = {
  apps: [
    {
      ...common,
      name: "qie-valhalla-watch",
      script: python || process.execPath,
      args: python
        ? ["-m", "qq_valhalla", "--env", envFile, "watch"]
        : ["-e", `console.error(${JSON.stringify(missingPythonMessage)}); process.exit(1);`],
      autorestart: Boolean(python),
      exp_backoff_restart_delay: 10000,
      max_memory_restart: "256M",
    },
    {
      ...common,
      name: "qie-valhalla-dashboard",
      script: serverPython,
      args: [
        "-m",
        "http.server",
        dashboardPort,
        "--bind",
        dashboardHost,
        "--directory",
        path.join(root, "archive", "dashboard"),
      ],
      autorestart: true,
      exp_backoff_restart_delay: 3000,
      max_memory_restart: "128M",
    },
  ],
};