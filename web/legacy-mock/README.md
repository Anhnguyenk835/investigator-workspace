# Legacy mock layer

The original prototype ran entirely on synthetic data (`mockApi`, seeded investigations,
simulated connectors and a scripted agent chat). The product now reads the real API, so
none of this is imported by `src/`, and `tsconfig`/`oxlint` do not cover this folder.

It is kept only so nothing was lost when the app was wired to the backend. Delete it when
you no longer need it for reference. The scripted agent chat (`features/agent`) has no
backend yet and is not shown in the product.
