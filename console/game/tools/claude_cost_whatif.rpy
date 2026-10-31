## claude-cost-whatif: what-if analysis on the last N days of Claude Code transcripts.
## Port of the original bin/claude-cost-whatif (Python). Entry label: tool_claude_cost_whatif.
##
##   claude-cost-whatif [DAYS]          DAYS defaults to 7
##
## A. Cache TTL: observed (1h, writes 2.0x) vs a 5-minute TTL (writes 1.25x, but a request after a
##    5-60 min idle gap re-writes its whole cached prefix instead of reading it).
## B. Compaction threshold T: when context crosses T, compact to floor F (measured 104k); the
##    compaction costs a summarisation call plus re-writing F at the write weight; later requests in
##    that transcript shrink by (C - F) until the next one.
## Units: input-token equivalents. Approximations, not billing.
## Exit 0 ok, 2 usage. Output goes to stdout (the caller reads it); narrator is not used.

init python:
    import glob
    import json
    import os
    import sys
    import time
    from datetime import datetime

    CW_W1H, CW_W5M, CW_OUT = 2.0, 1.25, 5.0
    CW_PRICES = {"claude-opus-5-5": (4.0, 0.05), "claude-sonnet-5-5": (2.0, 0.05), "claude-fable-5-1": (10.0, 0.025)}
    CW_F, CW_SUMMARY_OUT = 104_000, 6_000

    def cw_price(model):
        return next((v for k, v in CW_PRICES.items() if (model or "").startswith(k)), (1.0, 0.1))

    def cw_ts(s):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    def cw_load(days):
        """Return one list of (t, B, R, is_sub, input, cache_write, cache_read, output) per transcript."""
        cut = time.time() - days * 86400
        seqs = []
        for f in glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True):
            if os.path.getmtime(f) < cut:
                continue
            seen, seq = set(), []
            for line in open(f, errors="replace"):
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                m = d.get("message") or {}
                u, mid = m.get("usage") or {}, m.get("id")
                if not u or not mid or mid in seen:
                    continue
                seen.add(mid)
                b, r = cw_price(m.get("model"))
                seq.append((cw_ts(d.get("timestamp", "")), b / 1e6, r, "/subagents/" in f,
                            u.get("input_tokens", 0), u.get("cache_creation_input_tokens", 0),
                            u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0)))
            if seq:
                seqs.append(seq)
        return seqs

    def cw_ttl(seqs):
        """Section A. Returns (lines, obs, gap_reqs, n_req, gap_tokens, five, sub5)."""
        obs = five = sub5 = 0.0
        gap_reqs = gap_tokens = 0
        for seq in seqs:
            prev = None
            for t, B, R, sub, i, cw, cr, o in seq:
                here = B * (i + cw * CW_W1H + cr * R + o * CW_OUT)
                obs += here
                gap = prev is not None and t is not None and 300 < t - prev <= 3600
                alt = B * (i + (cw + cr) * CW_W5M + o * CW_OUT) if gap else B * (i + cw * CW_W5M + cr * R + o * CW_OUT)
                five += alt
                sub5 += alt if sub else here
                if gap:
                    gap_reqs += 1
                    gap_tokens += cr
                prev = t if t is not None else prev
        n_req = sum(len(s) for s in seqs)
        lines = [
            f"A. TTL  transcripts {len(seqs)}, requests {n_req:,}",
            f"   observed 1h TTL everywhere: ${obs:,.0f}   5-minute everywhere: ${five:,.0f} ({(five-obs)/obs:+.1%})"
            f"   main 1h + sub-agents 5m: ${sub5:,.0f} ({(sub5-obs)/obs:+.1%})",
            f"   requests after a 5-60 min idle gap: {gap_reqs:,} ({gap_reqs/max(n_req, 1):.1%}), "
            f"cached tokens they would re-write: {gap_tokens/1e6:,.1f}M",
        ]
        return lines, obs

    def cw_threshold(seqs, T, obs):
        """Section B for one threshold (None = observed). Returns (total, n_comp)."""
        total = 0.0
        n_comp = 0
        for seq in seqs:
            drop = 0
            prev_ctx = 0
            for t, B, R, sub, i, cw, cr, o in seq:
                ctx = i + cw + cr
                if prev_ctx and ctx < 0.6 * prev_ctx:
                    drop = 0  # an observed compaction or /clear: the real history already shrank
                prev_ctx = ctx
                eff = max(ctx - drop, 0)
                if T and eff > T:
                    n_comp += 1
                    total += B * (eff * R + CW_SUMMARY_OUT * CW_OUT + CW_F * CW_W1H)
                    drop += eff - CW_F
                    eff = CW_F
                cr_eff = max(cr - drop, 0)
                total += B * (i + cw * CW_W1H + cr_eff * R + o * CW_OUT)
        return total, n_comp

    def cw_report(days):
        seqs = cw_load(days)
        ttl_lines, obs = cw_ttl(seqs)
        out = list(ttl_lines)
        out.append("B. compaction threshold (simulated on top of observed history)")
        for T in (None, 500_000, 400_000, 300_000, 250_000, 200_000, 150_000):
            total, n_comp = cw_threshold(seqs, T, obs)
            label = "none (observed)" if T is None else f"{T//1000}k"
            out.append(f"   T={label:<16} total ${total:,.0f}  ({(total-obs)/obs:+.1%})  extra compactions {n_comp:,}")
        return out

label tool_claude_cost_whatif:
    python:
        if len(ade_argv) > 1:
            print("usage: claude-cost-whatif [DAYS]", file=sys.__stderr__)
            ade_exit_code = 2
        else:
            try:
                _cw_days = float(ade_argv[0]) if ade_argv else 7.0
            except ValueError:
                print("usage: claude-cost-whatif [DAYS]", file=sys.__stderr__)
                ade_exit_code = 2
            else:
                for _cw_line in cw_report(_cw_days):
                    print(_cw_line, file=sys.__stdout__)
                ade_exit_code = 0
        sys.__stdout__.flush()
        sys.__stderr__.flush()
    return
