# Table diagnostics review

## Summary

Optional diagnostics track selected token occurrences through actual reconstruction assignments and preserve repeated values, coordinates, header/body placement, leader exclusions, and unresolved guards. Records include existing boundary and nearby block evidence. The default disables collection.

## Action items

None remain for this evidence-only change. Review requested explicit rejected-candidate versus OCR provenance, existing processor override compatibility, forms/contents coverage, and whole-processor measurements. The tests and report include those checks.

## Evidence

The final 27 diagnostics tests pass on Linux; the earlier 22-test revision also passed in the parent Windows run. The Linux run includes the twenty heading tests, for 47 passes. The thirteen baseline table characterizations retain exact unchanged output with diagnostics off and on. Collection does not change reconstruction thresholds, HTML, recognition calls, or cleanup decisions. Raw page character data is released.

Seven groups of fifty fresh documents measured the whole `TableProcessor` with OCR disabled. Median synthetic-page time changed from 0.420 to 0.497 ms; selected public-page time changed from 1.913 to 2.058 ms. Peak traced Python allocations changed from 12,174 to 22,153 bytes and from 19,319 to 44,702 bytes respectively. Metadata occupied 2,916 and 7,913 bytes. These measurements include neighboring-block collection and cleanup, but exclude document construction, PDF parsing, inference, rendering, and full-document retention.

## Suggestions and limitations

Assigned text can still belong to the wrong row or be surrounding prose. Unresolved numeric text can be legitimate. Existing OCR HTML has no independent completeness reference. Diagnostics describe the reconstruction candidate, not replacement OCR or a later rewrite. No acceptance threshold follows from unresolved counts alone. Selected-token metadata grows with document size.

Upstream commits `5f63811`, `a86bee6`, and `2173678` establish HTML table reconstruction, mode thresholds, and disjoint-line extraction optimization. This change preserves those decisions.

## Recommendation

Approve diagnostics as evidence for the next table change. Do not treat these records as a final conversion certificate.
