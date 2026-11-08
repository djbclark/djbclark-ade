/** Fit the SIPB 32k context without dropping project instructions or tools. */
export default function serviceContext(pi) {
  pi.on("before_agent_start", (event, ctx) => {
    if (ctx.model?.provider !== "sipb") return;
    event.systemPromptOptions.skills = [];
  });
}
