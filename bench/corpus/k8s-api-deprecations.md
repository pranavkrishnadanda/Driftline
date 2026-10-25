# Deprecated API migration guide (bench fixture)

Synthetic bench fixture written for Driftline's load test, modelled on Kubernetes docs.

## Ingress

The `extensions/v1beta1` and `networking.k8s.io/v1beta1` Ingress APIs were removed in
v1.22. Migrate manifests to `networking.k8s.io/v1`, where `pathType` is required and the
backend uses `service.name` and `service.port`.

## CronJob

The `batch/v1beta1` CronJob API was removed in v1.25. Use `batch/v1`, available since
v1.21. No notable field changes are needed.

## HorizontalPodAutoscaler

The `autoscaling/v2beta2` HorizontalPodAutoscaler API was removed in v1.26. Use
`autoscaling/v2`, available since v1.23.

## Finding deprecated usage

Check the `apiserver_requested_deprecated_apis` metric, and look for the
`k8s.io/deprecated` audit annotation. Run `kubectl convert` to rewrite manifests to the
new API versions.
