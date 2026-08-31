# Medicare Supplement Enrollment IDP Pipeline

Serverless intelligent document processing pipeline for Medicare Supplement
enrollment applications. Ingests PDFs and scanned images, extracts fields
using Amazon Textract Queries (template-based, one query set per document
variant), conforms the result to a canonical JSON schema, and hands off the
transformed XML to the existing Enrollment API's "insurance update" endpoint.

## Architecture

```
S3 (raw upload) --EventBridge--> Step Functions pipeline:
  ClassifyDocument
    -> StartTextractAnalysis (async Textract job, FORMS + QUERIES)
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
- **DynamoDB** (`EnrollmentRecordsTable`) — one item per document: status
  (`NEEDS_REVIEW` / `READY_FOR_SUBMISSION` / `SUBMITTED` / ...), canonical
  record, low-confidence fields, and schema errors.
- **Lambda functions** (`src/functions/`):
  | Function | Responsibility |
  |---|---|
  | `classify_document` | Determines document type/state/variant. v1 uses the `incoming/<state>/<filename>` upload convention — see the docstring for the plan to move to content-based classification. |
  | `start_textract_analysis` | Kicks off an async Textract `StartDocumentAnalysis` job using the query set for the document's variant. |
  | `check_textract_status` | Polls the Textract job and writes the merged Blocks to S3 once it succeeds. |
  | `parse_and_validate` | Extracts Textract Query answers into the canonical schema, checks field confidence against `CONFIDENCE_THRESHOLD`, and JSON-Schema-validates the result. |
  | `store_canonical_record` | Persists the canonical record and status to DynamoDB. |
  | `transform_to_xml` | Maps the canonical record to the `<InsuranceUpdate>` XML the Enrollment API expects (placeholder mapping — see TODO in the module). |
  | `submit_enrollment` | POSTs the XML to the Enrollment API and records the outcome. In `dev`/`test`, auto-wires to the built-in mock Enrollment API (below) if `EnrollmentApiEndpoint` isn't set; no-ops (`SUBMISSION_SKIPPED`) in `prod` if it isn't set. |
  | `mock_enrollment_api` | Dev/test stand-in for the real Enrollment API. Accepts the posted XML, stores it in `MockEnrollmentSubmissionsTable` so submissions can be inspected, and returns an `<InsuranceUpdateAck>`. Never deployed for `Stage=prod`. |
- **Common layer** (`src/layers/common/python/idp_common/`) — shared across
  functions:
  - `canonical_enrollment_schema.json` / `schema.py` — the canonical record's
    JSON Schema and a `validate_canonical_record()` helper.
  - `textract_queries.py` — the template-based Textract Queries and the
    field map from query alias to canonical field name, per document
    variant (`DEFAULT_*` plus per-state `VARIANT_*` overrides).

### Template-based today, LLM-assisted later

Extraction is currently 100% template-based: a fixed set of Textract Queries
per variant, mapped to canonical fields, validated against a confidence
threshold and a JSON Schema. This keeps costs low and behavior predictable
for the common case. The `variant` concept (state-specific query sets and
field maps in `textract_queries.py`) is the seam for handling state-specific
branding/verbiage differences without forking the pipeline. An LLM-based
extraction/classification path (e.g., for documents that don't fit any
known template, or for `classify_document`'s v1 filename-convention
shortcut) can be added later as an alternate branch feeding the same
canonical schema and validation step, without changing anything downstream.

## Known TODOs

- `transform_to_xml`: the `<InsuranceUpdate>` XML is a placeholder 1:1 field
  dump. Replace with the real structure/field names once the Enrollment
  API's XSD or a sample payload is available.
- `submit_enrollment`: no authentication is sent yet. Add whatever the
  Enrollment API requires (API key / OAuth / mTLS), pulled from Secrets
  Manager.
- `classify_document`: v1 relies on the `incoming/<state>/<filename>`
  upload convention. Replace with content-based classification once
  documents can arrive without a reliable naming convention.
- `canonical_enrollment_schema.json` is a draft — align its required
  fields with what the Enrollment API's XML actually requires.

## Project layout

```
template.yaml                          SAM template (all AWS resources)
statemachine/pipeline.asl.json         Step Functions definition
src/functions/<name>/app.py            Lambda handlers
src/layers/common/python/idp_common/   Shared schema, validator, query definitions
events/s3_object_created.json          Sample EventBridge event for local invoke
tests/unit/                            pytest unit tests (one file per function/module)
```

## Prerequisites

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Python 3.13
- An AWS account/credentials with permission to create the resources in
  `template.yaml` (S3, DynamoDB, Step Functions, Lambda, KMS, SQS, IAM)

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

Subsequent deploys: `sam deploy`.

### Try it

Upload a sample document to the raw bucket using the `incoming/<state>/`
convention `classify_document` expects, e.g.:

```
aws s3 cp sample.pdf s3://<RawDocumentsBucketName>/incoming/ca/sample.pdf
```

This triggers the Step Functions execution via EventBridge. Watch progress
in the Step Functions console, or invoke a single function locally against
the sample event:

```
sam local invoke ClassifyDocumentFunction --event events/s3_object_created.json
```

## Outputs

`sam deploy` prints (and `aws cloudformation describe-stacks` can retrieve):
`RawDocumentsBucketName`, `ProcessedDocumentsBucketName`,
`EnrollmentRecordsTableName`, `PipelineStateMachineArn`, and (dev/test only)
`MockEnrollmentApiUrl`, `MockEnrollmentSubmissionsTableName`.
