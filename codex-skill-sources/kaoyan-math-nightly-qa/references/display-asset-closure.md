# Stable Display Asset Closure

Quick-package paths are provenance only. A formal Obsidian page may retain the source `manifest.json`, but it must never retain a quick/package/T9/temporary binary path.

For each exact manifest and formal-ID set:

1. Run `display_assets.py plan` and persist its JSON outside the immutable package.
2. Review the deterministic roles and exact authorization; Sol may choose display intent, never an arbitrary target path.
3. Run `display_assets.py publish --plan-file ... --authorization ...`.
4. Require stable-file hash equality, managed embed reread, bridge snapshot membership, zero forbidden formal binary references and the closure receipt.
5. Run `math_formal_lint.py` only after the closure exists.
6. Bind the closure receipt ID/SHA, formal-reference scan SHA, stable-asset count and no-display proof into archive receipt and pointer.

Question/source images are practice-safe. Solution, explanation, reference and user-work images are protected and remain inside a collapsed answer block. `other_attachment` and `solution_text` are archive-only. A closeout with no formal ID uses an empty formal-ID plan and explicit `no_display_proof`; it may still archive normally.

Cleanup is fail-closed. If stable copy, Markdown CAS, embed reread, bridge membership or formal-reference scan fails, keep the complete local package and resume only `pending_component=display_assets`. Never replay formal apply.

For historical broken references, use `historical-preview` first. Apply requires the exact preview authorization and `--apply`; run GS-908 as a single-card canary before any barrier batch. The repair tool may copy exact verified T9 bytes and update image references only. It must not change formal semantics, rebuild, rollback, Wiki semantics, `.base`, or T9 bytes.
