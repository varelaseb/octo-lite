# octo-lite ownership conformance fixture

`fixture.json` is the deterministic octo-lite side of the ANN-28 ownership
contract. It names the owned source paths, role skill declarations, profile
targets, yield cases, and the exact pre-fleet shaping-review mapping.

Run the validator from this repository after installing the shared profile:

```sh
scripts/check-octo-lite-conformance \
  --profile-root "$HOME" \
  --shaping-review /path/to/shaping-review.json \
  --output fixtures/conformance/octo-lite/receipt.json
```

The receipt records the octo-lite Git revision, fixture digest, profile root,
resolved role paths, yield results, provider mapping, and the clear or blocking
shaping-review verdict. It is evidence for that exact run, not an ownership
registry.
