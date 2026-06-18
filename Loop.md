# Loopcraft: The Art of Stacking Agent Loops

Agents are useful because they help us automate work by taking actions in the real world. But getting agents to do valuable work reliably takes more than just a good model: it requires a carefully designed harness that's fit to a set of tasks.

The core agent algorithm is simple: give the LLM context and let it call tools in a loop until it's done. This is the most fundamental loop. But it’s far from the only loop that powers agents. Swyx recently wrote a great piece on **"loopcraft: the art of stacking loops"**, the idea that you can stack and extend loops to build more effective agents.

Here's how we think about that stack, and how to instrument each level with LangChain primitives.

---

## Loop 1: The Agent

At its core, an agent is just a model calling tools in a loop until a task is complete.

![Loop 1](<https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a317cf80046aaedb90c50c6_loop1%20(1).png>)

This is what LangChain’s `create_agent` gives you. Pick any model, plug in tools, and you have a working agent loop. Tools are what give the agent the power to take action in the real world.

Take our internal docs agent as an example (which we’ll use as a motivating example for the rest of this blog). At the first loop level, it receives a request for a documentation improvement, the model plans and drafts changes, and it uses tools to clone repos, read files, write docs, open a pull request, etc.

![Docs Writer Agent Loop](https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a317dca401c7eac8f267ab7_docs_writer_agent_loop_white_bg.png)

---

## Level 2: Verification Loop

The agent loop gets work done, but it doesn't always produce correct or consistent work on the first pass. When consistency matters, it's often useful to wrap it in a verification loop that checks the output and sends feedback back to the model when it falls short.

![Verification Loop](<https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a317d145d0b7b0f966909fc_loop2%20(1).png>)

The verification loop adds a grader: something that checks the agent's output against a rubric and, if it fails, sends the result back with feedback. Graders can either be deterministic or agentic (LLM-as-a-judge is a classic example).

`RubricMiddleware` handles this pattern, or you can wire it up with an `after_agent` hook on `create_agent`.

For our docs writer example, the grader runs tests after each attempt, checking that:

- All links resolve
- All CI checks pass
- The diff is scoped to what was actually requested

No manual review is needed to catch those classes of error.

One tradeoff: adding verification increases latency and cost per run. It's worth it when quality matters more than speed, which is most production use cases.

![Docs Writer Verification Loop](https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a317dd76a131bd58de00fb9_docs_writer_verification_loop_white_bg.png)

---

## Level 3: Event-Driven Loop

One of the most important parts of agent development is the integrations layer: connecting your agent to your ecosystem so that it can run in the background.

The event-driven loop connects your agent to your ecosystem. An event fires—a new document lands, a schedule triggers, a webhook arrives—and the agent runs. The agent isn't something you invoke manually; it's a component running continuously inside a larger system.

![Event-Driven Loop](https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a317e69736b32a1e2363865_event_loop_generic_v3_white_bg.png)

LangSmith Deployment supports the trigger infrastructure, including support for cron schedules and webhooks. One popular example of crons in action is **heartbeats** in OpenClaw, which turn your agent into an always-on, proactive assistant.

Our docs agent is powered by Fleet, our no-code agent builder. Fleet's channels and schedules handle event-driven and cron-style triggers. We use a channel to fire off the docs agent whenever a message is sent in our `#docs-plz` Slack channel.

![Docs Writer Event Loop](https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a317e185240aaebb95cc7c3_docs_writer_event_loop_white_bg.png)

---

## Level 4: Hill Climbing Loop

The first three loops automate work. The fourth (and arguably most important) automates improvement.

![Hill Climbing Loop](https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a317e975f50e84a5bf17b80_hill_climbing_loop_generic_v2_white_bg.png)

Every agent run produces a trace: a record of what the model did, the tools it called, grader feedback, etc.

Those traces contain high-value signals regarding what's working and what isn't.

The hill climbing loop runs an analysis agent over those traces and uses the findings to rewrite the harness with improved configuration. That can include:

- Prompt tweaks
- Tool changes
- Grader improvements

In LangSmith, you can use **Engine**, a trace analysis agent, to instrument this fourth loop.

For the docs agent example, Engine analyzes traces to detect issues. When multiple traces signal a potential problem, an issue is filed requesting changes to the offending prompt or tool.

![Docs Writer Hill Climbing Loop](https://cdn.prod.website-files.com/65c81e88c254bb0f97633a71/6a317ea8af8c1790096c468d_docs_writer_hill_climbing_loop_v4_white_bg.png)

The key move here is that the return arrow doesn't just loop back to the top—it reaches inside and updates the agent loop directly. Each cycle of the outer loop makes the inner loops more effective.

### Looking Forward

Prompt and tool configuration are the simplest things to improve, but they're not the only options.

For teams running open-weight models, the hill climbing loop can feed into RL fine-tuning, using trace or evaluation outcomes as training signals to improve the model itself.

Auxiliary context such as:

- Memory
- Retrieved skills
- Knowledge sources

can be improved the same way.

The loop is the pattern; what it optimizes is up to you.

---

## Human Oversight and Expertise

Automation doesn't mean removing humans from the loop.

At every level, there are natural points where human oversight adds value.

An automated grader can check whether links resolve; it takes a human to notice whether the framing is wrong for the audience. That kind of judgment—earned from context, experience, and taste—is exactly where human review earns its place.

Some expertise should be codified in the prompt/tools themselves, but for sensitive actions, live human review is essential (e.g., financial transactions, database operations).

LangChain makes it straightforward to instrument these touch points in every loop:

1. **Agent loop** — Require human input before sensitive actions/tool calls.
2. **Verification loop** — A human can act as the grader for sensitive workflows.
3. **Application loop** — A human can approve outputs before they're returned to the end user.
4. **Hill climbing loop** — Harness improvements can flow through human review before deployment.

All of LangChain’s open-source frameworks make adding a **human in the loop** a first-class primitive.

---

## Putting It All Together

| Loop                      | What It Does                                                                           | Impact                              | LangChain Primitive                                                |
| ------------------------- | -------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------ |
| **1. Agent Loop**         | Model calls tools repeatedly until a task is complete                                  | Automate work                       | `create_agent`, any LangChain-supported model                      |
| **2. Verification Loop**  | Agent runs, output is scored against a rubric, retried with feedback if it fails       | Ensure work quality and correctness | `RubricMiddleware`                                                 |
| **3. Event-Driven Loop**  | Events trigger agent runs that update a real system                                    | Automated work at scale             | LangSmith Deployment with cron triggers/webhooks or Fleet channels |
| **4. Hill Climbing Loop** | Traces from production runs feed an analysis agent that improves harness configuration | Harness improvements                | LangSmith Engine                                                   |

---

## Conclusion

This is what **loop engineering**—or **loopcraft**, as Swyx puts it—looks like in practice.

AI leaders such as Steipete, Boris, and Andrej have all arrived at the same conclusion:

> The potential in agents is in the loops you build around them.

We've been thinking about loops 1 and 2 for a while. But the focus should increasingly shift toward loops 3 and 4, where value compounds by embedding agents into your ecosystem and continuously improving them according to your criteria.

As Satya Nadella frames the organizational stakes:

> Companies that build learning loops early—where human judgment and token capital compound together—will build an advantage that's hard to replicate.
