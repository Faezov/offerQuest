# Chekhov Refactor Plan

## Diagnosis

Main bloat sources:

* Web route indirection: **offerquest/web/app.py** builds **OverviewRouteDeps**, **SetupRouteDeps**, and **WorkflowRouteDeps**, then every route calls **get_deps()** just to reach already-imported functions.
* Barrel modules: **offerquest/workbench/__init__.py** re-exports most of workbench; **offerquest/workbench/setup.py** is an unused wildcard wrapper.
* Repeated workflow plumbing: path resolution, existence checks, output writes, run manifests, form feedback, and selected-job context are repeated across **workbench/profile.py**, **workbench/jobs.py**, and **workbench/documents.py**.
* Duplicate small helpers: **dedupe** variants, location predicates, byte formatting, JSON writing, and “select/suggest” helpers appear in multiple places.
* Some modules mix concerns: **ollama.py** contains status, CLI resolution, server lifecycle, GPU detection, archive download, HTTP streaming, and formatting in one 982-line file.

Baseline: Python LOC is **15,791**. Largest app files are **ollama.py** **982**, **jobs.py** **975**, **cli.py** **969**, **resume_tailoring.py** **800**, **cover_letter.py** **749**.

## Ranked Refactor Opportunities

1. Remove web route dependency containers.
   Files/classes/functions: **offerquest/web/app.py**, **offerquest/web/_routes_overview.py::OverviewRouteDeps**, **offerquest/web/_routes_setup.py::SetupRouteDeps**, **offerquest/web/_routes_workflows.py::WorkflowRouteDeps**, plus **register_*_routes**.
   Delete the three dataclasses, three **get_*_route_deps** closures, **get_deps** route arguments, repeated **deps = get_deps()** calls.
2. Delete unused compatibility wrapper.
   File: **offerquest/workbench/setup.py**.
   It is not referenced by repo code or tests. Delete it entirely unless external import compatibility must be preserved.
3. Shrink workbench public barrel.
   File: **offerquest/workbench/__init__.py**.
   Stop using it from **web/app.py**; route modules should import exact owning modules. Keep documented/tested exports for now to avoid public API churn, but do not add more.
4. Merge repeated selected-job/workflow form context.
   Files/functions: **workbench/documents.py::build_cover_letter_selection_context**, **workbench/jobs.py::build_rerank_jobs_form_view**, **_util.py::choose_ranking_source**, **choose_ranking_job**, **build_ranking_preview_items**.
   Keep one selection/context builder for ranking source, selected job, documents, jobs files, and defaults.
5. Inline thin wrappers in document workflows.
   Files/functions: **workbench/documents.py::generate_cover_letter_payload**, **write_cover_letter_draft_artifact**, **prepare_cover_letter_inputs**.
   Keep **prepare_cover_letter_inputs** only if shared by all four workflows; otherwise inline the one-call wrappers that hide simple calls.
6. Consolidate obvious duplicate helpers without adding a new utility module.
   Files/functions: **profile.py::dedupe**, **ats.py::dedupe_preserve_order**, **resume_tailoring.py::dedupe_preserve_order**, **cover_letter.py::looks_like_location**, **jobs.py::looks_like_location**, **ollama.py::_format_bytes**, **workbench/ollama_setup.py::format_progress_bytes**.
   Prefer reusing an existing owner or inlining at call sites. Do not create a generic **utils.py**.
7. Split only behavior-heavy **ollama.py** if needed after deletions.
   Candidate boundaries: HTTP/streaming, local runtime/server lifecycle, GPU detection.
   This is lower priority because splitting files may reduce file size but can add concepts. Do it only if call paths become simpler.

## Deletions, Merges, And Abstractions To Remove

Delete entirely:

* **OverviewRouteDeps**
* **SetupRouteDeps**
* **WorkflowRouteDeps**
* **get_overview_route_deps**
* **get_setup_route_deps**
* **get_workflow_route_deps**
* **offerquest/workbench/setup.py**, if no external compatibility concern

Merge or inline:

* Route calls should call imported functions directly.
* Duplicate Ollama action-result construction in **/ollama** sync submit and background job should become one small local helper in **_routes_setup.py**.
* **workbench/documents.py** one-hop helpers should be inlined unless they remove real duplication.
* Duplicate **dedupe_preserve_order** variants should collapse to one existing owner or local inline logic.

Remove, not add:

* Dependency dataclasses used only as function bags.
* Wildcard re-export wrapper.
* Broad barrel imports from **workbench** inside **web/app.py**.
* New generic helper modules.
* New architectural registries for CLI or routes.

## Risks And Invariants

Must not change:

* CLI command names, flags, exit behavior, JSON payload shape, or run manifest contents.
* Web routes, template names, form field names, redirects/responses, status codes, and visible workflow behavior.
* Workspace path safety: inputs and outputs must stay inside the workspace where currently enforced.
* Job record normalization, IDs, dedupe keys, ranking order, ATS scores, and cover-letter/resume payload schemas.
* Ollama progress JSON shape and job-store behavior.

Known verification constraint:

* **pytest** is not installed here: **pytest -q** and **python3 -m pytest -q** both fail because pytest is unavailable. First implementation pass should install/use the project dev environment, then run the suite.

## Milestone Plan

1. Web route dependency deletion.
   Change **offerquest/web/app.py**, **_routes_overview.py**, **_routes_setup.py**, **_routes_workflows.py**, and adjust **tests/test_web_app.py** patch targets.
   Verification: run **python3 -m pytest tests/test_web_app.py tests/test_workbench.py -q**.
   Invariants: all routes render the same templates; patched test doubles still isolate slow work; Ollama job polling payloads unchanged.
   Metrics: remove 3 classes, 3 closure factories, every **deps = get_deps()** call; reduce route call depth by one.
2. Remove unused workbench setup wrapper.
   Delete **offerquest/workbench/setup.py**.
   Verification: **rg "workbench\\.setup|from offerquest\\.workbench\\.setup"** returns no matches; run **python3 -m pytest tests/test_workbench.py tests/test_web_app.py -q**.
   Metrics: one fewer file, 4 LOC deleted.
3. Simplify workbench document/job context.
   Refactor selection/default context in **workbench/documents.py**, **workbench/jobs.py**, and **_util.py**.
   Verification: **tests/test_workbench.py**, **tests/test_web_app.py**.
   Metrics: fewer repeated calls to **list_ranking_sources**, **list_profile_source_files**, **list_job_record_files**; lower LOC in **documents.py** and **jobs.py**.
4. Remove duplicate tiny helpers.
   Consolidate or inline dedupe, location, byte-formatting helpers in **profile.py**, **ats.py**, **resume_tailoring.py**, **cover_letter.py**, **jobs.py**, **ollama.py**, **workbench/ollama_setup.py**.
   Verification: **tests/test_profile.py**, **tests/test_ats.py**, **tests/test_resume_tailoring.py**, **tests/test_cover_letter.py**, **tests/test_jobs.py**, **tests/test_ollama.py**.
   Metrics: fewer duplicate helper definitions; no output diffs in scoring/drafting tests.
5. Review CLI/workbench overlap.
   Only after behavior is protected, look for direct reuse between CLI handlers and workbench runners without changing CLI API.
   Verification: **tests/test_cli_productization.py**, workflow tests, release smoke tests.
   Metrics: fewer repeated output/write/run-manifest blocks, no new command abstraction registry.

## First Milestone To Implement

Start with milestone 1 only: delete the three web route dependency dataclasses and **get_deps** factories, make route modules import/call their real functions directly, and update web tests to patch the new owning module paths. This is the cleanest first cut: small, reversible, mostly mechanical, and it removes pure ceremony without touching scoring, document parsing, job data, or generated artifacts.
