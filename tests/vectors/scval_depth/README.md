# ScVal recursion and depth-boundary vectors

The vectors in `scval_depth.json` are derived from the `ScVal` XDR union in
`stellar-xdr` 28.0.1. The source links and the exact XDR bytes are recorded in
the vector file; the bytes are generated from the XDR discriminants, optional
Vec/Map flags, sequence lengths, and integer representations, not fabricated
JSON samples.

`stellar-xdr` does not define a fixed protocol-level ScVal nesting limit.
`Limits::none()` uses `u32::MAX`, and a caller may choose `Limits::depth(n)`.
The positive/negative depth pair therefore uses an explicit, documented
`Limits::depth(67)` boundary: the generated readers consume four depth units
per one-element nested Vec layer plus three for the leaf, so 16 layers are
accepted and 17 are rejected. The test also decodes both at the default
unlimited setting, proving that this is not an arbitrary depth-8 assumption.

The same corpus covers empty Vec and Map values, nested Vec/Map/Address
structures, integer minima/maxima, invalid optional flags, truncated payloads,
and a declared Map entry with no bytes for its key/value.
