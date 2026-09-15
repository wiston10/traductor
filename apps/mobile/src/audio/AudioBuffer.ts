export class AudioBuffer<T> {
  private readonly items: T[] = [];

  constructor(private readonly maxSize = 128) {}

  push(item: T) {
    if (this.items.length >= this.maxSize) {
      this.items.shift();
    }

    this.items.push(item);
    return item;
  }

  take(): T | undefined {
    return this.items.shift();
  }

  peek(): T | undefined {
    return this.items[0];
  }

  clear() {
    this.items.length = 0;
  }

  get size() {
    return this.items.length;
  }

  values() {
    return [...this.items];
  }
}
