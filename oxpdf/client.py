"""0xPdf API client."""

import json
from pathlib import Path
from typing import Any, Generator

import requests


class OxPDFError(Exception):
    """Raised when the 0xPdf API returns an error."""

    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class Client:
    """Sync client for the 0xPdf PDF-to-JSON API."""

    def __init__(self, api_key: str, base_url: str = "https://api.0xpdf.com/api/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["X-API-Key"] = api_key

    # ── internal helpers ────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes | None, str]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)
        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                files=files,
                data=data,
                timeout=120,
            )
        except requests.RequestException as e:
            raise OxPDFError(str(e)) from e

        if resp.status_code == 204:
            return {}

        if not resp.ok:
            try:
                body = resp.json()
                detail = body.get("detail", body.get("error", resp.text))
                if isinstance(detail, list):
                    detail = "; ".join(str(d.get("msg", d)) for d in detail)
                elif not isinstance(detail, str):
                    detail = str(detail)
            except Exception:
                detail = resp.text or resp.reason or f"HTTP {resp.status_code}"
            raise OxPDFError(
                detail,
                status_code=resp.status_code,
                response_body=resp.text,
            )

        if not resp.content:
            return {}
        return resp.json()

    def _upload_pdf(
        self,
        file_path: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read a PDF from disk, validate, and POST as multipart."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError("File must be a PDF")

        with path.open("rb") as f:
            files = {"file": (path.name, f.read(), "application/pdf")}

        return self._request(
            "POST",
            endpoint,
            params=params or None,
            files=files,
            data=data,
        )

    # ── PDF parsing ─────────────────────────────────────────────────

    def parse(
        self,
        file_path: str,
        *,
        schema: dict[str, Any] | None = None,
        schema_template: str | None = None,
        schema_id: str | None = None,
        use_ocr: bool = False,
        ocr_engine: str = "surya",
        pages: list[int] | None = None,
    ) -> dict[str, Any]:
        """Parse a PDF file and return structured JSON data."""
        params: dict[str, Any] = {}
        if schema_id:
            params["schema_id"] = schema_id
        if schema_template:
            params["schema_template"] = schema_template
        if pages:
            params["pages"] = ",".join(str(p) for p in pages)

        data: dict[str, Any] = {"use_ocr": str(use_ocr).lower(), "ocr_engine": ocr_engine}
        if schema is not None:
            data["schema_json"] = json.dumps(schema)

        return self._upload_pdf(file_path, "pdf/parse", params=params, data=data)

    def parse_stream(
        self,
        file_path: str,
        *,
        schema: dict[str, Any] | None = None,
        schema_template: str | None = None,
        schema_id: str | None = None,
        use_ocr: bool = False,
        ocr_engine: str = "surya",
        pages: list[int] | None = None,
        batch_size: int = 5,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Streaming PDF parse via Server-Sent Events.

        Yields dicts with ``event`` and ``data`` keys as the backend
        processes the PDF in batches.  Event types:
        ``started``, ``page``, ``ocr``, ``complete``, ``error``.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError("File must be a PDF")

        params: dict[str, str] = {"batch_size": str(batch_size)}
        if schema_id:
            params["schema_id"] = schema_id
        if schema_template:
            params["schema_template"] = schema_template
        if pages:
            params["pages"] = ",".join(str(p) for p in pages)

        form_data: dict[str, Any] = {"use_ocr": str(use_ocr).lower(), "ocr_engine": ocr_engine}
        if schema is not None:
            form_data["schema_json"] = json.dumps(schema)

        with path.open("rb") as f:
            files = {"file": (path.name, f.read(), "application/pdf")}

        url = self._url("pdf/parse-stream")
        try:
            resp = self._session.post(
                url,
                params=params,
                files=files,
                data=form_data,
                stream=True,
                timeout=300,
            )
        except requests.RequestException as e:
            raise OxPDFError(str(e)) from e

        if not resp.ok:
            raise OxPDFError(resp.text, status_code=resp.status_code, response_body=resp.text)

        event_type = "message"
        data_lines: list[str] = []

        for line in resp.iter_lines(decode_unicode=True):
            if line is None:
                continue
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line == "":
                if data_lines:
                    raw = "\n".join(data_lines)
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = {"raw": raw}
                    yield {"event": event_type, "data": payload}
                    event_type = "message"
                    data_lines = []

    # ── Async upload (job queue) ────────────────────────────────────

    def upload(
        self,
        file_path: str,
        *,
        schema_id: str | None = None,
        schema_name: str | None = None,
        use_ocr: bool = False,
        ocr_engine: str = "surya",
    ) -> dict[str, Any]:
        """
        Upload a PDF for async background processing.

        Returns a dict with ``job_id`` — poll with :meth:`job_status`.
        """
        params: dict[str, Any] = {"use_ocr": str(use_ocr).lower(), "ocr_engine": ocr_engine}
        if schema_id:
            params["schema_id"] = schema_id
        if schema_name:
            params["schema_name"] = schema_name
        return self._upload_pdf(file_path, "pdf/upload", params=params)

    def job_status(self, job_id: str) -> dict[str, Any]:
        """Poll the status of an async PDF processing job."""
        return self._request("GET", f"pdf/status/{job_id}")

    # ── PDF validation ──────────────────────────────────────────────

    def validate(
        self,
        file_path: str,
        *,
        schema_id: str | None = None,
        schema_name: str | None = None,
    ) -> dict[str, Any]:
        """Validate a PDF without full processing (dry-run)."""
        params: dict[str, Any] = {"dry_run": "true"}
        if schema_id:
            params["schema_id"] = schema_id
        if schema_name:
            params["schema_name"] = schema_name
        return self._upload_pdf(file_path, "pdf/validate", params=params)

    # ── Image extraction ────────────────────────────────────────────

    def extract_images(
        self,
        file_path: str,
        *,
        pages: list[int] | None = None,
        min_width: int = 50,
        min_height: int = 50,
        use_ocr: bool = False,
        ocr_engine: str = "surya",
    ) -> dict[str, Any]:
        """Extract and process images from a PDF."""
        params: dict[str, Any] = {
            "min_width": str(min_width),
            "min_height": str(min_height),
            "use_ocr": str(use_ocr).lower(),
            "ocr_engine": ocr_engine,
        }
        if pages:
            params["pages"] = ",".join(str(p) for p in pages)
        return self._upload_pdf(file_path, "pdf/parse-images", params=params)

    # ── Image management ────────────────────────────────────────────

    def list_images(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """List extracted images."""
        return self._request("GET", "pdf/images", params={"limit": limit, "offset": offset})

    def get_image_url(self, image_id: str, *, expiration_seconds: int = 3600) -> dict[str, Any]:
        """Get or refresh a presigned URL for an extracted image."""
        return self._request(
            "GET",
            f"pdf/images/{image_id}/url",
            params={"expiration_seconds": expiration_seconds},
        )

    def delete_image(self, image_id: str) -> None:
        """Delete a specific extracted image."""
        self._request("DELETE", f"pdf/images/{image_id}")

    def delete_all_images(self) -> dict[str, Any]:
        """Delete all extracted images for the current user."""
        return self._request("DELETE", "pdf/images")

    # ── File management ─────────────────────────────────────────────

    def list_files(self) -> dict[str, Any]:
        """List previously uploaded PDFs."""
        return self._request("GET", "pdf/files")

    def get_file(self, pdf_id: str) -> dict[str, Any]:
        """Get metadata and download URL for an uploaded PDF."""
        return self._request("GET", f"pdf/files/{pdf_id}")

    def delete_file(self, pdf_id: str) -> None:
        """Delete an uploaded PDF."""
        self._request("DELETE", f"pdf/files/{pdf_id}")

    # ── Schema templates ────────────────────────────────────────────

    def list_templates(self) -> list[dict[str, Any]]:
        """List available pre-built schema templates (pdf route)."""
        out = self._request("GET", "pdf/templates")
        return out.get("templates", [])

    # ── Schema CRUD ─────────────────────────────────────────────────

    def list_schemas(self) -> list[dict[str, Any]]:
        """List user's saved schemas."""
        out = self._request("GET", "schemas")
        return out.get("schemas", [])

    def get_schema(self, schema_id: str) -> dict[str, Any]:
        """Get a specific schema by ID (includes full definition)."""
        return self._request("GET", f"schemas/{schema_id}")

    def create_schema(
        self,
        name: str,
        schema: dict[str, Any],
        *,
        is_default: bool = False,
    ) -> dict[str, Any]:
        """Create a new JSON schema."""
        return self._request(
            "POST",
            "schemas",
            json_body={"name": name, "schema": schema, "is_default": is_default},
        )

    def update_schema(
        self,
        schema_id: str,
        name: str,
        schema: dict[str, Any],
        *,
        is_default: bool = False,
    ) -> dict[str, Any]:
        """Update an existing schema."""
        return self._request(
            "PUT",
            f"schemas/{schema_id}",
            json_body={"name": name, "schema": schema, "is_default": is_default},
        )

    def delete_schema(self, schema_id: str) -> None:
        """Delete a schema."""
        self._request("DELETE", f"schemas/{schema_id}")

    def set_default_schema(self, schema_id: str) -> dict[str, Any]:
        """Set a schema as the default."""
        return self._request("PATCH", f"schemas/{schema_id}/set-default")

    def generate_schema(
        self,
        description: str,
        *,
        refinement: str | None = None,
        current_schema: dict[str, Any] | None = None,
        selected_text: str | None = None,
    ) -> dict[str, Any]:
        """Generate a JSON schema using AI from a natural-language description."""
        body: dict[str, Any] = {"description": description}
        if refinement:
            body["refinement"] = refinement
        if current_schema:
            body["current_schema"] = current_schema
        if selected_text:
            body["selected_text"] = selected_text
        return self._request("POST", "schemas/generate", json_body=body)

    def list_schema_templates(self) -> list[dict[str, Any]]:
        """List schema templates from the /schemas/templates/list route."""
        out = self._request("GET", "schemas/templates/list")
        return out.get("templates", [])

    def get_schema_template(self, template_id: str) -> dict[str, Any]:
        """Get a specific schema template by ID (includes full schema def)."""
        return self._request("GET", f"schemas/templates/{template_id}")

    # ── Analytics ───────────────────────────────────────────────────

    def get_analytics(self) -> dict[str, Any]:
        """Get usage analytics for the current user/org."""
        return self._request("GET", "analytics/user")

    def submit_feedback(self, feedback: str) -> dict[str, Any]:
        """Submit in-app feedback."""
        return self._request("POST", "analytics/feedback", json_body={"feedback": feedback})

    # ── Pricing ─────────────────────────────────────────────────────

    def get_pricing(self, *, billing_cycle: str = "monthly") -> dict[str, Any]:
        """Get available pricing tiers."""
        return self._request("GET", "pricing", params={"billing_cycle": billing_cycle})

    def get_current_tier(self) -> dict[str, Any]:
        """Get the current user's subscription tier and quota."""
        return self._request("GET", "pricing/current")
