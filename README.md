# oxpdf

Python SDK for the [0xPdf](https://0xpdf.com) PDF-to-JSON API.

## Installation

```bash
pip install oxpdf
```

## Quick Start

```python
from oxpdf import Client

client = Client(api_key="your_api_key")

# Parse with a built-in template
result = client.parse("invoice.pdf", schema_template="invoice")
print(result["data"])

# Parse with a custom schema
result = client.parse("doc.pdf", schema={
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "amount": {"type": "number"}
    }
})

# Stream parse with real-time progress
for event in client.parse_stream("large.pdf", schema_template="invoice"):
    if event["event"] == "page":
        print(f"Progress: {event['data'].get('message')}")
    elif event["event"] == "complete":
        print("Done!", event["data"])
```

## Error Handling

```python
from oxpdf import Client, OxPDFError

client = Client(api_key="your_api_key")

try:
    result = client.parse("doc.pdf", schema_template="invoice")
except OxPDFError as e:
    print(f"API error: {e} (status: {e.status_code})")
except FileNotFoundError:
    print("PDF file not found")
```

## Full API Reference

### Client

```python
Client(api_key, base_url="https://api.0xpdf.com/api/v1")
```

### PDF Parsing

| Method | Description |
|---|---|
| `parse(file_path, *, schema, schema_template, schema_id, use_ocr, ocr_engine, pages)` | Sync parse — returns structured JSON |
| `parse_stream(file_path, *, schema, schema_template, schema_id, use_ocr, ocr_engine, pages, batch_size)` | Streaming parse via SSE — yields events |
| `validate(file_path, *, schema_id, schema_name)` | Dry-run validation without processing |

### Async Jobs

| Method | Description |
|---|---|
| `upload(file_path, *, schema_id, schema_name, use_ocr, ocr_engine)` | Queue PDF for background processing |
| `job_status(job_id)` | Poll async job status |

### Image Extraction

| Method | Description |
|---|---|
| `extract_images(file_path, *, pages, min_width, min_height, use_ocr, ocr_engine)` | Extract images from a PDF |
| `list_images(*, limit, offset)` | List extracted images |
| `get_image_url(image_id, *, expiration_seconds)` | Get/refresh presigned URL |
| `delete_image(image_id)` | Delete a specific image |
| `delete_all_images()` | Delete all images |

### File Management

| Method | Description |
|---|---|
| `list_files()` | List uploaded PDFs |
| `get_file(pdf_id)` | Get PDF metadata + download URL |
| `delete_file(pdf_id)` | Delete an uploaded PDF |

### Schema CRUD

| Method | Description |
|---|---|
| `list_schemas()` | List saved schemas |
| `get_schema(schema_id)` | Get schema with full definition |
| `create_schema(name, schema, *, is_default)` | Create a new schema |
| `update_schema(schema_id, name, schema, *, is_default)` | Update existing schema |
| `delete_schema(schema_id)` | Delete a schema |
| `set_default_schema(schema_id)` | Set as default |
| `generate_schema(description, *, refinement, current_schema, selected_text)` | AI-generate a schema |

### Templates

| Method | Description |
|---|---|
| `list_templates()` | Parse templates (invoice, receipt, etc.) |
| `list_schema_templates()` | Schema editor templates |
| `get_schema_template(template_id)` | Get template with full schema |

### Analytics & Pricing

| Method | Description |
|---|---|
| `get_analytics()` | Usage analytics |
| `submit_feedback(feedback)` | Submit feedback |
| `get_pricing(*, billing_cycle)` | Get pricing tiers |
| `get_current_tier()` | Current subscription & quota |
