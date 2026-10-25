# Resource requests and limits (bench fixture)

Synthetic bench fixture written for Driftline's load test, modelled on Kubernetes docs.

## Requests and limits

A container's `requests` is what the scheduler reserves for it on a node. Its `limits`
is the most it may use. CPU is measured in cores (`500m` is half a core) and memory in
bytes (`256Mi`).

## What happens at the limit

A container that exceeds its CPU limit is throttled. A container that exceeds its memory
limit is killed by the kernel OOM killer and restarted according to its restart policy;
its last state shows the reason `OOMKilled`.

## Quality of service classes

Pods are `Guaranteed` when every container sets equal requests and limits for CPU and
memory, `Burstable` when at least one request or limit is set, and `BestEffort`
otherwise. Under node memory pressure, BestEffort pods are evicted first.

## LimitRange and ResourceQuota

A LimitRange sets default requests and limits for containers in a namespace. A
ResourceQuota caps the total requests and limits across the namespace.
