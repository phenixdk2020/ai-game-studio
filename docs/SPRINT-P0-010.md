# P0-010: Hunyuan response validation

Implemented for the synchronous worker:
- Raw Base64 image request, without a data URL prefix.
- Accept only model/gltf-binary or application/octet-stream responses.
- Validate minimum size, GLB magic, version, declared size, chunk boundaries and first JSON asset version.
- Publish the model only after validation; preserve existing output and rejected responses.
- Record task ID, parameters, timestamps, image/output SHA256, content type and failures per attempt. Image Base64 is omitted.

Validation: 13 standard-library unit tests pass with PowerShell 7 available. Worker passes PowerShell parser validation. Git ownership exception was supplied only through process environment during tests.

Pending local ALIEN evidence: real Hunyuan /generate response, actual server content type, Blender readability, retry and GUI behavior. Structural validation does not prove mesh validity or Blender readability. The existing worker was previously untracked; this change adds its full current implementation to version control.

Next: verify this synchronous path locally, then Blender import/cleanup, previews and asset QA. Async polling and full M1 remain pending. No runtime queue, results, logs or state were edited or executed.
