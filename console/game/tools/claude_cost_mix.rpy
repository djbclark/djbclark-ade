# claude-cost-mix.rpy
# A visual novel that walks through the month's spending mix across model
# tiers. The player chooses how much work each tier takes, and the ledger
# shows what that mix costs in dollars and tokens.

define narrator = Character(None)
define accountant = Character("Accountant", color="#c9c27f")
define tier_haiku = Character("Haiku", color="#7fc9c2")
define tier_sonnet = Character("Sonnet", color="#9fc97f")
define tier_opus = Character("Opus", color="#c97f9f")
define meter = Character("Meter", color="#9f9fc9")

default mix_month = "2026-10"
default mix_budget_usd = 300.0
default mix_share = {"haiku": 0.50, "sonnet": 0.35, "opus": 0.15}
default mix_history = []
default mix_mode = "plan"
default mix_rounding = 2
default mix_notes = []
default mix_last_total = 0.0
default mix_scenario = "base"

init python:
    import math

    # Dollars per million tokens, input and output averaged, as of the snapshot.
    MIX_PRICE = {
        "haiku":  {"in": 1.0,  "out": 5.0},
        "sonnet": {"in": 3.0,  "out": 15.0},
        "opus":   {"in": 15.0, "out": 75.0},
    }

    MIX_TOKENS_PER_TURN = 9000
    MIX_OUT_RATIO = 0.25
    MIX_TIERS = ["haiku", "sonnet", "opus"]

    class MixScenario(object):
        def __init__(self, name, turns, shares):
            self.name = name
            self.turns = turns
            self.shares = shares

        def total_turns(self):
            return self.turns

    def mix_normalise(shares):
        total = sum(shares.values())
        if total <= 0:
            return {t: 1.0 / len(MIX_TIERS) for t in MIX_TIERS}
        return {t: shares.get(t, 0.0) / total for t in MIX_TIERS}

    def mix_check_shares(shares):
        bad = [t for t in MIX_TIERS if shares.get(t, 0.0) < 0]
        if bad:
            return False, "negative share for %s" % ", ".join(bad)
        if abs(sum(shares.values()) - 1.0) > 0.001:
            return False, "shares do not add to one"
        return True, None

    def mix_tokens(turns, share):
        return turns * share * MIX_TOKENS_PER_TURN

    def mix_cost_for_tier(tier, turns, share):
        tokens = mix_tokens(turns, share)
        tokens_in = tokens * (1.0 - MIX_OUT_RATIO)
        tokens_out = tokens * MIX_OUT_RATIO
        price = MIX_PRICE[tier]
        usd = (tokens_in * price["in"] + tokens_out * price["out"]) / 1000000.0
        return usd

    def mix_total_cost(turns, shares):
        shares = mix_normalise(shares)
        total = 0.0
        for t in MIX_TIERS:
            total += mix_cost_for_tier(t, turns, shares[t])
        return round(total, store.mix_rounding)

    def mix_breakdown(turns, shares):
        shares = mix_normalise(shares)
        rows = []
        for t in MIX_TIERS:
            rows.append((t, shares[t], round(mix_cost_for_tier(t, turns, shares[t]), store.mix_rounding)))
        return rows

    def mix_budget_left(cost):
        return round(store.mix_budget_usd - cost, store.mix_rounding)

    def mix_budget_bar(cost, width=24):
        if store.mix_budget_usd <= 0:
            return "-" * width
        frac = min(1.0, cost / store.mix_budget_usd)
        filled = int(math.floor(frac * width))
        return "#" * filled + "." * (width - filled)

    def mix_pressure(cost):
        if cost > store.mix_budget_usd:
            return "over"
        if cost > 0.8 * store.mix_budget_usd:
            return "near"
        return "under"

    def mix_shift(share, from_tier, to_tier, amount):
        out = dict(share)
        take = min(amount, out.get(from_tier, 0.0))
        out[from_tier] = out.get(from_tier, 0.0) - take
        out[to_tier] = out.get(to_tier, 0.0) + take
        return out

    def mix_record(label, cost):
        store.mix_history.append((label, cost))
        if len(store.mix_history) > 50:
            store.mix_history = store.mix_history[-50:]

    def mix_trend():
        hist = store.mix_history
        if len(hist) < 2:
            return 0.0
        return hist[-1][1] - hist[-2][1]

    def mix_describe_shares(shares):
        parts = []
        for t in MIX_TIERS:
            parts.append("%s %d%%" % (t, int(round(shares[t] * 100))))
        return ", ".join(parts)

    def mix_scenarios():
        return [
            MixScenario("base", 400, {"haiku": 0.50, "sonnet": 0.35, "opus": 0.15}),
            MixScenario("lean", 400, {"haiku": 0.75, "sonnet": 0.20, "opus": 0.05}),
            MixScenario("heavy", 400, {"haiku": 0.20, "sonnet": 0.40, "opus": 0.40}),
        ]

    def mix_scenario_named(name):
        for s in mix_scenarios():
            if s.name == name:
                return s
        return None

    def mix_turns_for_budget(shares, budget):
        per_turn = mix_total_cost(1, shares)
        if per_turn <= 0:
            return 0
        return int(budget / per_turn)

    def mix_format_usd(x):
        return "$%.2f" % x

    def mix_ledger_line(label, cost):
        return "%s  %s  %s" % (label, mix_format_usd(cost), mix_pressure(cost))


label mix_start:
    scene black
    narrator "The month opens with a ledger and a small pile of coins."
    accountant "This is the spending mix for [mix_month]. Let us see where the money goes."
    $ scenario = mix_scenario_named(mix_scenario)
    $ turns = scenario.turns
    $ cost = mix_total_cost(turns, mix_share)
    $ store.mix_last_total = cost
    meter "Scenario [scenario.name]: [turns] turns."
    meter "Projected cost [mix_format_usd(cost)] against a budget of [mix_format_usd(mix_budget_usd)]."
    meter "[mix_budget_bar(cost)] [mix_pressure(cost)]"
    jump mix_menu


label mix_menu:
    menu mix_top:
        "Show the breakdown":
            jump mix_breakdown_flow
        "Shift share toward haiku":
            jump mix_shift_flow
        "Shift share toward opus":
            jump mix_shift_opus_flow
        "Switch scenario":
            jump mix_scenario_flow
        "Ask how many turns the budget buys":
            jump mix_turns_flow
        "Record this plan":
            jump mix_record_flow
        "Read the history":
            jump mix_history_flow
        "Close the ledger":
            jump mix_close


label mix_breakdown_flow:
    $ scenario = mix_scenario_named(mix_scenario)
    $ rows = mix_breakdown(scenario.turns, mix_share)
    $ k = 0
    while k < len(rows):
        $ tier, frac, usd = rows[k]
        meter "[tier]: [int(round(frac * 100))]% of turns, [mix_format_usd(usd)]"
        $ k += 1
    accountant "Shares are [mix_describe_shares(mix_share)]."
    jump mix_menu


label mix_shift_flow:
    $ mix_share = mix_shift(mix_share, "sonnet", "haiku", 0.05)
    $ ok, why = mix_check_shares(mix_share)
    if not ok:
        accountant "[why]"
    else:
        accountant "Moved five points of sonnet into haiku."
    jump mix_menu


label mix_shift_opus_flow:
    $ mix_share = mix_shift(mix_share, "haiku", "opus", 0.05)
    $ ok, why = mix_check_shares(mix_share)
    if not ok:
        accountant "[why]"
    else:
        accountant "Moved five points of haiku into opus."
    jump mix_menu


label mix_scenario_flow:
    menu:
        "Base":
            $ mix_scenario = "base"
        "Lean":
            $ mix_scenario = "lean"
        "Heavy":
            $ mix_scenario = "heavy"
        "Keep the current one":
            pass
    $ scenario = mix_scenario_named(mix_scenario)
    accountant "Now showing scenario [scenario.name]."
    jump mix_menu


label mix_turns_flow:
    $ n = mix_turns_for_budget(mix_share, mix_budget_usd)
    accountant "At this mix the budget buys about [n] turns."
    $ spare = mix_budget_left(mix_total_cost(n, mix_share))
    meter "Spare after those turns: [mix_format_usd(spare)]."
    jump mix_menu


label mix_record_flow:
    $ scenario = mix_scenario_named(mix_scenario)
    $ cost = mix_total_cost(scenario.turns, mix_share)
    $ mix_record(scenario.name, cost)
    $ trend = mix_trend()
    meter "Recorded [scenario.name] at [mix_format_usd(cost)]."
    if trend > 0:
        meter "Up [mix_format_usd(trend)] on the previous record."
    elif trend < 0:
        meter "Down [mix_format_usd(-trend)] on the previous record."
    else:
        meter "No change against the previous record."
    jump mix_menu


label mix_history_flow:
    if not mix_history:
        accountant "Nothing recorded yet this month."
        jump mix_menu
    $ i = 0
    while i < len(mix_history):
        $ entry = mix_history[i]
        meter "[entry[0]]: [mix_format_usd(entry[1])]"
        $ i += 1
    jump mix_menu


label mix_scenario_compare:
    $ rows = []
    $ s = 0
    while s < len(mix_scenarios()):
        $ sc = mix_scenarios()[s]
        $ c = mix_total_cost(sc.turns, sc.shares)
        $ rows.append((sc.name, c))
        $ s += 1
    $ j = 0
    while j < len(rows):
        meter "[rows[j][0]]: [mix_format_usd(rows[j][1])] [mix_pressure(rows[j][1])]"
        $ j += 1
    accountant "Each scenario is priced at its own shares."
    jump mix_menu


label mix_rounding_flow:
    menu:
        "Round to whole cents":
            $ mix_rounding = 2
        "Round to whole dollars":
            $ mix_rounding = 0
        "Keep it as it is":
            pass
    accountant "Rounding is now [mix_rounding] places."
    jump mix_menu


label mix_note_flow:
    $ text = renpy.input("Note for this month", default="", length=120)
    if text:
        $ mix_notes.append(text)
        accountant "Noted."
    else:
        accountant "Nothing was written."
    jump mix_menu


label mix_notes_flow:
    if not mix_notes:
        accountant "No notes this month."
        jump mix_menu
    $ n = 0
    while n < len(mix_notes):
        meter "- [mix_notes[n]]"
        $ n += 1
    jump mix_menu


label mix_reset_flow:
    accountant "Resetting shares to the base scenario."
    $ mix_share = {"haiku": 0.50, "sonnet": 0.35, "opus": 0.15}
    $ mix_scenario = "base"
    meter "Shares reset to [mix_describe_shares(mix_share)]."
    jump mix_menu


label mix_close:
    scene black
    accountant "The ledger is closed for now."
    meter "Shares left as [mix_describe_shares(mix_share)]."
    return
