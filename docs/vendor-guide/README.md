# Integration Guide generator

`docs/Thermo-API-Integration-Guide.docx` (and its `.pdf`) is generated from the API itself, so its examples are always real
responses. Regenerate it after any change to the API (new endpoint, changed fields, new version number).

```bat
cd docs\vendor-guide
python export_examples.py examples.json
npm install docx
node build_guide.js ..\Thermo-API-Integration-Guide.docx examples.json
```

1. `export_examples.py` runs every documented request against the application and writes the real requests and responses
   (and the version number) to `examples.json`. It needs the Backend dependencies (`pip install -r Backend\requirements.txt`).
   It stops with an error if a documented request no longer works, which is a useful check in itself.
2. `build_guide.js` builds the Word document: cover, overview, request/response format, errors, one page per endpoint,
   health check, client examples. `npm install docx` is needed once. The explanatory text and the field tables are in
   `build_guide.js`; edit them there when an endpoint changes (the page list is the `apis` array).
3. Open the `.docx` in Word and choose *Save as PDF* (or *Export*) to refresh the `.pdf`.

Each numbered section starts on a new page. `examples.json`, `node_modules` and `package-lock.json` are generated files and
are not kept in git.
