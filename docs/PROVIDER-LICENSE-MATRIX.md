# Provider license matrix

| Provider | Classification | Bundled | v0.1 rule |
|---|---|---:|---|
| `procedural-blender` | project core baseline | yes | deterministic and offline |
| `pixal3d-local` | optional local adapter | no | audit upstream and third-party NOTICE before enabling |
| `meshy-remote` | proprietary remote service | no | BYOK, explicit upload consent, current ToS |
| `trellis2-local` | optional GPU adapter | no | Linux/NVIDIA requirement and dependency audit |
| `hunyuan3d-2.1` | restricted model license | no | never auto-download; geography/legal gate required |
| Unity Editor | proprietary tool | no | user/CI supplies a licensed installation |

“Available” and “open source” are not interchangeable labels. No provider may silently change the core schema or turn a candidate into a blocking PASS without deterministic QA.
