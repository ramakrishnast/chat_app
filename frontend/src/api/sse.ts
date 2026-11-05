/** Parse a text/event-stream body. Yields the JSON `data` of each event. */
export async function* parseSse<T>(stream: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function* drain(final: boolean): Generator<T> {
    buffer = buffer.replace(/\r\n/g, "\n");
    let end = buffer.indexOf("\n\n");
    while (end >= 0 || (final && buffer.trim())) {
      const block = end >= 0 ? buffer.slice(0, end) : buffer;
      buffer = end >= 0 ? buffer.slice(end + 2) : "";
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data) yield JSON.parse(data) as T;
      end = buffer.indexOf("\n\n");
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      yield* drain(false);
    }
    buffer += decoder.decode();
    yield* drain(true);
  } finally {
    reader.releaseLock();
  }
}
