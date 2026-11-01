# K3s worker agent

Joins the existing inventory registration VIP using the pinned K3s version and
encrypted inventory token. The normal rolling playbook retains its readiness
and lease gates. This role does not initialize a control plane or manage etcd.

Optional `k3s_agent.node_labels` (mapping) and `k3s_agent.node_taints` (list of
`key[=value]:effect` strings) render registration flags for a **new** worker.
They configure registration for new workers; they do not reconcile live labels
or remove taints from an existing Node. Normal rolling readiness and lease
checks remain mandatory around agent configuration changes.
