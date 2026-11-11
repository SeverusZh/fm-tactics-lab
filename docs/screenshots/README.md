# Screenshot provenance

These are real captures of the current source UI running with the v1103.2 native adapter and included example player inputs. The engine-settings static route fix on main is applied; the original published v1103.2 EXE is unchanged.

The current away-pool and save-tactics captures come from the same source UI loaded by the offline preview harness with example league metadata; they show the rotation and real-squad controls and the Overwrite home squad action without exposing a local save path.

- `tactics.png`: possession and out-of-possession tactical boards and team instructions.
- `players.png`: example outfield player's attributes and whole-squad editing controls.
- `results.png`: a real paired batch, six matches per variant, seeds 42–47, full event mode, two native workers. The reference uses the default mentality; the edited home side uses Positive mentality. All 12 matches completed with zero failures.
- `save-tactics.png`: the rebuilt save tactic page with the localized league list, one entry per competition, real AI tactics and the Overwrite home squad action. The save path field is blanked.
- `save-tactics-progress.png`: batch generation progress with finished variants appearing in the league table.
- `away-pool.png`: the away tactic pool popup with rotation mode, saved real squads, per-entry squad tags and the per-variant match count.

The screenshots demonstrate the interface. The small example batch is not a recommendation for a particular tactical setting. Captures use the Chinese UI, are cropped directly from the browser viewport; the save path field is blanked and no local filesystem paths are shown. No match values are inserted or retouched.
