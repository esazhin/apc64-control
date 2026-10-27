"""The plugin directory for layout generators and colour schemes (contract d12, §7.1 OCP).

Each module here is imported once when the service starts and exposes exactly one of:
  GENERATOR — an object with `name`, `params` (ParamSpecs) and `notes(params) -> 64 notes` (r1c1 first, None
              = silent), see _apc64_lab.domain.generators.PadLayoutGenerator;
  SCHEME    — an object with `name` and `colour(note, root) -> (rest Rgb, pressed Rgb)`, see ColourScheme.
A new generator or scheme is one file here plus its test; nothing else changes (d99). Plugins import only
the standard library and _apc64_lab.domain. A plugin that fails is listed as broken and never written (d13).
"""
