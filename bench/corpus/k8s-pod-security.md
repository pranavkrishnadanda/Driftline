# Pod Security admission (bench fixture)

Synthetic bench fixture written for Driftline's load test, modelled on Kubernetes docs.

## Overview

Pod Security admission enforces the Pod Security Standards at namespace level. It
replaced PodSecurityPolicy, which was removed in Kubernetes 1.25.

## Levels

There are three levels. `privileged` is unrestricted. `baseline` prevents known
privilege escalations such as hostNetwork, hostPID and privileged containers.
`restricted` follows pod hardening best practice: containers must run as non-root, drop
all capabilities and set a seccomp profile.

## Modes

Each namespace can set three modes with labels: `enforce` rejects violating pods,
`audit` records violations in the audit log, and `warn` returns a warning to the user.
Labels take the form `pod-security.kubernetes.io/<mode>: <level>`.

## Versions

Pin a policy version with `pod-security.kubernetes.io/<mode>-version`, for example
`v1.36`, so that upgrades do not change what the namespace accepts. The default is
`latest`.
