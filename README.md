# Medicare Supplement Enrollment IDP Pipeline

Serverless intelligent document processing pipeline for Medicare Supplement
enrollment applications. Ingests PDFs and scanned images, extracts fields
using Amazon Textract Queries (template-based, one query set per document
variant), conforms the result to a canonical JSON schema, and hands off the
transformed XML to the existing Enrollment API's "insurance update" endpoint.

## Architecture

![Architecture diagram: an enrollment document lands in S3, EventBridge starts a Step Functions state machine that classifies it, runs it through Textract, validates and stores a canonical record in DynamoDB, transforms it to XML, and submits it to a mock or real Enrollment API, with any step failure routed to a dead-letter queue.](docs/architecture.svg)

```
S3 (raw upload, CLI or web app) --EventBridge--> Step Functions pipeline:
  PrepareInput (Lambda - extracts documentId from a web-app upload key, or generates one)
    -> StartTextDetection (async Textract job, plain OCR - text only)
    -> WaitForTextDetection / CheckTextDetectionStatus (poll loop)
    -> ClassifyDocument (matches detected text against configured form fingerprints)
    -> MarkDocumentProcessing (DynamoDB status -> PROCESSING)
    -> StartTextractAnalysis (async Textract job, FORMS + QUERIES for the classified variant)
    -> WaitForTextract / CheckTextractStatus (poll loop)
    -> ParseAndValidate (Textract answers -> canonical record, schema + confidence check)
    -> [FlagForReview | StoreCanonicalRecord] (DynamoDB)
    -> TransformToXml (canonical record -> <InsuranceUpdate> XML)
    -> SubmitToEnrollmentApi (POST to the existing XML Enrollment API)
  Any step failure -> SendToDeadLetterQueue (SQS) -> PipelineFailed
```

- **S3** — `RawDocumentsBucket` (incoming uploads, triggers the pipeline via
  EventBridge) and `ProcessedDocumentsBucket` (Textract output, canonical
  JSON, generated XML). Both SSE-KMS encrypted with a customer-managed key.
- **Step Functions** (`statemachine/pipeline.asl.json`) — orchestrates the
  pipeline end to end, with retry/catch on every task and a DLQ for failures.
- **DynamoDB** (`EnrollmentRecordsTable`) — one item per document, keyed by
  `documentId`, status progressing `UPLOADED` (web app only) →
  `PROCESSING` → `NEEDS_REVIEW` | `READY_FOR_SUBMISSION` → `SUBMITTED` /
  `SUBMISSION_FAILED` / `SUBMISSION_SKIPPED`, plus canonical record,
  low-confidence fields, and schema errors once available. Written with
  `UpdateItem` (not `PutItem`) everywhere after the first write, so earlier
  fields (e.g. the web app's `originalFilename`/upload-time `ingestedAt`)
  survive later steps.
- **Lambda functions** (`src/functions/`):
  | Function | Responsibility |
  |---|---|
  | `prepare_input` | First pipeline step. Extracts `documentId` from a web-app upload key (`incoming/web/<id>/...`) so the pipeline's writes land on the same tracking record the upload API created; generates a fresh one for any other key (e.g. the CLI convention below), exactly like the `States.UUID()` this replaced. |
  | `start_text_detection` | Kicks off a plain-OCR async Textract `StartDocumentTextDetection` job (no FORMS/QUERIES) purely to get text for classification, before the variant — and therefore the right query set — is known. |
  | `check_text_detection_status` | Polls that job and returns the joined `LINE` text directly (small enough to pass through state, no S3 round-trip). |
  | `classify_document` | Matches the detected text against configured form fingerprints (`idp_common.classification_config.CLASSIFICATION_RULES`) to determine document type/state/variant — content-based, independent of the S3 upload path. |
  | `mark_document_processing` | Updates DynamoDB status to `PROCESSING` right after classification, so a document has visible status movement between `UPLOADED` and its terminal outcome. |
  | `start_textract_analysis` | Kicks off an async Textract `StartDocumentAnalysis` job using the query set for the document's variant. |
  | `check_textract_status` | Polls the Textract job and writes the merged Blocks to S3 once it succeeds. |
  | `parse_and_validate` | Extracts Textract Query answers into the canonical schema, checks field confidence against `CONFIDENCE_THRESHOLD`, and JSON-Schema-validates the result. |
  | `store_canonical_record` | Persists the canonical record and status to DynamoDB. |
  | `transform_to_xml` | Maps the canonical record to the `<InsuranceUpdate>` XML the Enrollment API expects (placeholder mapping — see TODO in the module). |
  | `submit_enrollment` | POSTs the XML to the Enrollment API and records the outcome. In `dev`/`test`, auto-wires to the built-in mock Enrollment API (below) if `EnrollmentApiEndpoint` isn't set; no-ops (`SUBMISSION_SKIPPED`) in `prod` if it isn't set. |
  | `mock_enrollment_api` | Dev/test stand-in for the real Enrollment API. Accepts the posted XML, stores it in `MockEnrollmentSubmissionsTable` so submissions can be inspected, and returns an `<InsuranceUpdateAck>`. Never deployed for `Stage=prod`. |
- **Common layer** (`src/layers/common/idp_common/`) — shared across
  functions:
  - `canonical_enrollment_schema.json` / `schema.py` — the canonical record's
    JSON Schema, `CONFIDENCE_THRESHOLD`, and a `validate_canonical_record()`
    helper.
  - `classification_config.py` — the configured form fingerprints
    (`CLASSIFICATION_RULES`: required text markers per state/carrier) that
    `classify_document` matches against. Onboard a new state/carrier form by
    adding an entry here.
  - `textract_queries.py` — the template-based Textract Queries, the field
    map from query alias to canonical field name, and the checkbox-field
    config (`DEFAULT_SELECTION_FIELDS`) that `parse_and_validate` matches
    against Textract FORMS' `SELECTION_ELEMENT` blocks — each per document
    variant (`DEFAULT_*` plus per-state `VARIANT_*` overrides).

### Template-based today, LLM-assisted later

Classification and extraction are currently 100% template/config-based:
`classify_document` matches OCR'd text against a configured set of form
fingerprints (`classification_config.CLASSIFICATION_RULES`), and extraction
runs a fixed set of Textract Queries per variant, mapped to canonical
fields, validated against a confidence threshold and a JSON Schema. This
keeps costs low and behavior predictable for the common case. The `variant`
concept (state-specific query sets, field maps, and selection-field configs
in `textract_queries.py`) is the seam for handling state-specific
branding/verbiage differences without forking the pipeline. An LLM-based
classification/extraction path — for documents that don't match any
configured fingerprint (`state: "UNKNOWN"`, `variant: "DEFAULT"`) — can be
added later as an alternate branch feeding the same canonical schema and
validation step, without changing anything downstream.

## Web upload/tracking app

![Web upload/tracking app diagram: a browser talks to a single CloudFront distribution that routes / to a static S3 frontend and /api/* to an HTTP API backed by three Lambdas, which read and write the same RawDocumentsBucket and EnrollmentRecordsTable the IDP pipeline uses; the actual file upload goes directly from the browser to S3 via a presigned URL.](docs/webapp-architecture.svg)

A static frontend (`frontend/`) lets a user upload an enrollment PDF and
watch it move through the pipeline above, polling status every few seconds.
No auth yet (open access, dev-only posture — matches the Mock Enrollment
API) — tighten before handling real PII. Served through the same CloudFront
distribution as its API (`/api/*` behavior), so there's no cross-origin
request involved and no CORS configuration needed for that path.

- **`WebAppApi`** (HTTP API) + 7 Lambdas:
  | Route | Function | Responsibility |
  |---|---|---|
  | `POST /api/documents` | `request_upload` | Generates a `documentId`, signs a presigned S3 PUT URL (`incoming/web/<id>/<filename>`), and writes the initial `UPLOADED` tracking record. The browser then PUTs the file straight to S3 — never through this API — so large scanned documents aren't limited by API Gateway/Lambda payload sizes. |
  | `GET /api/documents/{documentId}` | `get_document_status` | Returns the current tracking record, or 404. |
  | `GET /api/documents?limit=&status=` | `list_documents` | Returns recent documents, newest first. Unfiltered: a bounded `Scan` (fine at this project's dev/demo scale — see the TODO below to replace with a GSI if that changes). With `status=`: `Query`s `EnrollmentRecordsTable`'s `StatusIndex` GSI directly instead — already sorted, and correct at any volume unlike the Scan path. |
  | `PATCH /api/documents/{documentId}` | `edit_document` | Corrects canonical fields on a `NEEDS_REVIEW` record (400 on an unknown/non-editable field name, 409 if the document isn't `NEEDS_REVIEW`). Merges the given fields onto the stored `canonicalRecord`, re-validates against the canonical schema, and drops any edited field names from `lowConfidenceFields` — a human just supplied them. Status stays `NEEDS_REVIEW`; editing alone never auto-submits. |
  | `POST /api/documents/{documentId}/resubmit` | `resubmit_document` | Submits a reviewed `NEEDS_REVIEW` record to the Enrollment API (409 if not `NEEDS_REVIEW`, 422 with `schemaErrors` if validation still fails). Builds and posts the XML the same way the pipeline's `transform_to_xml`/`submit_enrollment` steps do — via the shared `idp_common.enrollment_submission` module — reading `canonicalRecord` straight from DynamoDB rather than re-running Textract, since the human is correcting already-extracted values, not re-scanning the document. Clears `lowConfidenceFields` on success (resubmission is the human's sign-off) and lands on `SUBMITTED`/`SUBMISSION_FAILED`/`SUBMISSION_SKIPPED` exactly like the pipeline's own submission step. |
  | `DELETE /api/documents/{documentId}` | `delete_document` | Permanently deletes the tracking record and its underlying S3 objects (raw upload + any `canonical`/`xml` output). 404 if missing; 409 while `UPLOADED`/`PROCESSING` — deleting mid-flight would race with the pipeline's own `UpdateItem` calls (which recreate the item via `if_not_exists()` if it's gone), silently "resurrecting" a partial record. |
  | `GET /api/documents/{documentId}/view` | `view_document` | 302-redirects to a short-lived (5 min) presigned S3 GET URL for the original uploaded PDF, with response headers forcing inline rendering (`ResponseContentType: application/pdf`, `ResponseContentDisposition: inline`). A plain `<a target="_blank">` link can point straight at this route — the browser's own top-level navigation follows the redirect directly to S3 (same pattern as the presigned PUT the upload flow already uses), so PDF bytes never get proxied through API Gateway/Lambda, and CORS doesn't apply to that kind of navigation at all. |
- **`FrontendDistribution`** (CloudFront, default `*.cloudfront.net` domain — no custom domain) + **`FrontendBucket`** (private S3, OAC-only) serve `frontend/index.html`/`app.js`/`styles.css`.
- `RawDocumentsBucket` has a `CorsConfiguration` allowing browser `PUT` (needed because the presigned upload target — the S3 REST endpoint — is a different origin than the page, even though the presigned URL itself is authorized independent of CORS).

### Reviewing and resubmitting NEEDS_REVIEW documents

When a document lands in `NEEDS_REVIEW`, the frontend swaps the read-only
extracted-fields table for an editable form (fields flagged low-confidence
are highlighted). **Save changes** calls `PATCH`; **Resubmit** calls
`POST .../resubmit` and is disabled while `schemaErrors` is non-empty. Both
buttons re-render the record from the response, so a save's updated
`lowConfidenceFields`/`schemaErrors` and a resubmit's new terminal status
show immediately without a poll.

Each row in Recent uploads also has a view (eye) link that opens
`GET .../{documentId}/view` in a new tab — the browser follows its 302
straight to the presigned S3 URL, so the PDF just opens in the tab's own
PDF viewer — and a delete (trash-can) button that calls
`DELETE .../{documentId}` after a confirm prompt. Delete is greyed out while
a document is `UPLOADED`/`PROCESSING` (matching the endpoint's 409),
reflecting the current status filter/page and refreshing the list on
success.

### Deploying the frontend

`sam build`/`sam deploy` only package Lambda code — the static assets need
a separate sync step after every deploy that changes them:

```
aws s3 sync frontend/ s3://<FrontendBucketName>/ --delete
aws cloudfront create-invalidation --distribution-id <FrontendDistributionId> --paths "/*"
```

Both names are in the stack's Outputs. Then open `FrontendDistributionDomainName`.

Note: `FrontendDistribution` is a CloudFront distribution — the *first*
`sam deploy` that creates it takes noticeably longer (~10-20 minutes) than
this project's other deploys while it propagates; subsequent deploys that
don't change it are unaffected.

## Known TODOs

- `transform_to_xml`: the `<InsuranceUpdate>` XML is a placeholder 1:1 field
  dump. Replace with the real structure/field names once the Enrollment
  API's XSD or a sample payload is available.
- `submit_enrollment`: no authentication is sent yet. Add whatever the
  Enrollment API requires (API key / OAuth / mTLS), pulled from Secrets
  Manager.
- `classify_document`: content-based, matched against
  `CLASSIFICATION_RULES` — currently has fingerprints for MI, GA (Anthem),
  and TN (BlueCross BlueShield of Tennessee "BlueElite") forms. Onboard each
  new state/carrier form by adding a rule (and, if its field layout differs,
  a matching `VARIANT_*` entry in `textract_queries.py` — GA/TN both needed
  a `VARIANT_SELECTION_FIELDS` override since their real forms label plan
  checkboxes `"Plan A"`/`"Plan G"` rather than MI's bare `"A"`/`"G"`).
  Confirmed against the TN fixture: correctly classified and extracted
  (`planSelected: "Plan G"`, `schemaErrors: []`), but `applicantName` and
  `applicantPhone` landed under the confidence threshold — TN's form splits
  the name across four boxes (Last/Jr,Sr/First/MI) rather than three, which
  the free-text Query answered correctly but less confidently. A real
  finding about that form's layout, not a bug.
- `canonical_enrollment_schema.json` is a draft — align its required
  fields with what the Enrollment API's XML actually requires.
- Textract Queries extract free-text/typed answers reliably but can't read
  checkbox-only answers (plan selection, yes/no questions), which is how
  real Medigap forms represent `planSelected` and
  `replacingExistingCoverage`. `parse_and_validate` now falls back to
  Textract FORMS' `SELECTION_ELEMENT` blocks for any canonical field
  configured in `idp_common.textract_queries.DEFAULT_SELECTION_FIELDS`
  (add per-variant overrides the same way as `VARIANT_FIELD_MAPS`).
  Confirmed against the fixture in `tests/fixtures/`: both fields now
  extract the correct value, though checkbox-detection confidence tends to
  run lower than text OCR confidence (~80-84% there, against a threshold of
  85), so they may still land in `lowConfidenceFields` pending a real scan
  rather than a synthetic PDF.
- The web app has no auth (see Web upload/tracking app above) — add Cognito
  (or similar) in front of it before it's used with real enrollment PII.
- `list_documents` does a full unpaginated `Scan`, fine at this project's
  dev/demo volume. If that changes, replace with a GSI keyed on a constant
  partition + `ingestedAt` sort key rather than scaling the Scan up.

## Project layout

```
template.yaml                          SAM template (all AWS resources)
statemachine/pipeline.asl.json         Step Functions definition
src/functions/<name>/app.py            Lambda handlers
src/layers/common/idp_common/          Shared schema, validator, query/classification/response config
frontend/                              Static web app (upload + status tracking, no build step)
events/s3_object_created.json          Sample EventBridge event for local invoke
tests/unit/                            pytest unit tests (one file per function/module)
tests/fixtures/                        Synthetic test document(s)
```

## Prerequisites

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Python 3.13
- An AWS account/credentials with permission to create the resources in
  `template.yaml` (S3, DynamoDB, Step Functions, Lambda, KMS, SQS, IAM,
  API Gateway, CloudFront)

## Build

```
sam build
```

Builds the common Lambda layer (installs `jsonschema` from
`src/layers/common/requirements.txt`) and packages each function.

## Test

Unit tests mock AWS clients (`unittest.mock`) — no AWS credentials or network
access required.

```
python -m venv .venv
.venv/Scripts/activate            # .venv/bin/activate on macOS/Linux
pip install -r tests/requirements-dev.txt
pytest
```

## Deploy

```
sam deploy --guided
```

First run walks you through stack name, region, and the `Stage` and
`EnrollmentApiEndpoint` parameters, then saves choices to `samconfig.toml`
(gitignored — each environment/developer keeps their own).

For `Stage=dev` or `Stage=test`, leave `EnrollmentApiEndpoint` blank and the
stack deploys a mock Enrollment API and points `submit_enrollment` at it
automatically — no external dependency needed to exercise the full
pipeline. Check the `MockEnrollmentApiUrl` stack output for its URL, and
`MockEnrollmentSubmissionsTableName` for the DynamoDB table holding
everything it's received (`documentId`, `rawXml`, `receivedAt`,
`submissionId`).

For `Stage=prod` (where the mock isn't deployed), leave
`EnrollmentApiEndpoint` blank to run the pipeline through XML generation
only, without submitting anywhere (`submit_enrollment` returns
`SUBMISSION_SKIPPED`). Set it to a real URL, in any stage, to submit there
instead of the mock.

Subsequent deploys: `sam deploy`. Then sync the frontend (see "Deploying the
frontend" under Web upload/tracking app above) — `sam deploy` alone doesn't
touch its static assets.

### Try it

**Via the web app**: open `FrontendDistributionDomainName` (a stack Output)
and upload a PDF — e.g. the included test fixture below — through the page.

**Via the CLI**: upload a sample document to the raw bucket to trigger the
pipeline via EventBridge, e.g. using the included test fixture
(`tests/fixtures/sample-medicare-supplement-application-mi.pdf` — a synthetic,
clearly-watermarked stand-in for a real BCBSM Medicare Supplement application,
filled with fictitious applicant data covering every canonical field).
Classification is content-based (see Architecture above), so the S3 key can
be anything — `incoming/<state>/` below is just a human-readable convention,
not something the pipeline reads. Two more fixtures isolate a single
missing required field each (all other fields filled in correctly):
`...-no-plan-selected.pdf` (no plan checkbox marked —
`schemaErrors: ["'planSelected' is a required property"]`) and
`...-no-medicare-number.pdf` (Medicare number field left blank —
`schemaErrors: ["'medicareNumber' is a required property"]`). Both produce
`NEEDS_REVIEW` with every other field still extracted correctly.
Two more fixtures cover different states/carriers on the real-world happy
path: `sample-medicare-supplement-application-ga.pdf` (Anthem, Georgia —
`VALID`/`SUBMITTED`) and `...-tn.pdf` (BlueCross BlueShield of Tennessee
BlueElite — extracts correctly but lands in `NEEDS_REVIEW` on confidence,
see Known TODOs). `...-mi-low-confidence-phone.pdf` deliberately exercises
the web app's edit-and-resubmit flow: every field is typed/machine-printed
except the phone number, which is rendered hand-written into the field
(a script font, unlike the monospace used everywhere else) - Textract still
reads it correctly but with confidence under the threshold, so the document
lands in `NEEDS_REVIEW` with `lowConfidenceFields: ["applicantPhone"]` and
`schemaErrors: []` (every other field clean). Good for demonstrating
`PATCH /api/documents/{id}` + `POST .../resubmit` end-to-end without a
schema error to work around.

```
aws s3 cp tests/fixtures/sample-medicare-supplement-application-mi.pdf \
  s3://<RawDocumentsBucketName>/incoming/mi/sample.pdf
```

This triggers the Step Functions execution via EventBridge. Watch progress
in the Step Functions console, poll `GET /api/documents/<documentId>` (the
`documentId` is a UUID generated fresh for this path — check the execution's
input/output in the console, or its final Step Functions output, to find
it), or invoke a single function locally against the sample event:

```
sam local invoke ClassifyDocumentFunction --event events/s3_object_created.json
```

## Outputs

`sam deploy` prints (and `aws cloudformation describe-stacks` can retrieve):
`RawDocumentsBucketName`, `ProcessedDocumentsBucketName`,
`EnrollmentRecordsTableName`, `PipelineStateMachineArn`, `WebAppApiUrl`,
`FrontendBucketName`, `FrontendDistributionId`,
`FrontendDistributionDomainName`, and (dev/test only) `MockEnrollmentApiUrl`,
`MockEnrollmentSubmissionsTableName`.
