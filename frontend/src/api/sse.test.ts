import { parseSse } from "./sse";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const out: unknown[] = [];
  for await (const event of parseSse(stream)) out.push(event);
  return out;
}

test("parses events split across chunks, CRLF, and a final event without a blank line", async () => {
  const events = await collect(
    streamOf(
      'event: text\ndata: {"type":"te',
      'xt","delta":"a"}\n\n',
      'event: done\r\ndata: {"type":"done"}\r\n\r\n: comment\n\n',
      'data: {"type":"last"}',
    ),
  );
  expect(events).toEqual([{ type: "text", delta: "a" }, { type: "done" }, { type: "last" }]);
});

test("joins multi-line data fields", async () => {
  const events = await collect(streamOf('data: {"a":\ndata: 1}\n\n'));
  expect(events).toEqual([{ a: 1 }]);
});
