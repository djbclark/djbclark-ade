// No Pi CLI or provider is run: getPiInvocation launches THIS file as the child.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

if (process.argv.includes("--mode")) {
	const args = process.argv.slice(2);
	const record = { args, cwd: process.cwd() };
	const promptIndex = args.indexOf("--append-system-prompt");
	if (promptIndex !== -1) {
		record.prompt = fs.readFileSync(args[promptIndex + 1], "utf8");
		record.promptPath = args[promptIndex + 1];
	}
	fs.appendFileSync(process.env.SUBAGENT_TEST_LOG, `${JSON.stringify(record)}\n`);
	if (args.includes("unavailable/model")) {
		process.stderr.write("Model unavailable/model not found");
		process.exit(1);
	}
	if (args.at(-1).includes("WAIT_FOR_ABORT")) {
		setInterval(() => {}, 1000);
	} else {
		// Small delay permits overlapping real subprocesses in parallel-mode tests.
		await new Promise((resolve) => setTimeout(resolve, 15));
		console.log(JSON.stringify({ type: "message_end", message: {
			role: "assistant", model: "child-reported-model", content: [{ type: "text", text: "child output" }],
			stopReason: args.at(-1).includes("LLM_ERROR") ? "error" : "stop",
			errorMessage: args.at(-1).includes("LLM_ERROR") ? "provider failure" : undefined,
			usage: { input: 3, output: 2, totalTokens: 5, cost: { total: 0 } },
		} }));
	}
} else {
	globalThis.fetch = () => { throw new Error("Network forbidden in subagent tests"); };
	const { Check } = await import("typebox/value");
	const { default: register } = await import("./index.ts");
	const { discoverAgents } = await import("./agents.ts");
	const { THINKING_LEVELS } = await import("./config.ts");
	let tool;
	register({ registerTool(definition) { tool = definition; } });
	assert.equal(tool.name, "subagent");
	const root = process.env.SUBAGENT_TEST_ROOT;
	const userDir = path.join(process.env.PI_CODING_AGENT_DIR, "agents");
	const projectDir = path.join(root, "project", ".pi", "agents");
	const childCwd = path.join(root, "child");
	fs.mkdirSync(userDir, { recursive: true });
	fs.mkdirSync(projectDir, { recursive: true });
	fs.mkdirSync(childCwd, { recursive: true });
	const define = (name, extra = "", dir = userDir) => fs.writeFileSync(path.join(dir, `${name}.md`),
		`---\nname: ${name}\ndescription: Test agent\n${extra}\n---\nTest system prompt.\n`);
	define("plain");
	define("configured", "model: anthropic/claude-sonnet-5\nthinking: high\ntools: [read, bash]");
	define("model-only", "model: openrouter/vendor/model:high");
	define("thinking-only", "thinking: low");
	define("project", "model: local/project", projectDir);
	define("plain", "model: local/shadow", projectDir);
	const ctx = { cwd: path.join(root, "project"), hasUI: false,
		// Prove these are NOT inherited: the brief requires child Pi defaults.
		model: { provider: "parent", id: "must-not-inherit" }, thinkingLevel: "max" };
	const records = () => fs.existsSync(process.env.SUBAGENT_TEST_LOG)
		? fs.readFileSync(process.env.SUBAGENT_TEST_LOG, "utf8").trim().split("\n").filter(Boolean).map(JSON.parse) : [];
	const clear = () => fs.writeFileSync(process.env.SUBAGENT_TEST_LOG, "");
	const execute = (params, updates = [], context = ctx, signal) =>
		tool.execute("test", params, signal, (update) => updates.push(structuredClone(update)), context);
	const wrap = (mode, item) => mode === "single" ? item : { [mode === "parallel" ? "tasks" : "chain"]: [item] };
	const option = (args, name) => args.includes(name) ? args[args.indexOf(name) + 1] : undefined;
	let cases = 0;
	const verify = async (mode, item, expected) => {
		clear();
		const params = wrap(mode, { task: "test", ...item });
		assert.equal(Check(tool.parameters, params), true, JSON.stringify(params));
		const updates = [];
		const result = await execute(params, updates);
		assert.ok(!result.isError, JSON.stringify(result));
		assert.equal(result.details.mode, mode);
		assert.ok(result.content[0].text.includes(`model=${expected.model ?? "default"}, thinking=${expected.thinking ?? "default"}`), result.content[0].text);
		assert.deepEqual(result.details.results[0].selectedConfig, expected);
		assert.equal(records().length, 1);
		const record = records()[0];
		assert.equal(option(record.args, "--model"), expected.model);
		assert.equal(option(record.args, "--thinking"), expected.thinking);
		assert.ok(record.args.includes("--no-session"));
		assert.ok(record.prompt.includes("Test system prompt."));
		assert.equal(fs.existsSync(record.promptPath), false, "temporary prompt cleaned up");
		assert.equal(fs.realpathSync(record.cwd), fs.realpathSync(item.cwd ?? ctx.cwd));
		assert.ok(updates.length > 0);
		for (const update of updates) assert.deepEqual(update.details.results[0].selectedConfig, expected);
		cases++;
	};
	for (const mode of ["single", "parallel", "chain"]) {
		await verify(mode, { agent: "plain" }, { model: undefined, thinking: undefined });
		await verify(mode, { agent: "configured" }, { model: "anthropic/claude-sonnet-5", thinking: "high" });
		await verify(mode, { agent: "model-only" }, { model: "openrouter/vendor/model:high", thinking: undefined });
		await verify(mode, { agent: "thinking-only" }, { model: undefined, thinking: "low" });
		await verify(mode, { agent: "configured", model: "openai/gpt-6-astra", cwd: childCwd },
			{ model: "openai/gpt-6-astra", thinking: "high" });
		await verify(mode, { agent: "configured", thinking: "off" }, { model: "anthropic/claude-sonnet-5", thinking: "off" });
		for (const thinking of THINKING_LEVELS) {
			await verify(mode, { agent: "configured", model: "namespace/provider/vendor/model:high", thinking },
				{ model: "namespace/provider/vendor/model:high", thinking });
		}
		// The explicit frontmatter thinking also beats an invocation model suffix (Pi CLI semantics).
		await verify(mode, { agent: "configured", model: "ollama/qwen:7b:low" },
			{ model: "ollama/qwen:7b:low", thinking: "high" });
		for (const invalid of [{ model: "" }, { model: " \n " }, { model: 123 }, { model: null },
			{ thinking: "turbo" }, { thinking: "HIGH" }, { thinking: "" }, { thinking: false }, { thinking: null }]) {
			clear();
			const params = wrap(mode, { agent: "configured", task: "test", ...invalid });
			assert.equal(Check(tool.parameters, params), false);
			// Simulate a post-schema tool_call mutation: execute must fail closed as well.
			const result = await execute(params);
			assert.equal(result.details.results[0].exitCode, 1);
			assert.ok(result.details.results[0].selectedConfig);
			assert.equal(records().length, 0);
			cases++;
		}
		for (const item of [{ agent: "missing", model: "custom/missing", thinking: "max" },
			{ agent: "plain", model: "unavailable/model", thinking: "minimal" },
			{ agent: "plain", model: "openai/test", thinking: "low", task: "LLM_ERROR" }]) {
			const result = await execute(wrap(mode, { task: "test", ...item }));
			assert.deepEqual(result.details.results[0].selectedConfig, { model: item.model, thinking: item.thinking });
			assert.ok(result.content[0].text.includes("failed") || result.isError);
			cases++;
		}
	}
	for (const [i, extra] of ["model: 42", "model: ''", "model: [bad]", "thinking: turbo", "thinking: true", "thinking: null"].entries()) {
		define(`invalid-${i}`, extra);
		clear();
		const result = await execute({ agent: `invalid-${i}`, task: "test" });
		assert.equal(result.isError, true);
		assert.equal(records().length, 0);
		cases++;
	}
	// Bad frontmatter is moot for a field the invocation overrides (invocation > frontmatter), fatal otherwise.
	for (const mode of ["single", "parallel", "chain"]) {
		await verify(mode, { agent: "invalid-3", thinking: "low" }, { model: undefined, thinking: "low" });
		await verify(mode, { agent: "invalid-1", model: "openai/gpt-6-astra" }, { model: "openai/gpt-6-astra", thinking: undefined });
		await verify(mode, { agent: "invalid-0", model: "local/ok" }, { model: "local/ok", thinking: undefined });
		for (const item of [{ agent: "invalid-3", model: "local/ok" }, { agent: "invalid-1", thinking: "low" }]) {
			clear();
			const result = await execute(wrap(mode, { task: "test", ...item }));
			assert.ok(result.isError || result.details.results[0].exitCode === 1);
			assert.match(result.content[0].text, /must be/);
			assert.equal(records().length, 0);
			cases++;
		}
	}
	// Chain pre-pass: a bad later step fails the chain before any earlier step runs.
	for (const bad of [{ agent: "invalid-3", task: "b" }, { agent: "missing", task: "b" }, { agent: "plain", task: "b", thinking: "turbo" }]) {
		clear();
		const result = await execute({ chain: [{ agent: "plain", task: "a" }, bad] });
		assert.equal(result.isError, true);
		assert.match(result.content[0].text, /Chain not started: step 2/);
		assert.equal(records().length, 0);
		cases++;
	}
	// Actual schema rejects missing nested required fields. Mode validation handles empty/mixed calls.
	for (const params of [{ tasks: [{ task: "test" }] }, { chain: [{ agent: "plain" }] }]) {
		assert.equal(Check(tool.parameters, params), false); cases++;
	}
	for (const params of [{}, { agent: "plain" }, { tasks: [] }, { agent: "plain", task: "test", chain: [{ agent: "plain", task: "test" }] },
		{ tasks: [{ agent: "plain", task: "test" }], model: "ignored/model" },
		{ chain: [{ agent: "plain", task: "test" }], thinking: "high" }]) {
		clear(); await execute(params); assert.equal(records().length, 0); cases++;
	}
	clear();
	const steps = [{ agent: "plain", task: "first", model: "openai/first", thinking: "off" },
		{ agent: "configured", task: "next {previous}", model: "anthropic/second", thinking: "max" }];
	const chain = await execute({ chain: steps });
	assert.equal(chain.details.results.length, 2);
	assert.equal(records()[1].args.at(-1), "Task: next child output");
	assert.equal(option(records()[1].args, "--model"), "anthropic/second");
	clear();
	const stopped = await execute({ chain: [{ ...steps[0], model: "unavailable/model" }, steps[1]] });
	assert.equal(stopped.isError, true); assert.equal(records().length, 1);
	clear();
	const parallel = await execute({ tasks: steps });
	assert.deepEqual(parallel.details.results.map((r) => r.selectedConfig), steps.map(({ model, thinking }) => ({ model, thinking })));
	assert.equal(records().length, 2);
	assert.ok(records().some((r) => option(r.args, "--tools") === "read,bash"));
	clear(); await execute({ tasks: Array(9).fill(steps[0]) }); assert.equal(records().length, 0);
	assert.equal(discoverAgents(ctx.cwd, "user").agents.find((a) => a.name === "plain").source, "user");
	assert.equal(discoverAgents(ctx.cwd, "both").agents.find((a) => a.name === "plain").model, "local/shadow");
	clear();
	let confirmations = 0;
	await execute({ agent: "project", task: "test", agentScope: "project" }, [],
		{ ...ctx, hasUI: true, ui: { confirm: async () => { confirmations++; return false; } } });
	assert.equal(confirmations, 1); assert.equal(records().length, 0);
	// A pre-aborted call keeps the original rejection behavior and carries config in its last update.
	const controller = new AbortController(); controller.abort();
	const updates = [];
	await assert.rejects(execute({ agent: "plain", task: "WAIT_FOR_ABORT", model: "local/test", thinking: "off" }, updates, ctx, controller.signal), /aborted/);
	assert.deepEqual(updates.at(-1).details.results[0].selectedConfig, { model: "local/test", thinking: "off" });
	console.log(`PASS: ${cases} configuration/schema cases plus mixed modes, consent, chain stop, cleanup and abort`);
}
