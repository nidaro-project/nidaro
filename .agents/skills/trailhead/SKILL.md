---
name: trailhead
description: A focused check before a simple feature. Questions until we're on the same page, a short path, then build on confirm.
disable-model-invocation: true
---

A simple feature has arrived: the way to done is roughly visible and one session can hold the work. Trailhead is the day hike next to wayfinder's expedition. Grilling works a whole design tree, every branch, adjacent domains included, until nothing anywhere is left assumed; trailhead works the feature's own tree until you and the user share an understanding of the path. Focus comes from where questions live, never from a round count. Every question sits on the trail, this feature, and the periphery becomes defaults the user can veto. If the feature turns out bigger than one session, that is wayfinder territory. Stop and say so.

## Scout

Look before asking. Read the code where the feature lands, the pattern it should follow, and the tests that will hold it. How another part of the repo behaves is a fact, so read it; a question is for a decision the user owns. Every fact you read is a question you never ask.

Done when you can name the files the feature touches, the pattern to follow, and the tests that will hold it, without guessing.

## The check

Interview in rounds. Each round asks the open forks in one batch, numbered, each with a recommended answer, then waits.

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

A question earns its place through the fork test: the answer changes what gets built on this trail. A fork too small to ask about takes the natural default and rides to the path. After each round, recompute the forks the answers opened and ask the next round. Rounds run as long as the trail holds open forks; shared understanding is the goal, and it takes the rounds it takes. Done when no fork is open and every skipped question sits recorded as a default.

## The path

Write the path as numbered steps, the files each step touches, and a last step that verifies the feature works. Under the steps list the defaults, one line each. Anything the check turned up beyond the feature gets one line under an `Off trail` heading, parked, out of the interview.

Reading the path with no vetoes is the shared-understanding seal. Wait for it. A vetoed default becomes one more question. Answer it, correct the path, and wait again.

## Walk it

On confirmation, build. Follow the path in order. A fork mid-build goes to the recorded default unless reality forbids it, and a fork nobody anticipated stops the work for one question.

Done when the verify step passes.
