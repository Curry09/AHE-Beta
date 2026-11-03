# Experiment Matrix

This document fixes the groups, comparison questions, and reporting conventions for the paper experiments. Engineering canaries (for example, ordinary N=1) are excluded from the paper’s main table unless they also meet the formal task/grader freeze requirements.

## Shared Control Variables

Except for the variable being ablated, keep the following consistent across groups: initial harness revision, five closed-loop rounds, task/mechanism category proportions, persona/seed, model, token budget, official task timeout, Daytona resources, grader, owner gate, and final held-out evaluation. Run each experimental track independently; intermediate revisions must not be shared.

Primary metric: official grader accuracy. Also report harness completion, user experience, interaction failure rate, deadline rate, token/cost, and wall time; report infrastructure failures separately and do not count them as task errors.

## A. Main Experiment

| ID | Name | Composition | Rounds | Purpose |
|---|---|---:|---:|---|
| M32 | Full-32 | 20 ordinary + 12 mechanism | 5 | Main paper experiment; complete user interaction, design, development, mechanical owner, and revision carry-forward |

M32 is the only main experiment. Treat all other conditions as ablations or robustness analyses; do not call them “main experiments” interchangeably with M32.

## B. Quantity Scaling Ablation

| ID | Sessions per round | Recommended composition | Rounds | Notes |
|---|---:|---:|---:|---|
| S4 | 4 | 3 ordinary + 1 mechanism | 5 | Smallest stratified subset |
| S8 | 8 | 5 ordinary + 3 mechanism | 5 | Keep category proportions close to M32 |
| S16 | 16 | 10 ordinary + 6 mechanism | 5 | Strict subset of M32 |
| M32 | 32 | 20 ordinary + 12 mechanism | 5 | Main experiment anchor |
| S64 | 64 sessions | 40 ordinary + 24 mechanism sessions | 5 | Run each of the 32 task/scenario identities once more using a second fixed persona/seed |

S4 ⊂ S8 ⊂ S16 ⊂ M32. S64 adds a second fixed interaction replicate on top of the current 32 identities; therefore, it must be written as **64 sessions** in the paper, not as 64 independent tasks. If 64 unique tasks/scenarios are actually added later, create a separate `S64-unique`; do not mix it with this version.

The previous ordinary N=1/N=4 five-round configurations were for the engineering pipeline and a small-scale pilot; N=4 contains no mechanism tasks, so it cannot directly serve as S4 here, since both “quantity” and “data composition” would change at once.

## C. User Interaction Ablation

Using the same set of 8 tasks that support both protocols, compare them in pairs with the same initial revision and seed:

| ID | Condition | N | Rounds | Only change |
|---|---|---:|---:|---|
| I8-D | Direct | 8 | 5 | Only the initial user request; no subsequent user intervention |
| I8-U | Simulated user | 8 | 5 | Use the historical persona/heartbeat user loop |

Do not force τ³’s benchmark-native user into the direct condition; it is not part of this paired experiment. This group answers “Does user interaction provide additional useful signal to the closed loop?” Report task accuracy and user experience, not just whether the harness returned final text.

## D. Closed-Loop Component Ablations

Use M32 as the base and retain at least the following three groups:

| ID | Condition | Removed component | Question to answer |
|---|---|---|---|
| L-NF | No user feedback | Designer/developer cannot see user traces, issue notes, or experience scores; retain only the objective grader | Does user feedback provide an improvement signal beyond the grader? |
| L-ND | No designer | Developer reads the frozen session + grader packet directly | Does the designer provide structured attribution and more stable changes? |
| L-NC | No carry-forward | Start from baseline v0 in every round; keep the number of other runs unchanged | Does the improvement come from accumulating revisions across rounds rather than repeated sampling/computation? |

A standalone “No developer” main ablation is not recommended: it substantially overlaps with the static baseline/L-NC and has no evolvable object. The round 1 v0 result can be reported as the static baseline.

## E. Mechanism Seed Group Ablation

After the 12 mechanism seeds are frozen, organize them into 3 families with 4 in each group. Until the final seed names are frozen, fix only the family semantics; do not invent task IDs in advance:

| Family | Semantic coverage | Examples |
|---|---|---|
| F-CORD | Collaboration and task decomposition | multi-agent, subagent, loop/handoff, parallel coordination |
| F-STATE | Intent and state management | goal, plan mode, memory, state retention across steps |
| F-CTRL | User control and side-channel communication | permission, `/btw`, steer/nudge, interrupt/cancel |

Perform leave-one-family-out:

| ID | Condition | N | Method for keeping N unchanged |
|---|---|---:|---|
| M-CO | Remove F-CORD | 32 | Replace with 4 difficulty-matched ordinary sessions |
| M-ST | Remove F-STATE | 32 | Replace with 4 difficulty-matched ordinary sessions |
| M-CT | Remove F-CTRL | 32 | Replace with 4 difficulty-matched ordinary sessions |

Do not simply reduce 32 to 28, as that would change both the mechanism family and the sample count. Match replacement tasks by benchmark,
difficulty, and expected duration, and fix them in the freeze record.

## F. Secondary/Appendix Experiments

The following groups are valuable, but including them in the main ablation table is not recommended:

| ID | Condition | Type | Reason |
|---|---|---|---|
| R-PM | `+ PM/divergent` | Role extension | PM is disabled in the main configuration; this adds a component rather than removing one |
| R-OWN | mechanical owner → LLM owner | Role robustness | Changes both cost and release policy, making interpretation more complex |
| R-MODEL | Change the harness/user model | Model robustness | Addresses cross-model generalization rather than causal ablation of harness mechanisms |
| R-SEED | Change the persona/random seed | Variance analysis | Used for confidence intervals and stability rather than system component ablation |

session drop, tool failure, budget pressure, and similar conditions are engineering stress tests; they are excluded from this paper's main experimental
matrix and presented separately as a reliability appendix to avoid conflating them with mechanism semantics and task distribution.

## Recommended Paper Table Structure

1. Main table: M32 final held-out accuracy, completion, feeling, cost, and curves over five rounds.
2. Quantity plot: sessions/round on the horizontal axis for S4/S8/S16/M32/S64, explicitly identifying S64 as a replicate.
3. Interaction table: per-task paired differences for I8-D vs I8-U.
4. Closed-loop ablation table: M32, L-NF, L-ND, L-NC.
5. Mechanism family table: M32, M-CO, M-ST, M-CT.
6. Appendix: R-PM, R-OWN, R-MODEL, R-SEED, and engineering stress tests.

If the budget is limited, the execution priority is: M32 → S8/S16/S64 → I8-D/I8-U → L-NF/L-ND/L-NC
→ three mechanism family leave-one-out experiments → appendix robustness experiments.
