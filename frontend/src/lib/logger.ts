/**
 * Structured logger — silences debug/info in production.
 */

type LogFn = (...args: unknown[]) => void;

export interface Logger {
  debug: LogFn;
  info: LogFn;
  warn: LogFn;
  error: LogFn;
}

// Vite 环境：用 import.meta.env.PROD 判断（替换原 agent-town 的 process.env）。
const isProd = import.meta.env.PROD;

function noop() {}

export function createLogger(tag: string): Logger {
  const prefix = `[${tag}]`;
  if (isProd) {
    return {
      debug: noop,
      info: noop,
      warn: console.warn.bind(console, prefix),
      error: console.error.bind(console, prefix),
    };
  }
  return {
    debug: console.debug.bind(console, prefix),
    info: console.info.bind(console, prefix),
    warn: console.warn.bind(console, prefix),
    error: console.error.bind(console, prefix),
  };
}
