import { execFileSync, execSync } from 'node:child_process';
import { rmSync } from 'node:fs';

const port = Number(process.argv[2] || 5175);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  console.error(`Invalid port: ${process.argv[2]}`);
  process.exit(2);
}

function windowsOwners(targetPort) {
  const out = execSync(`netstat -ano -p tcp`, { encoding: 'utf8', windowsHide: true });
  const pids = new Set();
  for (const line of out.split(/\r?\n/)) {
    const m = line.trim().match(/^TCP\s+\S+:${targetPort}\s+\S+\s+LISTENING\s+(\d+)$/i);
    if (m) pids.add(m[1]);
  }
  return [...pids];
}

if (process.platform !== 'win32') {
  console.log(`Port cleanup is only needed on Windows for this project. Skipping ${port}.`);
  process.exit(0);
}

function clearViteCache() {
  try {
    rmSync(new URL('./node_modules/.vite/', import.meta.url), { recursive: true, force: true });
    console.log('Cleared stale Vite transform cache.');
  } catch (err) {
    console.warn(`Could not clear Vite cache: ${err.message}`);
  }
}

let pids;
try {
  pids = windowsOwners(port);
} catch (err) {
  console.error(`Unable to inspect port ${port}: ${err.message}`);
  process.exit(1);
}

if (!pids.length) {
  clearViteCache();
  console.log(`Port ${port} is free.`);
  process.exit(0);
}

for (const pid of pids) {
  let commandLine = '';
  try {
    commandLine = execFileSync(
      'powershell.exe',
      ['-NoProfile', '-Command', `(Get-CimInstance Win32_Process -Filter \"ProcessId=${pid}\").CommandLine`],
      { encoding: 'utf8', windowsHide: true }
    ).trim();
  } catch {
    commandLine = '';
  }

  const looksLikeVite = /(^|[\\/\s])(vite|vite\.cmd)(?:[\\/\s]|$)/i.test(commandLine) ||
    /node(?:\.exe)?[^\r\n]*(vite|npm-cli|npm\.cmd)/i.test(commandLine);

  if (!looksLikeVite) {
    console.error(`Port ${port} is already used by PID ${pid}.`);
    if (commandLine) console.error(`Process: ${commandLine}`);
    console.error('The project will not kill an unrelated process automatically.');
    console.error(`Stop that process or run the project on another port.`);
    process.exit(1);
  }

  try {
    execFileSync('taskkill.exe', ['/PID', pid, '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    console.log(`Stopped stale Vite process PID ${pid} on port ${port}.`);
  } catch (err) {
    console.error(`Could not stop stale Vite process PID ${pid}: ${err.message}`);
    process.exit(1);
  }
}

// Give Windows a short moment to release the socket.
await new Promise((resolve) => setTimeout(resolve, 250));
clearViteCache();
console.log(`Port ${port} is ready.`);
