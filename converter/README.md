# EUDAMED → MIR 7.3.1 Converter App

## Quick start

### 1. Start the backend (from project root)
```bash
source .venv/bin/activate
uvicorn converter.backend.main:app --reload --port 8000
```

### 2. Start the frontend dev server (in a second terminal)
```bash
cd converter/frontend
npm run dev        # opens on http://localhost:5174
```

The Vite dev server proxies `/api/*` requests to `http://127.0.0.1:8000`.

### 3. Production build
```bash
cd converter/frontend
npm run build      # output in converter/frontend/dist/
```

## API

`POST /api/convert`  
Multipart form with one field: `file` (an EUDAMED XML file).

Returns JSON:
```json
{
  "filename": "mir731_SAMPLE_DTX_VIG_002.01.xml",
  "xml": "<?xml version='1.0'...>",
  "meta": {
    "reportType": "Initial",
    "eventClassification": "Death",
    "mfrRef": "...",
    "ncaReportNo": "...",
    "brandName": "...",
    "serviceId": "VIG_DOSSIER",
    "payloadType": "vig:mir_2Type"
  }
}
```

Only `serviceID=VIG_DOSSIER` + `xsi:type=vig:mir_2Type` files are converted.
All other payload types return HTTP 422 with a descriptive message.
