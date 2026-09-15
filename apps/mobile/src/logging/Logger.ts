export type LogLevel = "info" | "warn" | "error";

export class Logger {
  static create(scope: string, enabled = true) {
    return new Logger(scope, enabled);
  }

  constructor(
    private readonly scope: string,
    private readonly enabled: boolean
  ) {}

  log(level: LogLevel, message: string, context?: Record<string, unknown>) {
    if (!this.enabled) {
      return;
    }

    const prefix = `[${this.scope}] [${level.toUpperCase()}]`;
    if (context) {
      console.log(prefix, message, context);
      return;
    }

    console.log(prefix, message);
  }
}
