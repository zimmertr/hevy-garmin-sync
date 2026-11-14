# hevy-garmin-sync: specification

Audience: the AI agent implementing this project. Status: signed off by TJ on 2026-11-07; tracked in #1. Source of truth for scope and requirements; record every change here with a date. Last updated 2026-11-13 (the check of each Hevy app release is in F-48; each set's note rewritten after the arm day of 2026-11-13, and warm-ups given the rep range, are in S-2, F-4a, F-22, F-24, F-25, F-27, F-28a, F-30, F-30b, C-12 and B-3; changes from the final review are marked 2026-11-10; choices made during the build are in D-11; the first watch check of the built code and the Hevy read of 2026-11-10 are in F-28a, F-50, U-17, C-7 and D-11; the live checks of 2026-11-10 and 2026-11-11 and the midnight run of 2026-11-11 are in F-31, F-53, U-10, C-7, D-10 and D-11; the second live check of 2026-11-11 is in F-16, F-20a, F-31, U-10, U-15, D-10, D-11 and B-5; the notes check of 2026-11-11 is in F-30 and B-3; last time's sets in each set's note, built on 2026-11-11, are in S-2, F-3b, F-4, F-4a, F-30b, C-12 and B-3, with the set type and the <code>Goal:</code> line each on a line of their own in F-30; the status page, manual syncs and the health checks, built on 2026-11-12 for #31, are in S-3, F-2, F-3a, F-4, F-4a, F-4b, section 11, O-1, O-2, section 12a, D-4 and D-11).

## 0. How to use this document

- Requirement IDs (`G-` goal, `S-` scope, `F-` functional, `C-` configuration, `A-` auth, `O-` operations, `D-` delivery) are stable. Cite them in code comments, commits, tests and PRs.
- MUST and MUST NOT are hard requirements. SHOULD is the default unless an `U-` item proves it impossible; then stop and ask TJ.
- Section 9 lists unverified assumptions (`U-`). Resolve each before building anything that depends on it, and record the result here.
- Live tests run against TJ's own Garmin and Hevy accounts. Ask TJ before each live test.
- Do not start any work until TJ explicitly says to. When something is ambiguous, ask TJ with simple questions. Do not invent names for mechanisms; use real identifiers.
- Any proposal outside this document's scope must be raised with TJ, not built.
- The watch session that had to come before the build is done (2026-11-10): U-22, U-23, U-24, U-25 and U-26 are resolved in section 9, and the delivery decision is in F-31a.

## 1. Goal and scope

<div class="wrap">

| ID | Statement |
|----|----|
| G-1 | Get Hevy workouts to Garmin. Each selected Hevy routine (and, if enabled, each Hevy Trainer workout) exists as a Garmin Connect workout with correct exercises, sets, rep targets and weights, selectable on the watch. |
| G-2 | Strava correctness is achieved indirectly: Strava keeps the watch's first upload (forwarded by Garmin's own Strava connection within seconds), so the planned workout decides what Strava shows. The app has no Strava integration. |
| S-1 | One direction only: Hevy (read) to Garmin (write). MUST NOT write to Hevy. MUST NOT modify Garmin activities (recordings). MUST NOT call Strava. |
| S-2 | Reading logged Hevy workouts is allowed only to compute Hevy Trainer prescriptions (F-40..F-46) and to show last time's sets on the status page (F-30b; TJ, 2026-11-11, #3; TJ, 2026-11-13). |
| S-3 | Out of scope: merging Hevy sets into Garmin activities (what hevy2garmin does), Strava titles or descriptions, notifications, changing settings from the status page (#57), any feature that depends on Docker-specific runtime configuration, cleanup or uninstall commands, dry-run mode, per-user overrides for built-in exercises (a custom exercise's Garmin exercise can be set, C-11; TJ, 2026-11-10, #24), multiple users per process. A web page and health checks were out of scope until 2026-11-12; they are section 12a now (TJ, #31). |
| S-4 | Target users: TJ first; then anyone with Hevy Pro, a Garmin watch that supports strength workouts, and basic Docker or Kubernetes skills. Docker is the primary way to run it. Kubernetes is secondary (TJ's own setup). |

</div>

**Rationale (do not re-litigate without TJ):** hevy2garmin is designed to correct Garmin activities after the session, which never reaches Strava. Strava's public API cannot edit exercise sets or delete activities (checked 2026-11-07). Reverse-engineering Strava's app was rejected because Strava's terms forbid it. Garmin's personal API key (opened 2026-10-21) is read-only, so it cannot create workouts. Garmin's Training API requires business-tier access.

## 2. Runtime model

<div class="wrap">

| ID | Requirement |
|----|----|
| F-1 | Single long-running process. On start: validate config (C-\*), load tokens (A-\*), run a full sync. Then loop: poll Hevy every `HEVY_POLL_INTERVAL_SECONDS`, and run the day rollover (F-31) at local midnight in `TZ`. All timers live inside the process. MUST NOT rely on external cron, Kubernetes CronJobs or sidecars. |
| F-2 | No webhook receiver. The one listening port serves the status page and its API (W-1; TJ, 2026-11-11, #31; it was "no listening ports" until then). Hevy has one webhook, for saved workouts only, set up on its developer settings page; none covers routines, and the public API has no routine change feed (only `GET /v1/workouts/events`, which covers workouts). A webhook would also need the port open to the internet. So the app polls (verified 2026-11-07 from the API spec; the webhook corrected 2026-11-10, recorded in `docs/DATA.md`). A weekly check compares the spec's paths with a copy in the repo, so a new path, such as a routine feed, opens an issue (TJ, 2026-11-10, #26). |
| F-3 | A sync is idempotent: compute the desired Garmin state from Hevy, compare with the Garmin workouts and calendar entries the app owns (F-12), apply only the differences. |
| F-3a | Principle (TJ, 2026-11-07): any change in Hevy must reach Garmin as fast as possible. Polling exists because routines have no feed and a webhook would need the port open to the internet (F-2, corrected 2026-11-10 and 2026-11-12); never trade speed for fewer calls without asking TJ. Every poll checks everything: routines, folders, and with Trainer, saved, edited or deleted workouts (`GET /v1/workouts/events?since=`, public) and the Trainer program (private). |
| F-3b | Expected Hevy load at 60 s: 2 requests per poll without Trainer (routines, folders, more if over 10 of either), 4 with Trainer; about 2,900 and 5,800 a day. After a saved Trainer workout, about 7 more (history at 3 per page, both preferences). Hevy access-token refresh about every 30 minutes. Exercise templates are read once as a whole list and cached in memory (D-11c, 2026-11-10). Last time's sets (F-30b, on by default) add the workout events to a poll without Trainer, so 3 requests and about 4,300 a day; with Trainer the events are read anyway. They also add one exercise history read for each exercise in a synced workout, once, at startup (2026-11-11, #3). |
| F-3c | Expected Garmin load for TJ (2 Trainer workouts): about 10 to 40 calls a day. A changed workout costs about 4 calls (1 update, then 3 for the push: last-used device, workout name, the message). The midnight reconcile reads the workout list and the calendar, then makes 2 calls per workout (remove yesterday's entry, add today's). Plus token refreshes. Scales with workout count at midnight (recounted 2026-11-10). Each change of Hevy Trainer's next workout costs 2 more: remove one entry, add one (TJ, 2026-11-10, #25). A workout Garmin refuses costs at most 8 more calls before the first midnight, then 1 a day (F-16; TJ, 2026-11-10, #4). |
| F-4 | Each poll lists routines (`GET /v1/routines`, `pageSize` max 10, so ceil(routines/10) calls) and folders, and rebuilds only routines whose `updated_at` changed since the last sync. A missing Garmin workout is found only by the full reconcile at startup and midnight, which read Garmin's workout list. A poll also compares folder titles (a renamed folder changes workout names, F-15) and, with Trainer, the program and its templates; any difference counts as a Hevy change. The `/v1/workouts/events` cursor lives in memory and starts at the startup time (the startup full sync covers anything earlier). The events are read once per poll, first, when Trainer or last time's sets (F-30b) is on, and both are told of them; with neither on they are not read. The cursor moves only once Hevy has answered (2026-11-11, #3). Trainer preferences (`availableWeights`, unit overrides) are read at startup, at midnight, after a saved, edited or deleted workout, and at a manual sync (W-3; TJ, 2026-11-12, #31). A Trainer template that disappears is handled like a deleted routine (F-14, F-14a). |
| F-4a | Garmin is contacted only: (1) at startup, full reconcile; (2) when a poll finds a Hevy change (routine created, changed, deleted or deselected; or, with Trainer, a saved, edited or deleted Hevy workout, which can change Trainer's next weights); (3) at local midnight, full reconcile plus calendar rollover, and on the first weekday Trainer's week switch; (4) token refresh and retries of the above; (5) with Trainer, when a poll finds that the workout Hevy says is next changed, to move today's calendar entry (F-31; TJ, 2026-11-10, #25); (6) a manual sync, a full reconcile asked for from the status page, its API or the `sync` command (W-3, W-4; TJ, 2026-11-11, #31). Moving it reads no calendar: the app removes the old entry by the id it already holds and adds the new one. A poll with no Hevy change makes no Garmin call. Garmin is known to block accounts that call too often. |
| F-4b | No special handling for hand edits in Garmin Connect. A workout's contents are rewritten only when its Version hash (F-12) changes, so a hand edit stays until that routine changes in Hevy (TJ, 2026-11-07), or until a forced sync rewrites every workout (W-4; TJ, 2026-11-10, #31: "Only with a --force flag"). Calendar entries are still reconciled at startup and midnight. Do not compare Garmin's actual workout contents. |
| F-5 | Changes reach the watch on its next phone sync. Accepted. The app queues each created or changed workout for the watch (F-31a), but the watch only receives it when it syncs. |

</div>

## 3. Garmin workouts

<div class="wrap">

<table>
<colgroup>
<col style="width: 50%" />
<col style="width: 50%" />
</colgroup>
<thead>
<tr>
<th>ID</th>
<th>Requirement</th>
</tr>
</thead>
<tbody>
<tr>
<td class="id">F-10</td>
<td>Selection: every Hevy routine syncs by default. If <code>INCLUDE_HEVY_FOLDERS</code> is set, only routines in those folders. Folders are matched by id or by exact title. Routines with no folder sync only when <code>INCLUDE_HEVY_FOLDERS</code> is unset.</td>
</tr>
<tr>
<td class="id">F-11</td>
<td>On start, log every Hevy routine folder as <code>id</code> and <code>title</code> at INFO, so users can copy ids.</td>
</tr>
<tr>
<td class="id">F-12</td>
<td>Ownership: the app MUST only create, update, delete or schedule Garmin workouts it created. Ownership is stored inside each Garmin workout's description, in this exact format (TJ, 2026-11-07):<br />
<code>Synced from Hevy: https://github.com/zimmertr/hevy-garmin-sync</code><br />
<code>Last updated: 2026-11-07 17:40 PST</code><br />
<code>Hevy routine: &lt;hevy_routine_id&gt;</code> (Trainer workouts: <code>Hevy Trainer template: &lt;template_id&gt;</code>)<br />
<code>Version: 3f9c1a</code><br />
"Version" is a short hash of the workout exactly as the app built it (name, steps, notes; not the "Last updated" line), so Garmin's re-encoding (weights stored in grams, extra fields) never looks like a change. Every reconcile compares the hash of the newly built workout with this line and writes only when they differ (TJ chose the description over a file in <code>DATA_DIR</code>, 2026-11-07). A new app version that builds workouts differently changes the hash, so its first sync rewrites each workout once.<br />
A workout is the app's only when the first line matches and the id line parses. To find them the app reads Garmin's whole workout list (<code>get_workouts</code> returns at most 100 per call; page until a short page; 2026-11-10) and relies on the list carrying each workout's description (U-26). "Last updated" is when the app last wrote that workout, in <code>TZ</code>; it changes only when the workout's contents change, never on a poll with no change (F-4a). The data folder MUST NOT be the source of ownership, so losing it never causes duplicates. The marker goes in the workout's <code>description</code> (present on python-garminconnect's <code>BaseWorkout</code>); the app writes it on every create and update, so the app itself never drops it. A user who deletes the id line by hand orphans that workout: the app no longer recognizes it and creates a new one. Accepted; the README tells users not to edit these descriptions (TJ, 2026-11-07). For Trainer workouts the template line replaces the routine line. <code>Version</code> is the first 6 hex characters of a SHA-256 of the built workout; "Last updated" uses the zone's own abbreviation (PST or PDT).</td>
</tr>
<tr>
<td class="id">F-13</td>
<td>A changed routine updates its existing Garmin workout in place with python-garminconnect <code>update_workout(workout_id, json)</code> (PUT, full body, keeps the id, calendar entries stay valid; verified from its source 2026-11-07). hevy2garmin deletes and recreates instead, which broke calendar entries; do not copy that.</td>
</tr>
<tr>
<td class="id">F-14</td>
<td>A routine that is deleted, or no longer selected, has its Garmin workout deleted (and its calendar entries, F-32). On the watch it then leaves the Today prompt and the calendar at the next sync, but the copy in the watch's saved workout list stays until the user removes it there (U-25). Accepted (TJ, 2026-11-10); the README says so.</td>
</tr>
<tr>
<td class="id">F-14a</td>
<td>Never delete on a bad read (TJ, 2026-11-07). Deletions happen only after Hevy returned the complete routine and folder lists (every page) without an error. If a folder named in <code>INCLUDE_HEVY_FOLDERS</code> disappears while running (deleted or renamed), keep its routines' Garmin workouts, log ERROR naming the folder and saying to fix the setting, and keep syncing the rest. At startup an unknown folder still exits (C-3).</td>
</tr>
<tr>
<td class="id">F-15</td>
<td>Names: <code>Hevy: {routine title}</code> when the routine has no folder; <code>Hevy/{folder title}: {routine title}</code> when it does; Trainer workouts <code>Hevy/Trainer: {template name} (C{cycle}-W{week of cycle})</code>, e.g. <code>Hevy/Trainer: Upper (C2-W2)</code>. No "Deload" suffix. Watch truncation is accepted (U-3).</td>
</tr>
<tr>
<td class="id">F-15a</td>
<td>Duplicate names are allowed (two routines with the same title in one folder get the same Garmin name). No suffixes.</td>
</tr>
<tr>
<td class="id">F-15b</td>
<td>A routine with no exercises gets no Garmin workout; log at INFO why. A workout Garmin rejects is F-16.</td>
</tr>
<tr>
<td class="id">F-16</td>
<td>If Garmin rejects one workout (a 4xx about its contents, not a network or server error), log ERROR with the routine title, Garmin's reason and when it is tried next, skip it, and continue with the others. Retry it at once when that routine changes in Hevy, and start its gaps over. Otherwise retry it 5 minutes after the refusal, then at gaps that double each time, until local midnight. The full run at midnight tries it once more; refused there too, it is tried once a day, at the midnight full run. Every other full run (at startup, after a Garmin failure) also tries it, and the gap doubles as after any try. Each retry is logged at INFO. A poll with no retry due makes no Garmin call for it (F-4a). The record is in memory: a restart tries the workout at startup and starts its gaps over. So a workout Garmin always refuses costs at most 8 more calls before its first midnight, then 1 a day (TJ, 2026-11-10, #4: "expontential backoff up to midnight. Then just daily"; the 5 minute first gap was the issue's proposal; replaces "only when the routine changes, at startup and at midnight", TJ, 2026-11-07; decision record 0011). Network errors, 5xx and 429 follow O-1. Garmin may cap the number of steps in one workout: on 2026-11-11 it took one of 250 steps with no repeat group, made and deleted at once; larger was not tried. Nothing is built around that: a routine too long for Garmin is rejected like any other, and the ERROR line also gives its step count so the cause is plain (TJ, 2026-11-10).</td>
</tr>
</tbody>
</table>

</div>

## 4. Workout contents (Hevy routine to Garmin steps)

<div class="wrap">

<table>
<colgroup>
<col style="width: 33%" />
<col style="width: 33%" />
<col style="width: 33%" />
</colgroup>
<thead>
<tr>
<th>ID</th>
<th>Hevy input</th>
<th>Garmin output (MUST)</th>
</tr>
</thead>
<tbody>
<tr>
<td class="id">F-20</td>
<td>Exercise</td>
<td>Strength step(s) named by the exercise map (F-50). Exercise order preserved.</td>
</tr>
<tr>
<td class="id">F-20a</td>
<td>Back-to-back sets of one exercise with the same type, rep target (or time or distance) and weight</td>
<td>One Garmin repeat group (<code>RepeatGroupDTO</code>, <code>numberOfIterations</code> = number of sets) holding the set step and its rest step, so the watch counts SET 1/3, 2/3, 3/3. A set that differs (a warm-up, a heavier top set) gets its own step. Decided by TJ, 2026-11-07, after the watch showed SET 1/1 for a set sent as its own step. VERIFIED on TJ's Fenix 8, 2026-11-07, with a one-off script that is not in the repo: warm-up 20 lb, a repeat of 3 x 40 lb, then 8 x 45 lb counted SET 1/1, 1/3, 2/3, 3/3, 1/1; every set showed its weight; the watch asked for reps and weight after all 5, including the repeat's last round. The step list shows the group as "Repeat 3x" with the set and rest inside. Build the group with <code>create_repeat_group(n, [set, rest], order, skip_last_rest_step=False)</code>, <code>childStepId</code> 1 on the group and its children, and the pound weight fields patched in (F-21a). Read back on 2026-11-11: Garmin stores the group as a group, not flattened, with its set and rest steps inside it (<code>docs/DATA.md</code>).</td>
</tr>
<tr>
<td class="id">F-21</td>
<td>Set weight (<code>weight_kg</code>)</td>
<td>The routine's weight. Null in the routine means no weight target. With Trainer, the prescription (F-43). Weights are kilograms in both APIs; never convert through display units.</td>
</tr>
<tr>
<td class="id">F-21a</td>
<td>Weight precision</td>
<td>VERIFIED on TJ's Fenix 8, 2026-11-07: a step with <code>weightValue: 40.0</code> and <code>weightUnit {unitId: 7, unitKey: "pound"}</code> shows 40.0 lbs everywhere the watch shows a set: the workout's step list ("12 Reps - 40.0 lbs"), the set's start screen, and prefilled on the set confirm screen (Garmin stores it as 18143 grams and labels unit 7 "centimetersPerMillisecond", but displays it correctly). A step sent the python-garminconnect way (<code>weight_kg</code>, stored 18143.7 with the kilogram unit) shows 0.0 lbs: DO NOT use the library's <code>weight_kg</code> helper. Kilogram users are untested (U-17). Send each weight in the user's unit, as hevy2garmin does (<code>web/lib/garmin-workout.ts</code> <code>weightFields</code>): for pounds, <code>weightValue</code> = round(kg x 2.2046226218, 2 decimals) with <code>weightUnit {unitId: 7, unitKey: "pound"}</code>; for kilograms, <code>weightValue</code> = kg with <code>{unitId: 8, unitKey: "kilogram"}</code>. 18.1437 kg becomes 40.00 lb; 17.5 lb stays 17.5 (not whole pounds: half-pound dumbbells and plates exist). The unit comes from Garmin's profile setting <code>userData.measurementSystem</code>, which python-garminconnect reads at sign-in (<code>unit_system</code>): <code>statute_us</code> means pounds, <code>metric</code> kilograms; <code>statute_uk</code> is unconfirmed (U-14). This matches what the watch displays and works without Trainer. With Trainer, Hevy's per-exercise unit overrides decide the rounding to equipment (F-43); the value sent to Garmin is still in Garmin's unit. Build the weight fields ourselves; never through the library's helper.</td>
</tr>
<tr>
<td class="id">F-22</td>
<td>Reps or <code>rep_range {start,end}</code></td>
<td>Rep target. For a range, the top (<code>end</code>), and the full range goes in the set's note (F-30). Every set with reps also waits for the Lap press: the watch never ends one on its own (TJ, 2026-11-13). A Trainer warm-up has the working sets' rep range, as the Hevy app shows it (TJ, 2026-11-13; it carried only a weight before). A set with no rep target ends on a button press (end condition <code>lap.button</code>, <code>conditionTypeId</code> 1, verified on TJ's Fenix 8), still with its weight (TJ, 2026-11-07; U-19).</td>
</tr>
<tr>
<td class="id">F-23</td>
<td><code>rest_seconds</code></td>
<td>Timed rest step of that length after each set. When the exercise has no rest timer (null or 0), an open rest step that ends on a button press (TJ, 2026-11-07; U-20).</td>
</tr>
<tr>
<td class="id">F-24</td>
<td>Set type <code>warmup</code></td>
<td>Separate step marked as warm-up (<code>stepType {stepTypeId: 1, stepTypeKey: "warmup"}</code>), with its own weight. Garmin stores the mark (<code>stepTypeKey: "warmup"</code> read back, 2026-11-07), but the Fenix 8 never shows it: not in the exercise name, the set's start screen, or the confirm screen ("Set 1 - Side Bend"). So the step's note starts with <code>Warm Up Set</code> (F-30). A warm-up never joins a repeat group with working sets (F-20a).</td>
</tr>
<tr>
<td class="id">F-25</td>
<td>Set types <code>dropset</code>, <code>failure</code></td>
<td>Normal sets, whose note starts with <code>Drop Set</code> or <code>Failure Set</code> (F-30).</td>
</tr>
<tr>
<td class="id">F-26</td>
<td><code>superset_id</code> shared by exercises</td>
<td>Alternate per round: A set, open rest (ends on a button press, so the watch asks for A's reps and weight, F-29), B set, then rest. Repeat for each round. Back-to-back rounds that match exactly (same reps, weight and note for every exercise in the round) become one repeat group, as in F-20a; a round that differs gets its own steps (TJ, 2026-11-07). The rest after each round uses the last exercise in the round's <code>rest_seconds</code> (open rest if it has none), as Hevy starts the timer after the last exercise (TJ, 2026-11-07; Hevy's own behavior not checked in its code). The open rest between exercises inside a round is TJ's choice (2026-11-07); it is proven to bring up the prompt (U-20) but not yet seen mid-superset (U-23). Details (2026-11-10): round <em>i</em> is set <em>i</em> of each exercise in the superset, in exercise order. With three or more exercises, an open rest follows each set but the round's last, which gets the timed rest. When the exercises have different set counts, a later round holds only the exercises that still have a set, and its rest comes from the last exercise in that round. When the superset's exercises are not next to each other in the routine, the whole superset sits where its first exercise is. VERIFIED on TJ's Fenix 8, 2026-11-10 (U-23): in a repeat group of 2 rounds, the watch asked for reps and weight after the first exercise, the open rest showed "Next: Crunch 15 reps" with a timer counting up, the timed rest followed the second exercise, and rounds counted 1/2, 2/2.</td>
</tr>
<tr>
<td class="id">F-27</td>
<td>Duration or distance targets</td>
<td>Time (e.g. plank): a step with a time target (end condition <code>time</code>), plus weight if set. VERIFIED on TJ's Fenix 8, 2026-11-07: it shows the time, counts down and ends on its own, but the countdown starts the instant the previous step ends. So before every timed set, insert a wait step: a rest step ending on a button press with the note <code>Press Lap button to start 30s Plank countdown</code> (the set's duration as <code>30s</code> or <code>1m 30s</code>, and the Hevy exercise title) (TJ, 2026-11-07; how a rest step shows its note is U-22). In a repeat group the wait step is inside the group, before the set.<br />
Distance (e.g. farmer's walk, sled push): the set ends on a button press, with the distance in the set's note in Garmin's unit (the profile's measurement system, as for weights: metric <code>20 m</code>, imperial <code>22 yd</code>, F-30; TJ, 2026-11-07; Hevy's own unit setting is private-API only), plus weight if set (TJ, 2026-11-07). A set with both a time and a distance (e.g. a timed carry) uses the time target, and its note has both, as <code>0:45</code> / <code>22 yd</code>. Do NOT send a distance end condition: on the Fenix 8 it showed 20 m as "0.01mi" and, indoors, never ended on its own.<br />
When a timed exercise has no rest timer, its open rest and the wait step come back to back, so the user presses twice. Accepted (TJ, 2026-11-10).<br />
VERIFIED on TJ's Fenix 8, 2026-11-10 (U-22): the wait step opens with "Rest / Until Lap Press", its screen shows "Next: Plank 0:30" and a note icon, and the note itself is one page down, not on the main screen. The plank's 30 seconds start on the button press, but a "Plank 0:30" splash covers the first few seconds. After a timed set with no weight the watch shows its own confirm screen ("0.0 / 0.00"); the app cannot change it.</td>
</tr>
<tr>
<td class="id">F-28</td>
<td>Bodyweight exercise with added weight</td>
<td>Only the added weight; none if zero or null.</td>
</tr>
<tr>
<td class="id">F-28a</td>
<td>Assisted exercise (exercise template <code>type</code> <code>bodyweight_assisted</code>, as read on 2026-11-10, or <code>bodyweight_assisted_reps</code>, as the API reference spells it; the app takes both)</td>
<td>The assistance is sent as the set's weight, and the set's note writes it as <code>Assisted 20 lbs</code> (F-30), so the number is not read as a load (TJ, 2026-11-07).</td>
</tr>
<tr>
<td class="id">F-29</td>
<td>Every set, including the last of the workout</td>
<td>The watch MUST prompt for reps and weight after the set. hevy2garmin omits the rest step after the workout's last set (<code>endsWorkout</code>, <code>skipLastRestStep</code> in its <code>web/lib/garmin-workout.ts</code>) and the prompt was skipped on 2026-11-06. Verified fix (U-4): always put a rest step after every set, including the last; never set <code>skipLastRestStep</code>. Use the routine's rest time, or an open rest ending on a button press if it has none (F-23).</td>
</tr>
<tr>
<td class="id">F-30</td>
<td>Set notes</td>
<td>Each set step gets at most one note, written by the app in the step's <code>description</code>. VERIFIED on TJ's Fenix 8, 2026-11-07, with a one-off script that is not in the repo: a step note shows as a note icon on the step in the step list and as an extra data screen (second position) during that set; it does not show on the set's start screen, the confirm screen, or the in-workout sets list. Format, changed by TJ on 2026-11-13 after an arm day: the note shows the set the way the watch's own set-info screen does, which is otherwise reached only by opening the step list during the workout. The note is one page down from the set's main screen. Before, the note held only what the watch did not show elsewhere (the formats of 2026-11-07 and 2026-11-11), and from 2026-11-11 last time's sets (F-30b). A line break is written below as <code>/</code>, and each part gets a line of its own:<br />
1. The set type, in Hevy's words: <code>Warm Up Set</code>, <code>Normal Set</code>, <code>Failure Set</code> or <code>Drop Set</code>.<br />
2. The target, when the set has one: the reps as <code>4-6 Reps</code>, <code>6 Reps</code> or <code>1 Rep</code>; a time as the watch counts it down, <code>0:30</code>; a distance in Garmin's unit, <code>20 m</code> or <code>22 yd</code>. A set with more than one gets a line for each, in that order.<br />
3. The weight, when the set has one, in the unit it goes to Garmin in (F-21a): <code>35 lbs</code> or <code>20 kg</code>, whole unless it has a fraction, as in <code>17.5 lbs</code> or <code>1.25 kg</code> (rounded to two decimals). An assisted exercise (F-28a) gets <code>Assisted 20 lbs</code>, or <code>Assisted</code> with no weight.<br />
4. Hevy's name for the exercise, last so a long one can wrap, as <code>Hevy: Seal Row (Dumbbell)</code>: only when Garmin's name has a word Hevy's doesn't. Both names are compared as sets of words, any order, singular, with Garmin's <code>DUMBELL</code> read as dumbbell and <code>WITH</code> left out, so <code>Arnold Press</code> for <code>Arnold Press (Dumbbell)</code> and <code>Dumbbell Hammer Curl</code> for <code>Hammer Curl (Dumbbell)</code> get none. The Garmin name is its key in words (<code>CHEST_SUPPORTED_DUMBBELL_ROW</code> is Chest Supported Dumbbell Row); the watch's own spelling of a name is not known to differ.<br />
Example: <code>Warm Up Set</code> / <code>4-6 Reps</code> / <code>35 lbs</code> / <code>Hevy: Seal Row (Dumbbell)</code>. The Garmin exercise name is not in the note: the watch shows it at the start of each set.<br />
Sets only share a repeat group (F-20a) when their notes match too. Hevy's own notes (routine exercise notes, pinned exercise notes) are NOT sent: TJ chose to keep his form reminders in Hevy (2026-11-07). The app's own notes stay this short: four lines, five when a set has a time and a distance. Longer ones were checked on TJ's Fenix 8 on 2026-11-11 for #3 (<code>docs/DATA.md</code>): a line break starts a new line, a line holds 14 digits or about 16 to 17 characters of mixed text before the watch wraps it at a space, the screen shows about six lines, and it scrolls by itself through a longer note. Garmin stored a note of 110 characters whole.</td>
</tr>
<tr>
<td class="id">F-30b</td>
<td>Last time's sets</td>
<td>Removed from the notes by TJ on 2026-11-13: during a set the note should say what to do now, and the Hevy app shows history better than a watch can. Built on 2026-11-11 (#3; decision record 0015, now superseded for the notes), it listed the last session's working sets under <code>Previous (lb):</code>, which also gave matching sets differing notes no longer. Last time's sets stay on the status page (TJ, 2026-11-13): last time is the newest logged workout that holds a working set of the exercise, whichever workout it was, in the last 12 months. Source: the public API only. The first time an exercise is needed, the app reads <code>GET /v1/exercise_history/{id}</code> for the last 12 months and keeps the answer in memory, an empty one too. After that the workout events (F-4) keep it current: a saved or edited workout replaces the sets when it is the kept workout or starts no earlier, and the history is read again when the kept workout is deleted or no longer holds a working set of the exercise. When Hevy refuses one exercise's history (a 4xx), that exercise shows none, and the log says so once at WARNING. None of it reaches Garmin, so it causes no Garmin call. On by default; <code>ENABLE_PREVIOUS_VALUES=false</code> turns it off (C-12).</td>
</tr>
</tbody>
</table>

</div>

## 5. Calendar

<div class="wrap">

<table>
<colgroup>
<col style="width: 50%" />
<col style="width: 50%" />
</colgroup>
<thead>
<tr>
<th>ID</th>
<th>Requirement</th>
</tr>
</thead>
<tbody>
<tr>
<td class="id">F-30a</td>
<td>Calendar entries are on by default and can be turned off with <code>ENABLE_SCHEDULED_WORKOUTS=false</code>; workouts then exist only in the watch's workout list. When turned off, the app removes the calendar entries it owns.</td>
</tr>
<tr>
<td class="id">F-31</td>
<td>Every synced workout has one calendar entry on today's date in <code>TZ</code>, except as F-33 says. Today only, not later days as well (TJ, 2026-11-10: the app's job ends at Garmin Connect; when the watch picks the calendar up is Garmin's side). At local midnight the app removes its entries from past days (<code>unschedule_workout</code>) and adds one on the new day for each workout (<code>schedule_workout</code>); it does not move entries. The watch's strength start screen then lists them all ("Today: 2 Workouts / Dismiss / ..."); verified on a Fenix 8 on 2026-11-07 with two entries. For routines the app does not choose which workout is next. For Hevy Trainer it follows Hevy: only the workout Hevy says is next is on today (F-33), and when that changes, the poll that sees it removes the old entry and adds the new one instead of waiting for midnight. An entry whose id Garmin did not give stays until the next full run. Changed 2026-11-10 (TJ, #25): "as long as rearranging them in Hevy gets synced to Garmin Connect promptly"; record 0009. Seen on a real account on 2026-11-11 (release 0.7.0, #22): the midnight full run's first Garmin call timed out, the run was tried again a minute later, and it removed one entry and added one, for the one Hevy Trainer workout that is next (O-1). Seen again on 2026-11-11: a reorder of the Trainer workouts in the Hevy app moved <code>next_workout_index</code> from 1 to 0, and the next poll removed one entry and added one.</td>
</tr>
<tr>
<td class="id">F-31a</td>
<td>Every created or changed workout is also sent to the user's devices (Garmin's "Send to Device"), so it is always in the watch's workout picker even when the Today prompt doesn't show. This holds when <code>ENABLE_SCHEDULED_WORKOUTS=false</code> too. Evidence (TJ's Fenix 8, 2026-11-07): four workouts copied in Garmin Connect and scheduled on today did not reach the watch after repeated syncs; after Send to Device they appeared in the watch's workout picker. The calendar delivers the "Today: N Workouts" prompt and the watch's training calendar; Send to Device delivers the picker. VERIFIED 2026-11-07 on TJ's Fenix 8: <code>send_scheduled_workouts_to_devices()</code> (<code>PUT /workout-service/schedule/sendtodevices</code>) returns null and delivers nothing. <code>push_workout_to_device(workout_id)</code> (<code>POST</code> to the device-message service, payload <code>messageUrl: workout-service/workout/FIT/{id}</code>, <code>messageType: workouts</code>) delivers the workout to the watch's picker after a sync. With no <code>device_id</code> it targets the device that synced last (<code>get_device_last_used</code>). Use that, with no device setting; push after every create and update. Multi-device users get only their last-synced device; revisit if anyone asks (backlog B-2).<br />
VERIFIED in the watch session of 2026-11-10, with a one-off script that is not in the repo, and the reason both the calendar entry and the push stay (TJ, 2026-11-10): (1) a workout the app put on today's calendar, with no push, reached the watch's Today prompt and training calendar after one sync, but not its saved workout list; (2) after <code>push_workout_to_device</code> it was in the saved list; (3) changed in place and not pushed, the Today prompt and calendar showed the new version while the saved list kept the old one; (4) pushed again, the saved list held one copy with the new name, reps and weight (U-24); (5) deleted in Garmin, it left the prompt and calendar but stayed in the saved list (U-25). Garmin also keeps a calendar workout in the watch's workout library once it has been done (TJ's Runna runs are all there), so a library copy exists either way, and only the push keeps it current. So: the calendar entry is the main delivery and needs no device; the push after every create and update keeps the saved copy correct and lets a workout be started again after an interrupted session.</td>
</tr>
<tr>
<td class="id">F-32</td>
<td>At startup and at midnight the app reconciles its own entries from 31 days back through today: exactly one entry on today for each workout it owns (none for a Trainer workout F-33 holds back), and every other entry of its own in that window removed, finished or not (TJ, 2026-11-10). The app never reads whether an entry was completed; the recorded activity stays on Garmin's calendar by itself. A workout done today keeps its entry until midnight. Entries on future days are left alone. Never touch calendar entries for workouts the app doesn't own (e.g. Runna runs).</td>
</tr>
<tr>
<td class="id">F-32a</td>
<td>REMOVED 2026-11-10: the app no longer needs Garmin's completion mark (F-32, F-33).</td>
</tr>
<tr>
<td class="id">F-33</td>
<td>Trainer: every program template is a Garmin workout and a selectable workout on the watch, and only the one Hevy says is next sits on today: the template at the program's <code>next_workout_index</code>, counted in the templates' <code>index</code> order (TJ, 2026-11-10, #25). At midnight on the user's first weekday (Hevy <code>first_weekday</code>), names and contents switch to the new week. When <code>next_workout_index</code> is missing, not an integer, or names no template, the earlier rule applies, with one WARNING: this week's Trainer workouts sit on today, and once one is done this week it gets no calendar entry until the next week starts (TJ, 2026-11-07). "Done this week" comes from Hevy, not Garmin: a logged workout whose <code>trainer_workout_template_id</code> matches and whose <code>start_time</code> falls in the current program week, from the history F-42 already reads (TJ, 2026-11-10). Changed 2026-11-10 (TJ, #25): one Trainer workout is now always on today, where the earlier rule showed none once the week's workouts were all logged.</td>
</tr>
</tbody>
</table>

</div>

## 6. Hevy Trainer (runs whenever `HEVY_SESSION` is set)

Trainer's program is not in Hevy's public API; only the private API the Hevy app uses has it. TJ decided (2026-11-07) to use it and not to disable it by default. There is no on/off setting: Trainer syncs whenever `HEVY_SESSION` is provided. Only the environment variable counts: when it is unset, Trainer is off even if `DATA_DIR` still holds a Hevy session, and the app deletes the Trainer workouts it owns and that stored session (TJ, 2026-11-10). If the account has no Trainer program, log that at INFO and sync routines as usual. The README states that Trainer uses Hevy's private API, which Hevy may change or object to (Hevy's terms allow suspending accounts for "unauthorized, or suspected unauthorized use").

Hevy's servers do not send Trainer's prescribed weights, warm-up weights or cycle/week; the Hevy app computes them on the phone. The app MUST compute them with the same rules. Reference implementation: `zimmertr/hevy-trainer-sync` `src/hevy_trainer_sync/trainer_rules.py`, `build.py` (`plan`, `plan_exercise`), `library.py`, `docs/DATA.md`, decision record 0042. Reference only: write fresh code (D-5), but match its behavior exactly, including everything the rows below don't state (0 or 3+ warm-ups, barbell plate combinations, dumbbell pairs, ties when rounding to the nearest weight, where the current rep-ladder rung comes from, the week of a past workout when excluding deload weeks, how far back to read history). It was validated against the app on 2026-11-06 and 2026-11-07 (Side Bend 35 to 40 lb, Lying Leg Raise to 15-20 reps, Goblet Squat warm-ups 30 and 50 lb).

<div class="wrap">

| ID | Requirement |
|----|----|
| F-40 | Trainer and plain routines sync together. Exercise type and equipment for the rules come from Hevy's public `GET /v1/exercise_templates` (`type`, `equipment`), not from a copy of the app's library. |
| F-41 | Week: `calendar_week` = whole weeks from the start of the week containing the program's `created_at` to the start of the current week, plus 1, with weeks starting on `first_weekday` in local time. Cycle length 6, or 7 when `deloads_enabled`. cycle = floor((week-1)/n)+1, week of cycle = (week-1)%n+1, deload week = week of cycle \> 6. |
| F-42 | History: the user's workouts whose `trainer_workout_template_id` matches the template and that contain the exercise, excluding deload weeks, sorted by time; the last one is the previous log. |
| F-43 | Weight: base = lightest normal set of the previous log. Fewer sets than the target: no change. Every set at or above the range end: x1.05. Every set below the range start: x0.95. Otherwise no change. Round to equipment the user owns (Trainer preferences `availableWeights`): machines in 2.5 kg or 5 lb steps (up = ceil, down = floor), dumbbells from the user's list counted as pairs, barbell from bars plus plate combinations. Deload week: 0.6x, nearest. |
| F-44 | Warm-ups: 1 warm-up = 60%; 2 warm-ups = 40% and 60%; rounded to the nearest available weight. |
| F-45 | Reps-only exercises move up or down the ladder 4-6, 6-8, 8-12, 12-15, 15-20, 20-25, 25-30 by the same all-sets rule. |
| F-46 | New exercise (no previous log in that template, e.g. after a rotation): match the app's starting weight (TJ approved 2026-11-07). Take the exercise's best estimated one-rep max (`best_1rm`) across all the user's workouts over the last 3 months, else the last 12 months. Per set, the estimate is weight / factor\[reps\] from a constant table for 1 to 30 reps (factor 0.5 above 30; 0 reps gives nothing). The starting weight is that one-rep max times a constant percentage for the target rep range, rounded to the user's equipment (F-43); warm-ups follow F-44. No one-rep max in 12 months: no weight (blank), as in the app. The factor table, the rep-range percentages and the exact window definitions go into `docs/HEVY_TRAINER_RULES.md` during the build (D-7b). Needs the exercise's sets for the last 12 months: one call to the public `GET /v1/exercise_history/{exerciseTemplateId}` with `start_date` and `end_date`, made only when such an exercise exists and cached in memory (TJ, 2026-11-10; replaces reading every workout through the private API, about 50 calls). |
| F-46a | No prescription for other reasons (exercise type or equipment the app gives no suggestion for, e.g. distance or time types): no weight, logged at INFO. Confirmed by TJ on 2026-11-10 after the first run against his account: such an exercise (his Walking Lunge (Dumbbell), a `short_distance_weight` type) stays without a weight; the app does not fill in the last logged weight, as hevy-trainer-sync did. A kettlebell or other equipment outside machine, dumbbell and barbell follows whatever the app does; confirm in the app's code. |
| F-47 | Weights change only after a logged session, not at week rollover (matches the app). Exception: the deload multiplier (F-43) follows the week, so entering and leaving a deload week changes weights at the week switch. |
| F-48 | Every Hevy app release, patches included, is checked for changes to these rules, outside this repo (D-7b). A weekly job opens the check when the App Store has a new version. A changed rule comes back here as an issue that states the new rule. 8 of the 29 releases from 3.0.8 to 3.2.7 changed a rule, 7 of them patches, and their release notes named 1. None changed from 3.2.5 to 3.2.7 (TJ, 2026-11-13; record 0018). Before, nothing checked, and a difference between the watch and the app was the only sign (decision record 0043 in hevy-trainer-sync). |

</div>

## 7. Exercise map

<div class="wrap">

| ID | Requirement |
|----|----|
| F-49 | The order workouts appear on the watch is whatever Garmin does. Do not build ordering logic. |
| F-50 | A static CSV file (confirmed by TJ 2026-11-07), read with Python's `csv` module, one row per exercise mapping every Hevy built-in exercise template id (451 in Hevy app 3.2.5; the ids and titles were checked against Hevy's own list on 2026-11-10, read once after asking TJ, keeping rows where `is_custom` is false; the map keeps four more ids Hevy no longer lists) to one Garmin exercise (Garmin Connect's category key plus exercise key, e.g. `BENCH_PRESS` and `BARBELL_BENCH_PRESS`). Columns: Hevy id, Hevy title, Garmin category, Garmin name, observed Strava name (empty until seen), observed date. |
| F-51 | Seed from hevy2garmin's `HEVY_TO_GARMIN` in `typescript/src/exercise-map.ts` (MIT; credit in the README and file header). Garmin's exercise list is Garmin Connect's own, published without sign-in at `https://connect.garmin.com/web-data/exercises/Exercises.json` (categories, each with its exercises; checked 2026-11-10), not the FIT SDK profile. The repo keeps a list of that file's category and exercise keys, and a test fails when a row of either map (F-50, F-53) names a pair that is not in it (TJ, 2026-11-10). The list ships in the image, in `src/hevy_garmin_sync/data/garmin_exercises.json`, so the app refuses a `CUSTOM_EXERCISE_MAP` pair that is not in it at startup (C-11; TJ, 2026-11-10, #24). A weekly check compares that list with Garmin's file, and on a difference opens one issue and one PR that updates the list (TJ, 2026-11-10, #26). Choose the closest movement and equipment for every row up front; known wrong rows: Upright Row (Dumbbell) showed as "Barbell Upright Row" on Strava; Pullover (Dumbbell) as "Straight Arm Pulldown". |
| F-51a | Review before the first version (TJ, 2026-11-07): the building agent fills every row; a second agent checks every row independently against Garmin's list (F-51) and flags doubtful matches; TJ reviews only the exercises he uses (those in his routines and Trainer program). Record unresolved doubts in the PR body. |
| F-52 | The Strava column is filled only from real sessions (Strava publishes no list). |
| F-53 | Custom Hevy exercises (`is_custom`, not in the map) are mapped by `primary_muscle_group` and `equipment` from `GET /v1/exercise_templates` to a Garmin exercise, via a second small table keyed by those two values. `CUSTOM_EXERCISE_MAP` (C-11) wins over that table. Each custom exercise in a synced routine or Trainer workout logs one INFO line naming its Hevy title, muscle group and equipment, the Garmin category and exercise it got, and whether the variable or the table chose it; once per exercise, and again when the choice changes (TJ, 2026-11-10, #24). A step with a `stepName` and no exercise, as hevy2garmin sent for an exercise it couldn't match, is no way to show a Hevy title: on 2026-11-10 Garmin accepted one with category `CORE`, stored `CORE` with no exercise name, kept no `stepName`, and the Fenix 8 showed "Core" (#24). So no fallback row uses `stepName`. |
| F-54 | Fixes to the shipped tables go into the repo. The one per-user override is `CUSTOM_EXERCISE_MAP` (C-11), for custom exercises only: a custom exercise's id belongs to one Hevy account, so no shipped row can hold it. An entry that names a built-in exercise is ignored, with one WARNING when that exercise is seen, since whether a title is built-in is known only once Hevy's templates are read; a wrong built-in is fixed in `exercise_map.csv` (TJ, 2026-11-10, #24). |
| F-55 | A built-in Hevy exercise missing from the map (e.g. added by Hevy later) uses the F-53 fallback and logs a WARNING naming the exercise and asking the user to report it, so the map gets a proper row. |

</div>

## 8. Authentication

<div class="wrap">

| ID | Requirement |
|----|----|
| A-1 | Plain routines use the Hevy public API key (`HEVY_API_KEY`, static, from Hevy settings, requires Hevy Pro). Free Hevy accounts are not supported: plain routines never come from the private API (TJ, 2026-11-07). |
| A-2 | Garmin: a one-off command `docker run --rm -it <image> login`, run on the user's own machine. It prompts for email, password and a 2FA code if requested, signs in through python-garminconnect, and prints one opaque value for `GARMIN_TOKEN` (the library's token data, encoded as one string; U-12). The password is used once and never written anywhere. |
| A-2a | Garmin client: depend on python-garminconnect (MIT, `cyberjunky/python-garminconnect`), pinned to an exact version (0.3.20 or later as of 2026-11-07). It implements Garmin's current DI OAuth sign-in (after Garmin's March 2026 change broke `garth`, which is deprecated), MFA, token refresh, workouts (`upload_workout`, `update_workout`, `delete_workout`, `get_workouts`), strength step models (`category`, `exerciseName`; its own `weight_kg` helper writes grams with the kilogram unit, which the watch shows as 0.0, so patch the weight fields per F-21a) and scheduling (`schedule_workout`, `unschedule_workout`, `get_scheduled_workouts_by_period`). Do not write our own Garmin sign-in. |
| A-3 | Hevy (Trainer only): no command. Hevy's password sign-in is behind reCAPTCHA (the hevy-unofficial client says the same of the web), so programmatic sign-in is not possible without a hack. The README shows how to copy the hevy.com `auth2.0-token` cookie into `HEVY_SESSION`. This works for every sign-in method, Apple and Google included (U-5). The README tells users to copy the cookie from a private browser window and then close that window without logging out: the app rotates the refresh token, so a browser left signed in on the same session and the app would each end the other's session (2026-11-10). The Hevy phone app has its own session and is not affected. |
| A-4 | The env var seeds the first start. The app then stores the current tokens in `DATA_DIR`, together with a hash of the env value it started from, and prefers the stored copy. When `GARMIN_TOKEN` or `HEVY_SESSION` changes (its hash differs from the stored one), the new env value replaces the stored copy: that is how a user recovers by running `login` again (TJ, 2026-11-07). Required because both services rotate refresh tokens: Garmin per the garmin-auth README ("Garmin rotates the refresh token each time, so an unsaved one stops working", checked 2026-11-07); Hevy per hevy-trainer-sync `docs/DATA.md` (2026-11-04). |
| A-5 | Token writes MUST be atomic (write then rename) and file mode 0600, so a crash never leaves a half-written token. |
| A-6 | MUST NOT log tokens, cookies, passwords or the user's email. |
| A-7 | Garmin may block sign-ins from cloud IPs (garmin-auth README); home connections usually work. `login` tells cloud users to run it from home when a sign-in fails, and so does `docs/USAGE.md` (TJ, 2026-11-13, #40). The README tells every user to run exactly one copy of the app per Garmin account: two copies refresh the same rotating token and one of them gets locked out. |

</div>

## 9. Unverified assumptions (resolve before depending on them)

<div class="wrap">

| ID | Assumption | How to verify | If false |
|----|----|----|----|
| U-1 | RESOLVED 2026-11-07: python-garminconnect `update_workout` replaces a workout in place and keeps its id. | Confirm with the first live sync. |  |
| U-2 | RESOLVED 2026-11-07: workouts have a `description` field; the app rewrites the marker on every update. | Confirm a strength workout's description round-trips on the first live sync. | Ask TJ; fall back to a list in `DATA_DIR`. |
| U-3 | RESOLVED 2026-11-07: Garmin Connect keeps a 49-character name in full; the Fenix 8 shows about the first 30 characters ("Hevy/Push Pull Legs: Full Body"). Trainer names ("Hevy/Trainer: Upper (C2-W2)", 27) fit; long folder names push the routine title past the cut. Accepted unless TJ says otherwise. |  |  |
| U-4 | RESOLVED 2026-11-07: with a rest step after the final set, the Fenix 8 shows the reps and weight confirm after that set, then "Workout Complete". Always end every set, including the last, with a rest step. |  |  |
| U-18 | RESOLVED 2026-11-07: a mix of single set steps and repeat groups counts, weighs and prompts correctly on the Fenix 8 (F-20a). |  |  |
| U-19 | RESOLVED 2026-11-07, with a one-off script that is not in the repo: a set ending on a button press waits for the press, shows its weight, and is followed by the reps and weight screen with that weight. |  |  |
| U-20 | RESOLVED 2026-11-07: an open rest waits for a button press, and the reps and weight screen still appears after the set before it. |  |  |
| U-21 | RESOLVED 2026-11-07: Garmin accepts time and distance end conditions on strength steps. Timed sets work but start counting at once; distance targets are useless indoors. Handled in F-27. |  |  |
| U-22 | RESOLVED 2026-11-10: a note on a rest step is not on the rest screen itself. The screen shows "Next: Plank 0:30" and a note icon; the note is one page down (F-27). |  |  |
| U-23 | RESOLVED 2026-11-10: an open rest between the exercises of a superset round brings up the reps and weight prompt for the first exercise, and the round reads clearly (F-26). |  |  |
| U-24 | RESOLVED 2026-11-10: a workout already on the watch, changed with `update_workout` (a freshly built body, same id) and sent again with `push_workout_to_device`, shows as one copy with the new name, reps and weight. Without the push the saved copy stays old, while the Today prompt and calendar show the new version (F-31a). This also confirms U-1 live. Seen again with the built code on 2026-11-10: after an update and a push the watch held one copy, with the new name and the changed weight (45.0 to 50.0 lbs). |  |  |
| U-25 | RESOLVED 2026-11-10: a workout deleted in Garmin Connect leaves the watch's Today prompt and calendar at the next sync, but stays in its saved workout list. A test workout deleted on 2026-11-07 was still there three days later. No remote removal is known. Handled in F-14. |  |  |
| U-26 | RESOLVED 2026-11-10: every item of `get_workouts` carries `description` (also `workoutId`, `workoutName`, `updateDate`), so finding the app's workouts costs one call per 100 workouts (F-12). |  |  |
| U-17 | Kilogram users: hevy2garmin sends `weightValue` = the kilogram number with `{unitId: 8, unitKey: "kilogram"}`. RESOLVED on TJ's Fenix 8, 2026-11-10 (#5): with Garmin Connect set to metric the app sent 20 and 22.5 kilograms; the watch, still in pounds, showed 44.1 and 49.6 lbs, and 20 and 22.5 kg once the watch itself was set to kilograms. The unit to send is Garmin Connect's; the watch's weight unit is a separate setting on the watch. | Ask a kilogram user, or temporarily switch a watch to metric, during the build. | Investigate. |
| U-5 | The hevy.com cookie is the same after Apple or Google sign-in. | Ask a user with such an account, or TJ if applicable. | Document the limitation. |
| U-6 | RESOLVED 2026-11-07: no usable programmatic Hevy sign-in (reCAPTCHA). Cookie only (A-3). |  |  |
| U-7 | RESOLVED 2026-11-07: use python-garminconnect (A-2a). |  |  |
| U-8 | RESOLVED 2026-11-07 from the API spec: routine sets have `type` (`warmup`, `normal`, `failure`, `dropset`), `weight_kg`, `reps`, `rep_range {start,end}`, `distance_meters`, `duration_seconds`; exercises have `superset_id`, `rest_seconds`, `notes`; templates have `type`, `equipment`, `primary_muscle_group`, `is_custom`. | Confirm against a live response. |  |
| U-9 | Polling every 60 s is acceptable to Hevy. No published limit; the spec only asks that hourly or daily jobs avoid minute :00. Cost is ceil(routines/10) + ceil(folders/10) calls per poll. | Log call counts per poll at DEBUG. | 60 s is the default (TJ, F-3a). On 429, back off per O-1. |
| U-13 | DROPPED 2026-11-10: the app no longer reads whether a calendar entry was completed (F-32); Trainer's "done this week" comes from Hevy (F-33). For the record, a schedule entry carries `associatedActivityId` and `associatedActivityDateTime` (seen 2026-11-10), which is where Garmin links the activity. |  |  |
| U-14 | Which weight unit Garmin's `statute_uk` setting implies. | Garmin Connect's settings page or python-garminconnect docs. | Treat as kilograms. |
| U-15 | RESOLVED 2026-11-11: per-exercise unit overrides come from the private API `GET /exercise_template_units` (the app also writes them, which we never do; 2026-11-07). On 2026-11-10 it answered with an empty list for TJ's account, which logs no exercise in the other unit. On 2026-11-11, with one exercise set to kilograms, a row was `{id, exercise_template_id, weight_unit}` (`id` an integer), and after a restart the app gave that exercise 20 kg, the number the Hevy app showed. The units are read only at startup, at midnight and after a workout event (F-4), so the change waited for the restart (#31). | Log the response shape (values hidden) on the first live run. | Use the account unit; ask TJ. |
| U-12 | RESOLVED 2026-11-07: python-garminconnect's token object (`garminconnect/client/tokens.py`) has `dumps()` (JSON string with the DI tokens), `loads(str)`, and an atomic `dump(path)`/`load(path)`. `login` prints `dumps()` (base64-encode it so it is one shell-safe line); the app decodes and `loads()` it on first start, then uses the file in `DATA_DIR`. It refreshes when the access token's JWT expiry is near. |  |  |
| U-10 | How the watch's Today prompt behaves with many workouts on one day. Inconclusive 2026-11-07: with 6 strength workouts scheduled on today, the prompt first listed only the 2 delivered earlier, then stopped appearing after several syncs (possibly because it had been dismissed once that day); the training calendar listed only those 2. F-31a makes every workout selectable regardless. On 2026-11-10 one workout the app's test put on today reached the prompt and the watch's calendar after one sync. Later on 2026-11-10 (#6), with eight check workouts added to today that evening, the prompt listed all eight under "Dismiss" (HGS check names, HGS check 1 to 5, HGS check step name, HGS check 6) and, dismissed once, came back at the next strength start. Garmin Connect's calendar also had the app's Hevy Trainer workout on today, the one Hevy says is next (the other, recorded on the watch earlier that day, was off the calendar as F-33 intends), but the prompt did not list it. That entry was on today before a strength activity was recorded that day; the eight were added afterwards. On 2026-11-11, before any activity was recorded that day, the prompt listed that Trainer workout (TJ). So the prompt offers the next Trainer workout on a day without a recorded activity, and the one time it was missing was after one had been recorded. Tested on 2026-11-11: after an activity recorded from one of today's workouts was saved, the prompt at the next strength start listed today's other workouts and not the one just done, which stayed in the watch's saved list. The workout missing on 2026-11-10 had not been done, so that one miss stays unexplained. File as an issue once the repo exists (TJ, 2026-11-07). | Re-test during the build with workouts the app creates and sends. | Ask TJ. |
| U-16 | RESOLVED 2026-11-07: `push_workout_to_device` works; `send_scheduled_workouts_to_devices` does not (F-31a). |  |  |
| U-11 | RESOLVED 2026-11-07: calendar entries can be turned off (F-30a). |  |  |

</div>

## 10. Known API facts (verified unless marked)

### Hevy private API (Trainer only)

- Base `https://api.hevyapp.com`; headers `x-api-key: shelobs_hevy_web` and `Authorization: Bearer <access_token>`. Undocumented, no published limits.
- Cookie `auth2.0-token`: URL-encoded JSON `{access_token, refresh_token, expires_at}`. Access token lasts about 30 minutes.
- `POST /auth/refresh_token {"refresh_token": ...}` needs the old (even expired) access token in `Authorization`, else 400. The refresh token rotates on every refresh.
- `GET /hevy_trainer/v3/program`: `{program, status}`. Program has `created_at`, `deloads_enabled`, `weekly_frequency`, `templates[]` (each with `id`, `key`, `index`, `name`, `exercises[]` with `exercise_template_id`, `kind`, `set_count`, `warmup_set_count`, `rep_range`, `rest_seconds`). No weights. `current_week` is not the app's week; ignore it.
- `GET /hevy_trainer/user_preferences`: `availableWeights` (`dumbbellsLbs`, `dumbbellsKg`, `barsLbs`, `barsKg`, `platesLbs`, `platesKg`; lists may be unordered).
- `GET /v2/user_preferences`: `username`, `weight_unit`, `first_weekday`.
- `GET /user_workouts_paged?username=&limit=&offset=`: `limit=10` returns 400 with an empty body; `limit=3` works (2026-11-07). Workouts carry `trainer_workout_template_id` and `start_time`; sets carry `indicator`, `reps`, `weight_kg`.

### Hevy public API (from the API spec, U-8)

- Base `https://api.hevyapp.com/v1`, header `api-key`. Routines, routine folders, exercise templates, workouts. Routines and folders: `pageSize` max 10; exercise templates max 100 (from the API spec). `GET /v1/exercise_history/{exerciseTemplateId}` takes `start_date` and `end_date` (F-46).

### Garmin Connect (unofficial)

- Sign-in and refresh: see garmin-auth `typescript/src/client.ts` (`refreshDiToken`: `grant_type=refresh_token`, client id as basic auth, new `refresh_token` returned and must be saved).
- Workout JSON, strength steps, repeat groups and scheduling: see hevy2garmin `web/lib/garmin-workout.ts` and its calendar code. Treat as a reference with known faults (F-13, F-29).

## 11. Configuration (environment variables only)

<div class="wrap">

| ID | Variable | Default | Rule |
|----|----|----|----|
| C-1 | `HEVY_API_KEY` | required | A-1 |
| C-2 | `GARMIN_TOKEN` | required if `DATA_DIR` holds no Garmin token | A-2, A-4 |
| C-3 | `INCLUDE_HEVY_FOLDERS` | unset = all routines | Comma-separated folder ids or titles; an id is tried before a title. An empty value counts as unset. Does not apply to Trainer workouts (section 6). Unknown folder: log the folder list (F-11) first, then exit at startup. |
| C-4 | `ENABLE_SCHEDULED_WORKOUTS` | `true` | F-30a |
| C-5 | `HEVY_SESSION` | unset = no Trainer | The hevy.com `auth2.0-token` cookie. Setting it turns Trainer on; unsetting it turns Trainer off and removes its workouts (section 6). Seeds the stored session, and replaces it when the value changes (A-4). |
| C-6 | `HEVY_POLL_INTERVAL_SECONDS` | `60` | F-1. A whole number of seconds, 10 or more; anything else exits at startup (TJ, 2026-11-10). |
| C-7 | `TZ` | the Garmin profile's time zone | "Today", midnight rollover, Trainer week start, "Last updated" (F-12). Unset: read the time zone from the Garmin profile at startup; if that fails, UTC with a WARNING. The user settings reply holds no time zone (its shape, recorded 2026-11-10): python-garminconnect's `get_user_timezone` reads it from the personal-information endpoint, by the profile's display name. The startup log says which zone is used and where it came from (TJ, 2026-11-07). |
| C-8 | `DATA_DIR` | `/data` in the image | Token storage only |
| C-9 | `LOG_LEVEL` | `INFO` | O-3 |
| C-10 | `LOG_FORMAT` | `text` | `text` or `json` |
| C-11 | `CUSTOM_EXERCISE_MAP` | unset = custom exercises by muscle group and equipment (F-53) | Comma-separated `title-or-id=CATEGORY/NAME` entries, such as `My Cable Raise=LATERAL_RAISE/CABLE_FRONT_RAISE`, setting a custom exercise's Garmin exercise (F-54). An entry is tried as the exercise template id before the title. Titles match exactly, case included, after trimming spaces, as in C-3. Each entry splits on its last `=`, so a title may hold `=`; a title holding a comma goes by its id. An empty value counts as unset. Exits at startup naming the entry for one with no `=`, an empty side, a pair not written `CATEGORY/NAME`, or an exercise named twice, and naming the pair for one Garmin doesn't have (F-51). An entry that matches no exercise is not an error. The startup log shows set with a count, never the entries: they are a user's own titles (TJ, 2026-11-10, #24). |
| C-12 | `ENABLE_PREVIOUS_VALUES` | `true` | F-30b. `true` or `false`; anything else exits at startup. Since 2026-11-13 it governs the status page's line of last time's sets only. `false` reads no exercise history and, without Trainer, no workout events (TJ, 2026-11-11, #3: "toggleable by variable is a nice touch"). |
| C-13 | `HTTP_PORT` | `8080` | W-1. The port the status page and its API listen on, on every interface. A whole number from 1 to 65535; anything else exits at startup. Never named `HEVY_GARMIN_SYNC_PORT`: Kubernetes sets that variable in every pod of a namespace holding a Service called `hevy-garmin-sync` (TJ, 2026-11-12, #31). |
| C-14 | `PREVIEW_PR` | unset = the live app | W-10. A pull request's number. Set, the app runs on made-up accounts and ignores `HEVY_API_KEY`, `GARMIN_TOKEN` and `HEVY_SESSION`, which are then not required. Anything but digits exits at startup. The startup log shows each credential as ignored (TJ, 2026-11-12, #62). |
| C-15 | `PREVIEW_COMMIT` | unset | W-10. The commit a preview runs, shown in its banner by its first 7 characters. Hex digits only; anything else exits at startup. Read only with `PREVIEW_PR`. |

</div>

At startup the app makes one call each to check `HEVY_API_KEY` (and Garmin's token, and `HEVY_SESSION` if set). A rejected Hevy API key, Garmin token or `HEVY_SESSION`, at startup or later, does not exit: the app stops calling that service and says so, with the fix (e.g. run `login` again), on the status page and in the log (W-8; TJ, 2026-11-12, #31). Until then a rejection exited non-zero like bad configuration (TJ, 2026-11-07 and 2026-11-10, #23). Unreachable services or 5xx at startup are not rejections; they follow O-1.

Invalid or missing configuration MUST exit non-zero at startup with a message naming the variable and the fix. Transient failures MUST NOT exit (O-1).

## 12. Operations

<div class="wrap">

| ID | Requirement |
|----|----|
| O-1 | Hevy or Garmin unreachable, 5xx or 429: keep running, retry with backoff, log at ERROR what failed and how to fix it. Recover automatically when the cause is fixed. A rejected `HEVY_API_KEY`, `GARMIN_TOKEN` or `HEVY_SESSION` is not waited out: on the first rejection, at startup or while running, the app logs one ERROR line naming the service and the fix (e.g. "run login again and set GARMIN_TOKEN") and stops calling that service; the rest keeps running (W-8). Until 2026-11-12 it exited 1 instead (TJ, 2026-11-10, #23), and each restart tried the dead token again (TJ, 2026-11-12, #31). The app adds no retry of its own: Hevy's private client refreshes the session and tries once more before it reports a rejection, and python-garminconnect refreshes Garmin's token by itself. Backoff (TJ, 2026-11-10): the first retry after 1 minute, doubling, capped at 30 minutes; after a Garmin 429 the first wait is 15 minutes. A 429 whose `Retry-After` says how long to wait, in seconds or as an HTTP date, is waited that long instead, even past the 30 minute cap, but never less than `HEVY_POLL_INTERVAL_SECONDS`; a missing value, or one that is neither, leaves the waits above. The log line says how long the app waits and that the service asked for it (TJ, 2026-11-10, #27: the service's wait wins; decision record 0011). python-garminconnect 0.3.20 hands the app Garmin's reply for a 429 on a read or a write, but not for one on its token exchange, which keeps the 15 minutes (`docs/DATA.md`). Each service backs off by itself: Hevy polling continues while Garmin is down, and the first Garmin call that succeeds is followed by a full reconcile. python-garminconnect retries 3 times by itself; create its client with `retry_attempts=0` so only the app retries. |
| O-1a | Every outbound call has a timeout of 30 seconds (TJ, 2026-11-10). Logs are the only signal (O-2), so a call that hangs would stop the app without a word. Confirm python-garminconnect sets one on its own calls; if it does not, set it on its HTTP session. |
| O-1b | At least 1 second between Garmin writes (create, update, delete, schedule, unschedule, push), so a first sync of many routines is not a burst (TJ, 2026-11-10; F-4a). |
| O-2 | The log, the status page (W-2) and the health checks (W-7) are the signals. No HEALTHCHECK in the image or in `compose.yaml` (Compose marks a container unhealthy but doesn't restart it), and no notifications (TJ, 2026-11-12, #31; until then logs were the only signal, TJ, 2026-11-10). |
| O-3 | Python standard `logging`; every line has an ISO timestamp, level and logger name. JSON lines when `LOG_FORMAT=json`. Each sync logs one summary line (created, updated, deleted, scheduled, failed counts) at INFO; per-workout detail at DEBUG; Trainer prescriptions per exercise at INFO. When an hour passes with no change, one INFO line says how many polls ran and that nothing changed, so an idle app and a stuck one look different (TJ, 2026-11-10). |
| O-3a | Chaos tolerance (TJ, 2026-11-07): the app must survive being killed at any instant (pod eviction, SIGKILL, power loss, a laptop shutting down). Every file write is write-temp, fsync, rename. Every sync is idempotent, so a half-finished one is completed by the next. Save a refreshed token immediately after Garmin or Hevy returns it. On SIGTERM or SIGINT, start no new write, finish the one in progress, and exit 0; the next start completes the sync. Known limit: a kill in the instant between a token refresh and its save loses the session (both services kill the old refresh token), requiring `login` again; document it. |
| O-3b | Midnight uses `zoneinfo` with `TZ` and handles daylight-saving changes. After a sleep or a missed midnight (process stopped), the next startup's full reconcile catches up. |
| O-3c | At startup, log the effective configuration at INFO with secrets redacted, plus the app version. |
| O-4 | Base image `python:3.15-slim` (TJ, 2026-11-12; `python:3.14-slim` before that, from 2026-11-07). The image runs as uid/gid 1000 (non-root) and writes only to `DATA_DIR`; `compose.yaml` and the Helm chart (`fsGroup: 1000`) make the volume writable by that user. A read-only root filesystem is the default, in the chart (`readOnlyRootFilesystem: true`) and in `compose.yaml` (`read_only: true`), so a write outside `DATA_DIR` fails at once; nothing needs a writable `/tmp` (TJ, 2026-11-10, #30; record 0008). |

</div>

## 12a. Status page and manual sync

Added 2026-11-12 (TJ, #31; decision record 0016). The approved mockup is linked from #31.

<div class="wrap">

| ID | Requirement |
|----|----|
| W-1 | One port, `HTTP_PORT` (C-13), on every interface (`0.0.0.0`), served by the standard library's threading HTTP server on a second thread of the one process. It serves `GET /` (the page and its own files), `GET /api/status`, `GET /api/logs`, `POST /api/sync`, `GET /healthz` and `GET /readyz`. The wrong method is refused with 405. No sign-in: anyone who can reach the port sees the page and can start a sync (TJ, 2026-11-11: "That's fine, it's just me."). A `POST` whose `Origin` names another host than its `Host` is refused with 403, so a page on another site can't start a sync from the user's browser; one with no `Origin` (the `sync` command, curl) is allowed. The server thread reads what the loop published and asks for a sync; it never calls Hevy or Garmin (A-7). `compose.yaml` publishes the port on `127.0.0.1` only. |
| W-2 | The page: plain HTML, CSS and JavaScript files in the image, with no framework, no build step and nothing loaded from elsewhere, so it works with no internet; the font (Barlow, SIL Open Font License) and the icon ship in the image. Every reply carries a Content-Security-Policy of `default-src 'self'`, with no inline script or style. It polls `GET /api/status`: the version, each service's state, the run in progress, the last and next daily run, and every workout the app syncs with its schedule, its Garmin state, its links and its exercises (each with the Garmin exercise it got and what chose it: the exercise map, `CUSTOM_EXERCISE_MAP` or the closest match, its sets, rest, weight, and with Hevy Trainer its direction and warm-ups, with F-30b last time's sets). Links: `https://hevy.com/routine/<id>` for a routine and `https://connect.garmin.com/app/workout/<id>?workoutType=strength_training`; a Hevy Trainer workout has no page on hevy.com. "Synced" is the workout's "Last updated" (F-12), so it survives a restart. Every time is one format in `TZ`. The page changes no setting (#57). |
| W-3 | A manual sync is asked for by Sync now on the page, `POST /api/sync`, or `sync` (which calls the API on `127.0.0.1`, as the image has no curl). All three go through one function, so one limit covers them: a request while a manual sync waits or runs joins it; one within 60 seconds of the last manual sync's end is refused with HTTP 429 and the seconds left (`Retry-After`); otherwise it ends the loop's wait for the next poll at once. A wait after a Garmin failure or rate limit is never cut short: the sync runs when it ends, and the page says so (O-1). The time is in memory; a restart clears it. The run is a full reconcile (F-4a): it retries every refused workout (F-16), sends every workout the app owns to the watch again (F-31a), and with Trainer reads its preferences and logged workouts again. It leaves each exercise's last logged sets alone: the workout events keep them current (F-30b). Logged at INFO as "Manual sync asked for", then the usual summary line. |
| W-4 | A forced sync (Force sync, `force=true`, `sync --force`) is a manual sync that also rewrites every owned workout in place, ignoring its `Version` (F-12), so each keeps its Garmin id and its calendar entry; it undoes hand edits in Garmin Connect (F-4b). It also drops each exercise's last logged sets, so each is read from Hevy again. A Force pressed while a manual sync waits to start makes that sync forced; one pressed once it runs joins it as it is. |
| W-5 | "Report this match" on an exercise whose Garmin exercise was the closest match opens the repo's `exercise-match.yml` issue form with both exercises filled in. The repo keeps its own `.github/ISSUE_TEMPLATE/`, with copies of yggdrasil's shared `bug.md`, `proposal.md` and `config.yml`, because GitHub serves a repo its own folder or the shared defaults, never both (TJ, 2026-11-12; zimmertr/yggdrasil record 0058). |
| W-6 | The log is kept in memory, the last 5,000 lines, each numbered. `GET /api/logs` returns up to 200 of the newest, or of those before a line number (`before`), with whether older lines are kept. No log file: Docker and Kubernetes keep the full log. |
| W-7 | `GET /healthz` is 200 while the loop is passing or waiting as planned, and 503 once it has stopped: the loop notes a deadline before each wait (the wait plus 2 minutes) and at each pass (15 minutes). A wait after a failure counts as alive, so the liveness probe never turns an outage into restarts, each of which would sign in to Garmin again. `GET /readyz` is 503 while any sign-in is rejected (W-8). The chart's liveness probe reads `/healthz` and its readiness probe `/readyz`; its Service sets `publishNotReadyAddresses`, so the page stays reachable while the pod is unready. |
| W-8 | A rejected sign-in degrades its service instead of exiting (O-1): the app stops calling it, and the page, the log and `/readyz` say so, with the fix. A rejected `HEVY_SESSION` stops only Hevy Trainer, whose Garmin workouts stay as they are; a rejected `GARMIN_TOKEN` stops every Garmin call; a rejected `HEVY_API_KEY` stops reading Hevy. Missing or invalid settings still exit at startup. |
| W-9 | Nothing the port serves holds `HEVY_API_KEY`, `GARMIN_TOKEN`, `HEVY_SESSION`, a username, an email or an account id (A-6). Settings show as `Config.summary` does, with secrets as set or unset. Hevy and Garmin ids appear only for the links. The page escapes every Hevy title. |
| W-10 | A preview of a pull request (TJ, 2026-11-12 and 2026-11-13, #62). With `PREVIEW_PR` set the app runs its real loop over the made-up Hevy, Hevy Trainer and Garmin accounts in `preview.py`, in memory: routines in two folders, a Trainer program, an exercise of the user's own that goes by muscle group (F-53), and one routine the made-up Garmin refuses for too many steps (F-16). It never calls Hevy or Garmin, with or without credentials set: their sign-ins rotate, and a second holder would sign the live app out (A-7). Sync now and Force sync work as they do live. The page shows a red banner above the top bar: "You are viewing a preview release of hevy-garmin-sync \| PR: 63 \| Commit: 7bc73bc". The tests build their fakes on the same classes, so the recorded shapes (D-10) hold both. |

</div>

## 13. Delivery

<div class="wrap">

| ID | Requirement |
|----|----|
| D-1 | One repo, `zimmertr/hevy-garmin-sync`, holding the app and the Helm chart (no GitHub organization; changed 2026-11-07). Created at TJ's request with the `/initialize-project` skill, which sets CI, tests and engineering rules; yggdrasil imports it into Terraform afterwards. Do not create other repos or registries. |
| D-2 | Python 3.15. Runnable from a clone with Python. Not published to PyPI. HTTP: `requests`, the library python-garminconnect already depends on (it also uses `curl_cffi` for Garmin's sign-in); no other HTTP client. |
| D-3 | Image: amd64 and arm64, at `ghcr.io/zimmertr/hevy-garmin-sync` (on Docker Hub until zimmertr/yggdrasil#9 moved it, 2026-11-10), exact version tags only (no `latest`). A basic `compose.yaml` with the volume ships in the repo. |
| D-4 | Helm chart, in the same repo, named `hevy-garmin-sync-helm` (not the image's name, which would collide on the OCI path; bluebird#111), published as an OCI chart to `oci://ghcr.io/zimmertr`, pinning the image's digest, by yggdrasil's release module since record 0012 (installed with `helm install oci://...`; no chart site, no Artifact Hub, no Argo Rollouts canary, since a canary runs two copies at once; kept by TJ over the initialize-project defaults, 2026-11-07). Contents: Deployment (1 replica, `Recreate` strategy so two pods never share tokens), PersistentVolumeClaim for `DATA_DIR`, Secret or existing Secret for `HEVY_API_KEY`, `GARMIN_TOKEN`, `HEVY_SESSION`; values for resources, pod and container security context, nodeSelector, tolerations. Since 2026-11-12 (#31): a Service for the status page (`service.type`, `ClusterIP` by default, `service.port`, `service.annotations`; no Ingress), and liveness and readiness probes (W-7). Since 2026-11-13 (#62): an Istio `Gateway` and `VirtualService` for the page by hostname through an existing ingress gateway (`ingress.enabled`, off by default, `ingress.hosts`, `ingress.gatewaySelector`), and `persistence.enabled`, which keeps `DATA_DIR` in an `emptyDir` when false, for a preview. |
| D-5 | MIT license. Fresh code; `zimmertr/hevy-trainer-sync` is a reference only. Credit hevy2garmin and garmin-auth (MIT) where their maps or flows are used. |
| D-6 | Versions start at 0.1.0; 1.0.0 only when TJ says it's ready. |
| D-7 | TJ's own deployment: every release's CI bumps the chart version in Kubernetes-Manifests (the `version` of the `hevy-garmin-sync-helm` entry in the folder's `kustomization.yml`), through a PR that merges itself, and Argo CD deploys it (TJ, 2026-11-07; wording corrected 2026-11-10). Until cutover the bumped file is `misc/hevy-garmin-sync.disabled/kustomization.yml`: the misc ApplicationSet skips folders named `*.disable*`, so nothing deploys early. At cutover the folder is renamed to `misc/hevy-garmin-sync` and the bump's path changes with it. TJ's cutover: one step, downtime fine. Remove hevy2garmin, the `hevy-trainer-sync` CronJob and the `hevy-trainer-poll` Deployment from Kubernetes-Manifests `misc/hevy2garmin`; TJ deletes hevy2garmin's Garmin workouts by hand; TJ deletes the old tool's "Hevy Trainer" routine folder in Hevy (else its routines sync as plain routines beside the real Trainer workouts); deploy the chart. Archive hevy-trainer-sync afterwards; its open issues are abandoned with it. DONE 2026-11-10: hevy2garmin, the CronJob and the poller were removed (Kubernetes-Manifests PR 1965), TJ deleted the old routines and Garmin workouts, 0.2.0 was released, the folder was renamed (Kubernetes-Manifests PR 1969) and the bump now edits `misc/hevy-garmin-sync/kustomization.yml`, so every release deploys (decision record 0005). |
| D-7a | Agents own the README and keep it accurate in every PR. It is short and points to `docs/` for the rest (TJ, 2026-11-13: "Readmes are supposed to be short and concise and reference supplementary docs where relevant"). It must cover: what the app does and doesn't do, requirements (Hevy Pro, a Garmin watch with strength workouts), getting `HEVY_API_KEY`, running `login`, copying the hevy.com cookie for Trainer, the private-API note for Trainer, every variable, running it with Compose and with the Helm chart, how to tell it works, its known limitations (an exercise swapped for one session, #44; custom exercises under a Garmin name, C-11; Trainer's weights worked out by the app; a routine deleted in Hevy staying in the watch's saved workout list, F-14; not editing a workout's description, F-12), and credits to hevy2garmin and python-garminconnect. Getting `compose.yaml` and `.env` without a clone and moving to a new release are in `docs/CONFIGURATION.md`; running `login` from home is in `docs/USAGE.md`, and `login` says it when a sign-in fails (A-7). Its order is a table of contents, then Summary, How It Works, Requirements, Instructions (setting up Hevy Trainer is part of the first step, since many users will want it), Configuration, Known Limitations and Problems, Docs, Support, License (TJ, 2026-11-14). It names no release: the commands link the Releases page, Helm installs the newest chart with no `--version`, and Compose takes the version from `HEVY_GARMIN_SYNC_VERSION` in `.env`. Running from a clone is in `docs/DEVELOPMENT.md` (TJ, 2026-11-13, #40). Docs layout beyond the README is whatever `/initialize-project` sets up. |
| D-7b | A dedicated doc in `./docs/` of the app repo (e.g. `docs/HEVY_TRAINER_RULES.md`) records the Trainer rules as findings: each rule (section 6 and F-46), every constant table, the inputs and endpoints used, the Hevy app version the rules match (3.2.5), and the cases checked against the app with dates and results. It records findings only, not how they were found (TJ, 2026-11-07). Never commit the app's code. |
| D-9 | Build order (TJ, 2026-11-07): the first version includes everything in this spec before TJ switches over. One PR with everything: code, tests, exercise map CSV, this spec converted to Markdown as `docs/SPEC.md` (kept current as decisions change; with the same omissions as D-7b), the `docs/` Hevy rules doc (D-7b), `compose.yaml`, the Helm chart, README. Build from this page; the spec does not need its own PR first (TJ, 2026-11-07). CI is the test runner; open the PR as a draft early and push often. |
| D-10 | Tests: CI cannot reach TJ's accounts. Hevy and Garmin are stubbed with real responses recorded once from TJ's accounts, with every name, id, token, email and other personal value replaced before commit (the repo is public). The Trainer cases checked against the app become fixed tests, anonymized: Side Bend 35 to 40 lb (increase), Goblet Squat warm-ups 30 and 50 lb, Lying Leg Raise to 15-20 reps, and the six unchanged exercises from the 3 Nov Lower; plus the predicted 7 Nov Upper (Seal Row 90, Floor Press 100, Upright Row 35, Pullover 30, Chest Fly 60, Hammer Curl 50, Skullcrusher 30) and the week case (6 Nov 2026 is program week 8, cycle 2 week 2, with Sunday as first weekday). Live runs against TJ's accounts happen at milestones, each with TJ's OK. Every reply the fakes build is recorded as a shape (keys and types, no values) in `tests/data/recorded_shapes.json`, and a test fails when a fake drifts from it (#22): Garmin's settings, workout list item, stored workout, calendar entry and schedule reply, and the five Hevy Trainer reads, on 2026-11-10 with `make live-check`; Hevy's public API (folders, routines, an exercise template, its exercise history and the workout events) on 2026-11-11 with `make live-check-hevy`; and later on 2026-11-11 Garmin's stored repeat group and the steps in and around it, a row of the unit list, and `user_key_values`. A routine set's `rep_range`, sent only with a rep range, is optional there, and a number's int and float count as one type. |
| D-8 | The repo is public: no tokens, ids or personal data in code, fixtures or logs. |
| D-12 | A preview per pull request (TJ, 2026-11-12 and 2026-11-13, #62). yggdrasil's `pr-preview` module builds each PR's image as `ghcr.io/zimmertr/hevy-garmin-sync-pr:pr-<N>-<head sha>` on `pull_request`, and TJ's own PRs get the `create pr container` label. An Argo CD `ApplicationSet` with the pull request generator in Kubernetes-Manifests `misc/hevy-garmin-sync-pr/` runs each labelled PR's chart with `PREVIEW_PR`, `PREVIEW_COMMIT`, no credential, `persistence.enabled: false` and the host `pr-<N>.atlas.sol.milkyway`, and removes it when the PR closes. Each release bumps that set's chart version, as it bumps the live folder's. The live page answers at `atlas.sol.milkyway`, through the same shared gateway. |
| D-11 | Choices made while building, confirmed by TJ on 2026-11-10 (PR #16). Where one differs from a row above, this row wins. (a) F-20a: the workout JSON is built as plain dictionaries with the same fields the watch checks sent, not with python-garminconnect's typed models or `create_repeat_group`; the typed models would add pydantic to the image and move the `Version` hash when the library changes a default. (b) F-14: a Garmin workout is deleted only after two polls in a row find its routine gone, because Hevy's list is read a page at a time and can shift mid-read. (c) F-3b: exercise templates are read as one list, once, 100 per page; a template created later is read by itself. (d) F-31a: a Send to Device that fails is retried at the next run from memory; a crash in between loses that one send. (e) O-1: an unexpected error is logged with its traceback and waited out like an outage, never fatal. (f) U-14: Garmin's `statute_uk` is treated as kilograms and yards. (g) O-1: a 401 and a 403 both count as a rejected credential. (h) C-8: `DATA_DIR` defaults to `data` outside the image. (i) Section 6: Hevy Trainer has its own wait after a failure; while it fails, routines keep syncing and Trainer's Garmin workouts stay as they are. A rejected `HEVY_SESSION` is not such a failure: it stops Hevy Trainer until the session is fixed or unset, and routines keep syncing (W-8; TJ, 2026-11-12, #31; until then it exited like the other credentials and stopped routines too, TJ, 2026-11-10, #23). (j) F-46: "the last 3 months, else the last 12" is taken as 91 and 365 days until the exact windows are confirmed. (k) F-40: Trainer's equipment is the public API's `equipment` field; it matched Hevy Trainer's own equipment value for all 447 exercises compared on 2026-11-10. (l) U-15: the app logs the shape of `/exercise_template_units`, without values, on the first read and uses the account's unit until a row fits; the row seen on 2026-11-11 fit. (m) F-53: the catch-all for a custom exercise is Garmin's `CORE` / `CORE`. (n) F-51: the map uses Garmin categories outside classic strength where they fit best (`RUN_INDOOR`, `INDOOR_BIKE`, `ELLIPTICAL`, `STAIR_STEPPER`, `BIKE_OUTDOOR`, `SLED`, `SANDBAG`, `BATTLE_ROPE`, `BANDED_EXERCISES`, `SUSPENSION`); Garmin accepted one strength workout holding all 42 categories the tables use (2026-11-10); for `BATTLE_ROPE` and `HYPEREXTENSION` the exercise it stored differed from the one sent. Read back on 2026-11-10 (#22): for the rows that send `HYPEREXTENSION` / `HYPEREXTENSION` and `BATTLE_ROPE` / `BATTLE_ROPE` Garmin stored the category with an empty exercise name, and the watch showed the category's name; every other row of those two categories was stored as sent. No row changes. On 2026-11-11 `CURL` / `CURL` was stored the same way; a set of each, recorded on the watch that day, was named for its category on the watch and in Strava, and the Hyperextension set in Garmin Connect too (`docs/DATA.md`). No row changes. (o) F-51a: TJ does not review the map row by row; he files an issue when a sync looks wrong (2026-11-10). |

</div>

## 14. Backlog (not in the first version)

<div class="wrap">

| ID | Item |
|----|----|
| B-5 | An exercise swapped for one session in Hevy (answered "Replace permanently? No") never reaches the watch: Hevy keeps it on the phone until the workout is saved, in none of the replies the app reads (2026-11-11, `docs/DATA.md`). Tracked in #44 (TJ, 2026-11-11). |
| B-4 | Not in MVP; file as an issue once the repo exists (TJ, 2026-11-07). Re-evaluate how the app retries a workout Garmin rejected (F-16): today it waits for a Hevy change, startup or midnight. Find a design that recovers sooner without risking Garmin blocking the account for calling too often. Done (TJ, 2026-11-10, #4): gaps from 5 minutes, doubling until midnight, then once a day; the rule is in F-16. |
| B-3 | Not in MVP; file as an enhancement issue once the repo exists (TJ, 2026-11-07). Add last time's numbers to each set's note, as Hevy's PREVIOUS column shows them, e.g. `Drop set: 4-6 reps` then `Prev: 25lb x 6 @ 6 RPE`. Source: the public API's exercise history, so no private sign-in. Open points: (1) sets only share a repeat group when their notes match (F-20a), so differing previous numbers split a group back to SET 1/1; per set vs one list per exercise is undecided; (2) Hevy's rule for which old set counts as previous (warm-up against warm-up, same routine or any workout, a possible Hevy setting) must be copied exactly or not at all; (3) every logged workout changes the notes, so the app must watch saved workouts, rewrite and resend the affected Garmin workouts; (4) untested whether a line break in a note shows as two lines on the watch. Checked on 2026-11-11 (#3, `docs/DATA.md`): for (4), `make live-check-notes` put three forms of such a note on TJ's Fenix 8, and a line break showed as a new line, with notes of up to 5 lines shown whole. For (2), Hevy has the setting: "Previous Workout Values", "Any workout" by default or "Same Routine", and it says it does not apply to Hevy Trainer workouts. For (1), TJ leaned to one list per exercise ("Presumably just per exercise"), which needs no match of set to set. Decided by TJ on 2026-11-11, after the photos: build it, with last time's working sets one to a line under `Prev:`, each with its unit and RPE, as in `65 lb x 6 @ RPE 7`. The unit is the one the app sends weights to Garmin in (F-21a). A second run that day showed that form too wide: `65 lb x 6 @ RPE 7.5` broke in two, and the watch scrolls by itself through a note longer than its six lines. So each set must fit on one line (TJ, 2026-11-11), and a third run with `make live-check-notes` wrote the widest likely set several ways to find one that does. TJ chose the form with the unit once, in the heading: `Prev (lb):`, then one line for each working set, as in `65 x 6 @ 7.5`, the number after `@` being the RPE. That form fit at `102.5 x 12 @ 9.5`; a line of more than 8 digits is written without the spaces around its numbers, as in `1002.5 x12 @9.5`, which also fit. Done (TJ, 2026-11-11, #3): for routines and Hevy Trainer workouts alike, last time being the last workout of any kind that logged the exercise, on by default with `ENABLE_PREVIOUS_VALUES` to turn it off, and the heading spelled out as `Previous (lb):`; the rule is in F-30b. Taken out of the notes again by TJ on 2026-11-13, after a session with it: it stays on the status page (F-30, F-30b). |
| B-2 | Users with several Garmin devices: push workouts to devices other than the last-synced one, if anyone asks. Each record of `get_devices` carries `strengthWorkoutCapable` and `workoutCapable`, and `get_primary_training_device` names the primary device (seen 2026-11-10), so a rule such as "every device that takes strength workouts" is possible without a setting. |
| B-1 | Let users choose which days each workout goes on the calendar, e.g. Lower on Tuesday and Upper on Friday, from a config file, instead of every workout on every day. TJ asked for this on 2026-11-07. File it as an issue in the new repo once it exists. |

</div>

## 15. Acceptance (first usable version)

1.  With only `HEVY_GARMIN_SYNC_VERSION`, `HEVY_API_KEY`, `GARMIN_TOKEN` and a volume, `docker compose up` creates one Garmin workout per Hevy routine, named per F-15, all on today's calendar.
2.  Editing a routine in Hevy updates the same Garmin workout within one poll interval; deleting it removes the workout and its calendar entry.
3.  Restarting the container, or deleting the volume and re-seeding `GARMIN_TOKEN`, creates no duplicates.
4.  At local midnight every routine, and Hevy Trainer's next workout (F-33), has one entry on the new day, and the app's entries on past days are gone (F-32).
5.  With `HEVY_SESSION` set, Trainer workouts match the Hevy app's prescribed weights and cycle/week for TJ's program.
6.  On the watch: every set ends with the reps and weight prompt, including the last; rest steps use the routine's timers (open rest when it has none); matching sets count as SET 1/3, 2/3, 3/3; each set's note follows F-30.
7.  On Strava, after a session done from a planned workout, every exercise whose Strava column is filled matches it.
8.  Killing Garmin connectivity logs errors with a fix and recovers on its own; a bad env var exits at startup with a clear message.
