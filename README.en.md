# FM Tactics Lab

[简体中文](README.md) | **English**

**Test your tactics locally with the original FM27 match engine.**

Configure both squads in Free Simulation or import an FM27 career save to play opponents from the same league. Compare scores, xG, shots, possession and passing statistics across complete matches.

Use it to explore which formation suits your players, how pressing or role changes affect performance, and whether an advantage holds across repeated matches.

## Interface preview

Edit possession and out-of-possession formations, team instructions and player roles side by side.

![Dual-phase tactical boards and team instructions](docs/screenshots/tactics.png)

The screenshots show Free Simulation with the included example players. The interface is in Chinese.

Save tactics: read a career save, browse any loaded league's coaches by primary and secondary preference preset, then export or add them to the away tactic pool.

![Save tactics page](docs/screenshots/save-tactics.png)

Away tactic pool: open the pool button beside Run matches to draw away tactics by weight or rotate through every candidate, using uniform attributes or save squads.

![Away tactic pool page](docs/screenshots/away-pool.png)

## How it works

The tool loads the original match engine from your local FM27 installation. It supplies player and tactical inputs, then runs the original code for decisions, movement, passing, challenges, shooting and match rules until the match finishes naturally.

```text
Players and tactics → Original engine runs a complete match → Scores, events and statistics → Batch comparison
```

**Match calculation and visual presentation are separate layers.** The engine advances players, the ball and match events; the match view presents those states. FM Tactics Lab runs detailed matches in the background and collects their results without displaying the pitch.

### Is this a played match, a holiday simulation, or Instant Result?

The tool runs the **original detailed match calculation**, corresponding to the detailed simulation layer used when entering a match. Set your inputs before kickoff, let the engine finish, then inspect the results. Live player interventions such as changing tactics or giving touchline instructions belong to the normal game interface.

A complete background simulation can also use detailed match logic. Holiday and Instant Result additionally involve game-level task scheduling and assistant management. Think of this project as a way to run the original detailed engine repeatedly for tactical experiments.

### Comparing results

Player actions and match rules use the original implementation. Scores, xG, shots and passing statistics are read from native match objects.

Each batch uses a sequence of random seeds. When comparing a saved reference with an edited setup, both variants run with the same seed sequence. Repeated matches help show average changes and variability.

## Download and launch

The current source version is **v1111.2**. Download published desktop builds from [GitHub Releases](https://github.com/lqf0624/fm-tactics-lab/releases). Exit the previous app from its tray menu before launching an update.

Install FM27, open Steam and sign in to the account that owns the game, then launch the EXE. The tool looks for your installation automatically. You can also select the game root containing `fm_Data` and `shared` in the engine settings at the top.

The EXE includes its Python runtime. Players do not need Python or a compiler. The desktop interface in this release is in Chinese; the English documentation below explains the controls. Source setup is described in the [developer guide](docs/DEVELOPMENT.md).

## Career-save matches

1. Switch to **存档对战** (Career-save Matches), import an FM27 .fm save, and select the club you manage.
2. Load its tactic, review first-team attributes, and adjust your starting lineup and bench.
3. Select opponents from the same league. Preview their in-possession and out-of-possession boards, then run home and away matches.

Opponent tactics use a built-in preset selected from the head coach's saved style and formation preferences. A team is selectable when both the coach and preferences can be verified. Opponent squads load in batches as needed. You can track or cancel match preparation.

## Save tactics

On **存档战术** (Save Tactics), read a save, then pick any loaded league in the game world to list every opponent head coach's preferences, excluding your club. Each coach produces up to two original game presets: one for his primary preferred formation and one for his secondary formation (tactic 1 and 2; a single preset remains when the secondary preference is missing or identical). Export the league's tactics into a local folder or add them to the away tactic pool in one click; pool imports are not deduplicated, so the same tactic may be added more than once and keep the club's current squad and attributes for real-roster mode. The per-row **覆盖主队名单** (Overwrite home squad) button copies that save club's squad and attributes onto the home team on the player attributes page. Exported files follow `club-coach-第1套战术.fmf` / `club-coach-第2套战术.fmf` (the tactic suffix is Chinese). League and country names are read from the local FM27 game database and follow the interface language (Chinese or English); each league is listed once, using the active or nearest schedule, and unavailable names fall back to league numbers. Exported files are preset approximations, not the actual match-day tactics.

Opponents in your current league can also batch-generate **real AI tactics**: for each club the tool reads its current head coach, current squad and your own coach, runs the original engine's zero-tick match preparation, and reads back the AI-generated two-phase plan (mentality, team instructions, roles and duties, player instructions and phase mapping). Every opponent produces two plans - tactic 1 for the opponent at home and tactic 2 for the opponent away - and they replace the two list columns (shown as `club home tactic` / `club away tactic`). Generation shows a progress bar, caches finished variants and only fills missing clubs and contexts on later full runs, while a single-club button rebuilds both of that club's plans; the cache is bound to the generation engine identity, so a changed original engine or native adapter invalidates it and regenerates. Export as `club-coach-主场战术.fmf` or `club-coach-客场战术.fmf` or import straight into the away tactic pool; export and pool import merge generated plans with still-available manager presets per club and variant, keep presets for clubs without generated plans and report them as omitted. This is the original AI's output in a controlled preview context (current save squad, fixed preview seed 0 and the tool's default player-side template), not a recording of a finished match; a real fixture is generated by the in-game AI from its own squad and context, and this tool never recalculates per match - the away tactic pool stores this fixed plan. Clubs whose coach profile falls outside the engine's supported range keep their presets and show the failure reason.

![Batch real AI tactic generation progress](docs/screenshots/save-tactics-progress.png)

## Free Simulation

### 1. Configure both squads

Start with the included player inputs and choose each side's starting lineup. Both sides can be edited independently. In **球员属性** (Player Attributes), adjust abilities and positional familiarity. Export a full JSON setup to keep your experiment.

![Player attributes and whole-squad editing](docs/screenshots/players.png)

### 2. Import or edit a tactic

Open **战术板** (Tactics Board):

- Use **导入主队／客队比赛战术 FMF** to import a home or away tactic.
- Edit **有球阶段** (In Possession) and **无球阶段** (Out of Possession) separately; both phases share the starting lineup.
- Drag shirts to swap players while keeping roles, duties and instructions attached to their positions. Moving to an empty position prompts for confirmation if any settings need to change.
- Adjust mentality, passing, pressing and other team instructions.
- Configure or import set-piece routines separately in **定位球与职责** (Set Pieces and Responsibilities).
- **Away tactic pool**: open the pool button beside Run matches to enable it, manage candidates, import FMF and choose the draw mode and away squad source. Save tactics can add candidates without enabling the pool. Disabling it retains candidates and settings and uses the currently selected opponent tactic.
- Draw modes: random draws by weight for each match; rotation plays every candidate in order for the configured number of rounds, and matches per variant automatically equal candidates times rounds. Both modes are derived from the task seed and reproduce within the same experiment.
- Away squads: uniform sets every away player's ability attributes to the configured panel value (15 by default) and gives starters maximum positional familiarity 20 for the tactic's positions; real roster uses the saved club's current squad and attributes and requires every candidate to come from Save tactics. FMF-imported tactics have no saved squad and therefore only support uniform attributes. Saved squads stay inside the local setup; saved-squad candidates are capped at about 1.5 MB in total, so reduce or clear candidates when the limit is hit.

Imported tactics remain editable. The dice button beside the starting seed generates a random seed.

### 3. Run matches

At the bottom, set the starting seed, matches per variant and worker count, then select **运行比赛** (Run Matches). Start with a small batch to check your setup.

| Setting | Purpose |
| --- | --- |
| 起始种子 — Starting seed | Controls the batch's seed sequence for later comparison; the dice button generates a random value |
| 每方案场数 — Matches per variant | Number of matches for each setup; in rotation mode this equals candidates times rounds |
| 并行数 — Workers | Number of concurrent native workers |
| 快速模式 — Quick mode | Complete detailed matches, scores and team statistics, with reduced player-event collection |
| 完整模式 — Full mode | Also collects and checks scorer, assist and card details |

**Quick mode still runs complete detailed matches.** The difference is the scope of event collection and validation.

### 4. Read the results

Open **实验结果** (Results) for batch summaries, averages and individual matches. Full mode includes player-event details. Export individual results as CSV to keep your own comparisons.

Failed matches are listed separately. Aggregates use completed matches that passed validation.

![Paired tactical comparison and native team statistics](docs/screenshots/results.png)

Example: six completed matches per variant, showing the comparison, xG, shots, possession and passing statistics.

## Example: does stronger pressing help?

1. Load your original tactic, confirm both squads and set pieces, and save it as the reference.
2. Increase pressing while keeping the other inputs unchanged.
3. Enable **与已保存战术对比** (Compare with Saved Tactic), choose the seed and batch size, then run.
4. Compare goals for and against, xG, shots and possession.
5. Try another seed sequence or opponent setup, or swap home and away, to examine stability.

With 100 matches per variant, the tool runs 100 reference matches and 100 edited matches: 200 in total. The saved reference contains the entire setup, so changing one thing at a time makes the comparison easier to interpret.

## Reading the numbers

| Question | Look at |
| --- | --- |
| Is attack improving? | Goals, xG, shots and shots on target |
| Is defence improving? | Opponent goals, xG, shots and shots on target |
| Is the playing style changing? | Possession, passes and completed passes |
| Is the advantage stable? | Multiple seed sequences, opponent setups and home/away comparisons |

For example, after increasing possession, check whether the side also creates more or better shooting opportunities.

### Starting conditions

Both full squads start with condition and match sharpness at 100%, accumulated fatigue at 0, morale at 20/20, team cohesion at 80 and club cohesion at 100. States evolve normally after kickoff. This makes repeated tactical comparisons easier; consider actual fatigue, morale, cohesion and injuries when applying findings in your season.

### Tactical effectiveness experiment

Set tactical understanding, player buy-in and opposition information separately for each team on a 0–100 scale. The native engine calculates player ability contributions from each player's CA and suitability for both phase roles. The experiment is off by default. Career-save effectiveness values are not yet available.

The away tactic pool can be combined with experimental tactical execution. Each side retains its three manual scores, while the native engine computes ability contribution from the current away players' CA and the assigned tactic's two-phase roles. Execution matches use isolated processes and run more slowly than normal reused sessions. The pool changes tactics; uniform mode retains the current away squad, real-roster mode uses the saved club's squad. Native-generated tactics remain incompatible with the pool.

## Save and export

- **Full setup JSON:** save both sides and reopen the setup for later experiments.
- **Tactic FMF:** export the selected side's tactic; set pieces have separate export controls.
- **Match CSV:** save individual results for analysis.
- **Experiment history:** name, find, rename or delete experiments. Confirming deletion removes their local results and logs.
- **Tray menu:** open the local results directory or exit the desktop tool.

## Version and project information

The current source version is **v1111.2**, for Windows x64. The adapter reference build is `27.0.1+2494687`. Tool code is licensed under MIT; the engine and game resources come from your local installation.

Original engine code and a career match's complete conditions are separate considerations. This tool standardizes starting states; inputs, random states and in-match interventions affect results. Evidence and validation scope are described in [Simulation Fidelity](docs/SIMULATION_FIDELITY.md).

For startup, path or version issues, see [Troubleshooting](docs/TROUBLESHOOTING.md). Developers can read the [build guide](docs/DEVELOPMENT.md), [contribution guide](CONTRIBUTING.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

The interface and system tray follow the Windows display language. Simplified Chinese and English are supported, with English as the fallback. Player names, club names, tactic data and raw logs retain their original text.

## v1111.2 compatibility

Supports the official FM27 27.0.1+2494687 engine and combines PR #3 with the v1111 adapter and save-reader fixes. AI plans use current squads, seed 0 and the default player-side template in a controlled preview; pool entries remain fixed plans.
