/**
 * 测试不能连真实后端：没有 mock 的 fetch 一律失败。
 * 否则开着 dev server 跑测试时，会读写真实数据（比如 Compare 的自动保存）。
 */
globalThis.fetch = (async (input: RequestInfo | URL) => {
  throw new TypeError(`测试里有没 mock 的网络请求：${String(input)}`);
}) as typeof fetch;
