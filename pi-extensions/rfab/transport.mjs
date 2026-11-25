// RFab accepts one buffered OpenAI completion. Present it to Pi's existing
// adapter as SSE so Pi retains tool-call, transcript, reasoning and usage handling.
export function bufferedCompletionsFetch(fetch) {
  return async (input, init) => {
    const request = new Request(input, init);
    const payload = await request.json();
    delete payload.stream_options;
    payload.stream = false;
    const headers = new Headers(request.headers);
    headers.delete("content-length");
    headers.set("accept", "application/json");
    const response = await fetch(new Request(request, {
      headers,
      body: JSON.stringify(payload),
      redirect: "error",
    }));
    // Use fixed failure bodies: upstream may echo credentials or request data.
    if (!response.ok) {
      await response.body?.cancel();
      return new Response(JSON.stringify({ error: { message: `RFab HTTP ${response.status}` } }), {
        status: response.status,
        headers: { "content-type": "application/json" },
      });
    }
    let completion;
    try {
      completion = await response.json();
    } catch {
      throw new Error("RFab returned an invalid chat completion");
    }
    const { id, created, model, usage, choices } = completion ?? {};
    const choice = choices?.[0];
    if (!choice?.message || typeof choice.finish_reason !== "string") {
      throw new Error("RFab returned an invalid chat completion");
    }
    const delta = { ...choice.message };
    if (delta.tool_calls) {
      delta.tool_calls = delta.tool_calls.map((call, index) => ({ ...call, index }));
    }
    const chunk = {
      id, created, model, usage, object: "chat.completion.chunk",
      choices: [{ index: 0, delta, finish_reason: choice.finish_reason }],
    };
    const credential = headers.get("authorization")?.match(/^Bearer (.+)$/i)?.[1];
    const encoded = JSON.stringify(chunk);
    const sseData = credential
      ? encoded.replaceAll(JSON.stringify(credential).slice(1, -1), "[redacted]")
      : encoded;
    return new Response(`data: ${sseData}\n\ndata: [DONE]\n\n`, {
      headers: { "content-type": "text/event-stream" },
    });
  };
}
