# Local integration evidence — 2026-10-22

## Scope

Real Blender and Unreal execution was explicitly requested. Validation used a generated rectangular prop with UVs and a blue material, a separate task sandbox and a newly created UnrealSmoke project. The Hunyuan service, production queue, protected tasks/results/logs/state folders and NinjaFrog project were not used. This is adapter smoke-test evidence, not completion of M1 with the sword/reference images.

## Observed results

- Blender 5.2.2 LTS imported the GLB, applied scale/pivot cleanup, wrote .blend/GLB/FBX, rendered three PNG previews and returned success.
- Blender QA: all checks pass. The real test exposed disconnected glTF face/normal seams: cleanup now welds coincident positions at 1e-8 meters before recalculating normals, preserving face-corner UV data. The fixture has 8 mesh vertices, 12 triangles, 0 non-manifold edges and 16 welded duplicate vertices.
- Unreal 5.7.1 imported and saved SM_Smoke and SmokeMaterial packages in a fresh import namespace.
- A separate full-editor process reloaded the saved StaticMesh and passed geometry, UV, material, collision, bounds and minimum-LOD checks.
- Measured: 12 triangles, 24 render vertices, 1 UV channel, 1 material, 1 convex collision and 1 LOD (LOD0). Dimensions are approximately 100 × 15 × 30 cm, matching the 1.0 × 0.15 × 0.30 m Blender dimensions.
- A fresh .umap was saved with the prop actor and studio lights. A 640 × 640 offscreen PNG was produced.
- Final status is AwaitingVisualReview; automatic completion was not asserted.

## Bugs revealed by real execution

1. Python commandlets do not instantiate StaticMeshEditorSubsystem. QA/test-map execution now uses full-editor startup with -ExecutePythonScript and -RenderOffscreen. Import still uses the lighter Python commandlet.
2. A one-shot capture could render fallback material shaders. The capture now invokes the engine's Editor.AsyncAssetCompilationFinishAll command before reading pixels. That command was verified in the installed UE 5.7 source (AsyncCompilationHelpers.cpp and AssetCompilingManager.cpp).
3. Coincident glTF seam vertices must be welded before recalculating connected outward normals. A real opt-in Blender regression verifies 8 closed-mesh vertices, 16 merged duplicates, UV retention and outward face normals.
4. Unreal Python Rotator positional order is roll/pitch/yaw; studio lights now use explicit named rotation fields. Fixed exposure, fill lighting and disabled bloom produce a readable shaded preview.
5. The final screenshot was visually inspected: all visible prop faces and the blue material are readable, with no fallback grid material or excessive bloom.

## GUI/worker coordination evidence

The shared transaction lock covers queue revision comparison, worker three-way merge and atomic replacement. Two separate PowerShell writers were synchronized to start from the same queue revision; exactly one saved and the stale writer was rejected. Additional tests preserve GUI-added tasks and priority changes across repeated worker updates and reject concurrent input edits, cancellation, pause and stale GUI saves. The Windows WPF view was loaded without showing it or running the GUI's production initialization.

Only cooperating writers using adapters/Studio.Queue.psm1 participate. Restart older GUI/worker instances after updating. Existing external work is not immediately interrupted by a GUI cancellation; the worker observes it on its next queue update.

## Remaining acceptance

- Actual Hunyuan image-to-mesh generation and its failure/retry behavior.
- Real sword mesh, textures and visual/historical validation.
- NinjaFrog integration and application-specific import policy.
- Production GUI usage with a running production worker.
- Controlled additional LOD generation, collision behavior tests and approval of the final visuals.
