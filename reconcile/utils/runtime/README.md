# Integration runtime

The `reconcile.utils.runtime` package controls the startup of integrations, the configuration of the GraphQL connection, early-exit behaviour during dry-runs and sharded dry-runs.

## Integration interface

An integration is implemented in one of two ways:

* as a Python `module` following providing certain callback functions, like a `run` function
* as a class derived from `reconcile.utils.runtime.integration.QontractReconcileIntegration`

## Integration dry-run

Each integration must provide dry-run functionality, where it simulates a reconcile run in as much detail as possible, processing the desired state with the same procedure as it will be processed in production, while not modifying target systems.

Dry-running an integration is usually used for checking a proposed change in app-interface. If such check fails, it indicates an error in the configuration (or the integration) and the respective MR will not be merged.

While those PR checks are crucial to prevent bad data to end up in the app-interface configuration state, they slow down the change process. An integration that needs to process a lot of data from various targets, tends to take a long time to finish the dry-run and it also tends to fail for unrelated errors because statistically something is always broken somewhere.

To ease the downsides of PR checks, two optimizations can be applied to an integration:

* allowed schemas
* early exit
* sharded dry-runs on affected data only

### Allowed schemas

An integration usually acts only on a small portion of the `app-interface` data. Therefore it is safe to not run an integration dry-run during a PR check, if unrelated data is changed in an MR.

A very basic and profound way to select the integrations that need to run, is the `qontract-schema` schemas that are queried by an integration. The basic thinking behind this is: if an integration does not query a certain schema, then a change in that schema is not part of the desired state the integration knows about.

The metadata to drive this schema based integration selection is found in the `/app-sre/integration-1.yml` schema, that describes integrations. The `schemas` section acts as an enforcing filter for the schemas an integration can query during runtime. If an integration tries to query an unlisted schema, it will error. Therefore it is safe to assume that a change in an unlisted schema does not hold meaningful information for an integration.

This approach works well for a lot of usecases but misses granularity for schemas that are very central to `qontract-reconciles` functionality, e.g. `/openshift/cluster-1.yml`, `/openshift/namespace-1.yml`, `/access/user-1.yml` etc. Those schemas are queried by a lot of integrations but most of the time not in full. Even if an integration requires only a small detail that never changes (e.g. `prometheusUrl` from `/openshift/cluster-1.yml`) the integration would be scheduled for a dry-run during a PR check if some other fields in a cluster change, consuming time and resources for no meaningful purpose.

### Early exit

The `early-exit` strategy tries to adress the downsides of the `allowed schemas` integration dry-run selection. It honors the fact, that each integration defines it's own part of the data from `app-interface` as its desired state. Only changes in that portion of the data will result in a full dry-run.

While the `allowed schema` strategy is implemented in integration metadata and controlled via CI scripts, the `early-exit` strategy is implemented in the integration code directly and controlled by `reconcile.utils.runtime.runner`. Each integration that wants to benefit from early exit, must offer its desired state as a `dict` of arbitrary data:

* module based integration offer a function `early_exit_desired_state(*args, **kwargs) -> dict[str, Any]`
* class based integration override a method `get_early_exit_desired_state(self, *args: Any, **kwargs: Any) -> Optional[dict[str, Any]]` and return something not `None`

`reconcile.utils.runtime.runner` calls this function twice to get the desired state from before and after the  change proposed by the MR (see `Dual-bundle qontract-server`). If the two states show no difference, then the MR does not introduce meaningful change and the integration exits early with success. Why success? Because the existing state within the `app-interface` repo is considered correct and the MR does not introduce any relevant change.

As long as an MR does not introduce relevant change, an integration dry-run can be skipped with early-exit and valueable time and resources are saved. But for integrations that have a very big desired state and run for a considerable amount of time, even the tiniest change in a isolated part of the desired state result in a lengthy PR check with all downsides.

### Sharded dry-runs on affected data only
