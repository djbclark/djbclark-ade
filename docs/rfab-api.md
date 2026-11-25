# Reality Fabricator API reference

Model IDs and pricing were checked on 2026-11-25.

Use Reality Fabricator only when the operator explicitly requests it for the
task. Send only art prompts and approved public art references to the media
API or MCP tools. Keep code, files, and private data out of those requests.

The base URL is `https://api.rfab.ai`. Resolve `RFAB_API_KEY` at invocation with
`sudo-secretspec get RFAB_API_KEY --reason rfab-media-request` captured in memory,
or use `sudo-secretspec run --reason rfab-media-request -- <program>` and read the
key from the program's environment. Send `X-API-Key` for media and balance REST
requests and `Authorization: Bearer` for OpenAI-compatible chat at `/api/v1`
and Streamable HTTP MCP at `/api/mcp`. Keep the credential out of argv, logs,
client settings and `.env` files. See the [full reference](https://rfab.ai/llms-full.txt)
and [OpenAPI document](https://api.rfab.ai/api/openapi.json).

## Pictures and game art

1. Send `POST /api/image-generation/generate` with
   `{ prompt, modelId: "openai:gpt-image-2", width, height, async: true }`.
   Save its `jobId` and poll `GET /api/image-generation/job/:jobId` for the
   permanent image URL. Use `GET /api/image-generation/models` to find ranked
   options and check current model availability. The full reference lists
   `seegen:gpt-image-2` as the current catalog ID for the same model. The
   default quality tier generally looks the same at normal display size.
2. For sprites, use `style: "pixel-art"` or `"game-assets"`. Repeat the same
   character paragraph at the start of every prompt for a consistent set.
   Use `alphaRegion` for the see-through window of a HUD frame. Use
   `POST /api/image-generation/isolate-figure` for a transparent cut-out.
3. For page headers and buttons, draw larger than the slot (for example
   1536 × 1024) and crop. Overlay headings and button labels in HTML because
   image models can misspell text.

## Video and loading animations

1. Send `POST /api/image-generation/generate-video` with
   `{ imageUrl, prompt, videoModelId: "atlascloud:seedance-2.5-i2v", duration }`.
   Poll `GET /api/image-generation/job/:jobId` for `result.videoUrl`. Check the
   model's supported durations and tier requirements in the full reference.
   Describe what moves. The phrase `camera locked` asks for a still camera.
2. To work from clips and sounds without a picture, use `videoUrls` and
   `audioUrls` as described in **Video From Reference Clips and Sounds** in
   the full reference.
3. For a loading loop, follow **Transparent Looping Animation** in the full
   reference. Draw the character on green, animate it, then use the FFmpeg
   chroma key filter and export a transparent WebM loop.

Check `GET /api/tokens/balance` before authorized spending. USD 1 buys 50,000
tokens, and a picture at default quality can cost a few cents.

## Pi and MCP

The manual [Pi provider](pi-services.md#veniceai-and-reality-fabricator-manual-access-2026-11-25)
lives in `pi-extensions/rfab/`. For media tools, attach the
[on-demand MCP bridge](mcp-servers.md#reality-fabricator-on-demand-added-2026-11-25) with
`ade-mcp-rfab` to the authorized task session.
