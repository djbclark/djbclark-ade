---
name: eli5
description: >-
  Write an ELI5 or plain-language explanation: short sentences, active voice, one everyday analogy, then the real
  technical terms. Use whenever the operator or a user asks for "ELI5", "explain like I'm five", "plain-language
  explanation", "explain simply", or an explanation "for a non-expert", and when you explain a concept to a reader
  who lacks the domain context.
---

# ELI5: explain it simply, and keep it true

The reader is a smart person who lacks the domain context. The reader is not a child. Do not use baby talk.
The r/explainlikeimfive rule says the same. It reads: "Don't condescend." It calls "like I'm five" a figure of
speech for "keep it clear and simple."

These rules are STE-based, not STE. They borrow from ASD-STE100 Issue 9 but do not use its controlled dictionary.
Never claim STE compliance. STE sets these limits:

- 20 words per procedure sentence (rule 5.1) and 25 words per descriptive sentence (6.3).
- Six sentences per paragraph (6.6).
- Three words per multi-word noun (2.1).

Our limits are stricter on purpose.

## Writing rules

1. Keep every sentence to 20 words or fewer. This house rule covers all text in an ELI5 answer, not other agent output. It is not an STE limit.
2. Give one idea in each sentence.
3. Use the active voice. Name the actor: "The server sends the page", not "The page is sent".
4. Use a direct verb. Write "start", not "perform an initialization of".
5. Use one word for one thing. Never swap in a synonym for variety (STE 1.11 for technical nouns, and the Google style guide).
6. Put no more than three nouns in a row. Expand dense compounds (STE 2.1).
7. Write literally. Use "because" and "although", not "since" and "while". Avoid idioms, slang and jokes.
8. Keep paragraphs to 3 or 4 sentences, on one topic. This is stricter than the STE limit of six.
9. Spell out every acronym and define every technical term once. Otherwise leave it out.
10. Put the condition first: "If the file is missing, the tool stops."

Do not write filler, throat-clearing or praise for the question.

## Required structure, in this order

1. **Core idea.** One or two sentences: what it is and which problem it solves.
2. **Everyday analogy.** Pick one familiar thing whose behaviour matches the real behaviour. STE avoids loose
   figures of speech, because every STE word has one literal meaning. So the analogy lives only in this
   section, labelled as an analogy. End with "Where the analogy breaks": one or two sentences, because every analogy is imperfect.
3. **How it works.** Give the steps in causal or time order. Say what each step causes.
4. **Term map.** Give the technical names only now. Define each name once and tie it back to the analogy.
5. **Optional last line.** Offer the next level of detail in one sentence.

For a small question, use one paragraph: core idea, analogy, and where it breaks.

## Check before you send

1. Check the answer against the real system: read the code or the docs, or run the command. Accuracy comes first.
2. If the analogy forces a false claim, change the analogy. Do not bend the facts.
3. If you cannot explain a step simply, you found a gap in your own knowledge. Go back to the source (Feynman technique).
4. Count the words in your longest sentences. Split any sentence over 20 words.

## Reply format for the operator

Standing order 5 still applies: Roman sections, bold-italic item labels, script-issued `Ref:` line (docs/ref-labels.md). When the answer has sections, the first four parts above become **I.** to **IV.**; the optional last line has no heading.

Sources and prior art: [docs/eli5-sources.md](../../docs/eli5-sources.md).
