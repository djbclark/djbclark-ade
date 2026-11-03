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
	if (args.at(-1).includes("SELF_KILL")) {
		process.kill(process.pid, "SIGKILL");
		await new Promise(() => {});
	}
	if (args.at(-1).includes("WAIT_FOR_ABORT")) {
		setInterval(() => {}, 1000);
	} else {
		// Small delay permits overlapping real subprocesses in parallel-mode tests.
		await new Promise((resolve) => setTimeout(resolve, 15));
		if (args.at(-1).includes("SPLIT_UTF8")) {
			// "é" (2 bytes), "€" (3 bytes) and an emoji (4 bytes), each cut in half across writes.
			const line = Buffer.from(`${JSON.stringify({ type: "message_end", message: {
				role: "assistant", content: [{ type: "text", text: "caf\u00e9 \u20ac \u{1F600}" }], stopReason: "stop" } })}\n`);
			const cuts = [line.indexOf(Buffer.from("\u00e9")) + 1, line.indexOf(Buffer.from("\u20ac")) + 1,
				line.indexOf(Buffer.from("\u{1F600}")) + 2];
			let from = 0;
			for (const cut of cuts) {
				process.stdout.write(line.subarray(from, cut));
				await new Promise((resolve) => setTimeout(resolve, 30));
				from = cut;
			}
			process.stdout.write(line.subarray(from));
			process.stderr.write(Buffer.from("err \u00e9").subarray(0, 5));
			await new Promise((resolve) => setTimeout(resolve, 30));
			process.stderr.write(Buffer.from("err \u00e9").subarray(5));
			process.exit(0);
		}
		if (args.at(-1).includes("MULTI_TEXT")) {
			console.log(JSON.stringify({ type: "message_end", message: {
				role: "assistant", content: [{ type: "text", text: "first part" }, { type: "thinking", thinking: "x" },
					{ type: "text", text: "second part" }], stopReason: "stop" } }));
			process.exit(0);
		}
		console.log(JSON.stringify({ type: "message_end", message: {
			role: "assistant", model: "child-reported-model",
			content: [{ type: "text", text: args.at(-1).includes("DOLLAR_OUT") ? "cost $& $1 $$ $` $'" : "child output" }],
			stopReason: args.at(-1).includes("LLM_ERROR") ? "error" : "stop",
			errorMessage: args.at(-1).includes("LLM_ERROR") ? "provider failure" : undefined,
			usage: { input: 3, output: 2, totalTokens: 5, cost: { total: 0 } },
		} }));
	}
} else {
	globalThis.fetch = () => { throw new Error("Network forbidden in subagent tests"); };
	const { Check } = await import("typebox/value");
	const { default: register, terminateChild } = await import("./index.ts");
	const { EventEmitter } = await import("node:events");
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
	define("project", "model: local/project\nthinking: low\ntools: [read]", projectDir);
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
	// Regression: a signal-killed child (exit code null) is a failure.
	clear();
	const killed = await execute({ agent: "plain", task: "SELF_KILL" });
	assert.equal(killed.isError, true);
	assert.notEqual(killed.details.results[0].exitCode, 0);
	assert.match(killed.content[0].text, /signal SIGKILL/); cases++;
	// Regression: {previous} substitution is literal ($&, $1, $$, $`, $' are not interpreted).
	clear();
	const literal = await execute({ chain: [{ agent: "plain", task: "DOLLAR_OUT" }, { agent: "plain", task: "next {previous}" }] });
	assert.ok(!literal.isError);
	assert.equal(records()[1].args.at(-1), "Task: next cost $& $1 $$ $` $'"); cases++;
	// Regression: SIGKILL escalation checks the real exit and is cancelled on exit/close.
	const fakeChild = (exitCode = null, signalCode = null) => {
		const p = new EventEmitter(); p.exitCode = exitCode; p.signalCode = signalCode; p.sent = [];
		p.kill = (s) => { p.sent.push(s); return true; }; return p;
	};
	const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
	const stuck = fakeChild(); terminateChild(stuck, 20); await sleep(60);
	assert.deepEqual(stuck.sent, ["SIGTERM", "SIGKILL"]);
	const exiting = fakeChild(); terminateChild(exiting, 20); exiting.exitCode = 0; exiting.emit("exit", 0, null);
	await sleep(60); assert.deepEqual(exiting.sent, ["SIGTERM"]);
	const diedSilently = fakeChild(); terminateChild(diedSilently, 20); diedSilently.signalCode = "SIGTERM"; await sleep(60);
	assert.deepEqual(diedSilently.sent, ["SIGTERM"]);
	const already = fakeChild(0); terminateChild(already, 20); await sleep(60); assert.deepEqual(already.sent, []); cases += 4;
	// Regression: one profile with invalid YAML is skipped and reported; the others still load.
	fs.writeFileSync(path.join(userDir, "broken.md"), "---\nname: broken\ndescription: [unterminated\n  : : :\n---\nBody\n");
	const found = discoverAgents(ctx.cwd, "user");
	assert.ok(found.agents.some((a) => a.name === "plain"));
	assert.ok(!found.agents.some((a) => a.name === "broken"));
	assert.equal(found.profileErrors.length, 1); assert.match(found.profileErrors[0], /broken\.md/); cases++;
	fs.rmSync(path.join(userDir, "broken.md"));
	clear();
	let confirmations = 0;
	await execute({ agent: "project", task: "test", agentScope: "project" }, [],
		{ ...ctx, hasUI: true, ui: { confirm: async () => { confirmations++; return false; } } });
	assert.equal(confirmations, 1); assert.equal(records().length, 0);
	// Consent: the model-supplied confirmProjectAgents flag cannot relax it.
	let dialog;
	const approving = { ...ctx, hasUI: true, ui: { confirm: async (title, body) => { dialog = { title, body }; return true; } } };
	clear();
	const approved = await execute({ agent: "project", task: "test", agentScope: "both", confirmProjectAgents: false, thinking: "high" }, [], approving);
	assert.ok(dialog, "prompt shown despite confirmProjectAgents:false"); assert.ok(!approved.isError);
	assert.match(dialog.body, /project: tools=read, model=local\/project, thinking=high/);
	assert.equal(records().length, 1); cases++;
	// Headless: refused without the operator env override, allowed with exactly "1".
	for (const [value, allowed] of [[undefined, false], ["", false], ["0", false], ["true", false], ["1", true]]) {
		if (value === undefined) delete process.env.PI_SUBAGENT_ALLOW_PROJECT_AGENTS; else process.env.PI_SUBAGENT_ALLOW_PROJECT_AGENTS = value;
		for (const mode of ["single", "parallel", "chain"]) {
			clear();
			const params = { ...wrap(mode, { agent: "project", task: "test" }), agentScope: "project", confirmProjectAgents: false };
			const result = await execute(params);
			assert.equal(records().length, allowed ? 1 : 0, `${mode} env=${value}`);
			assert.equal(!!result.isError, !allowed);
			if (!allowed) assert.match(result.content[0].text, /PI_SUBAGENT_ALLOW_PROJECT_AGENTS=1/);
			cases++;
		}
	}
	delete process.env.PI_SUBAGENT_ALLOW_PROJECT_AGENTS;
	// User-scope agents never need consent, headless.
	clear(); assert.ok(!(await execute({ agent: "plain", task: "test" })).isError); assert.equal(records().length, 1); cases++;
	// Every text block of the final assistant message is returned (single, parallel, chain), joined by newlines.
	for (const mode of ["single", "parallel", "chain"]) {
		const result = await execute(wrap(mode, { agent: "plain", task: "MULTI_TEXT" }));
		assert.ok(result.content[0].text.includes("first part\nsecond part"), result.content[0].text);
		cases++;
	}
	clear();
	await execute({ chain: [{ agent: "plain", task: "MULTI_TEXT" }, { agent: "plain", task: "next {previous}" }] });
	assert.ok(records()[1].args.at(-1).includes("first part\nsecond part"), "{previous} carries all text blocks"); cases++;
	// Multibyte UTF-8 split across stdout/stderr chunks is decoded intact.
	for (const mode of ["single", "parallel", "chain"]) {
		const result = await execute(wrap(mode, { agent: "plain", task: "SPLIT_UTF8" }));
		assert.ok(result.content[0].text.includes("caf\u00e9 \u20ac \u{1F600}"), result.content[0].text);
		assert.ok(!result.content[0].text.includes("\ufffd"));
		cases++;
	}
	const split = await execute({ agent: "plain", task: "SPLIT_UTF8" });
	assert.equal(split.details.results[0].stderr, "err \u00e9"); cases++;
	// Renderers use the same failure predicate as execution: stopReason "error" with exit code 0 is a failure.
	const theme = { fg: (color, text) => `<${color}>${text}`, bold: (text) => text };
	const draw = (component) => component.render(200).join("\n");
	const rendered = async (params, expanded) => {
		const result = await execute(params);
		return draw(tool.renderResult(result, { expanded }, theme, {}));
	};
	for (const expanded of [false, true]) {
		for (const [mode, params] of [
			["single", { agent: "plain", task: "LLM_ERROR" }],
			["chain", { chain: [{ agent: "plain", task: "ok" }, { agent: "plain", task: "LLM_ERROR" }] }],
			["parallel", { tasks: [{ agent: "plain", task: "ok" }, { agent: "plain", task: "LLM_ERROR" }] }]]) {
			const out = await rendered(params, expanded);
			assert.ok(out.includes("<error>Error: provider failure"), `${mode} expanded=${expanded}: ${out}`);
			assert.ok(out.includes("<error>✗"), `${mode} expanded=${expanded}: ${out}`);
			if (mode === "chain") assert.ok(out.includes("1/2 steps") && out.includes("<success>✓"), out);
			if (mode === "parallel") assert.ok(out.includes("1/2 tasks"), out);
			cases++;
		}
		// A failure with only stderr (exit 1, no errorMessage) shows the stderr.
		const stderrOnly = await rendered({ chain: [{ agent: "plain", task: "test", model: "unavailable/model" }] }, expanded);
		assert.ok(stderrOnly.includes("Model unavailable/model not found") && stderrOnly.includes("0/1 steps"), stderrOnly);
		cases++;
	}
	// A pre-aborted call keeps the original rejection behavior and carries config in its last update.
	const controller = new AbortController(); controller.abort();
	const updates = [];
	await assert.rejects(execute({ agent: "plain", task: "WAIT_FOR_ABORT", model: "local/test", thinking: "off" }, updates, ctx, controller.signal), /aborted/);
	assert.deepEqual(updates.at(-1).details.results[0].selectedConfig, { model: "local/test", thinking: "off" });
	console.log(`PASS: ${cases} configuration/schema cases plus mixed modes, consent, chain stop, cleanup and abort`);
}
