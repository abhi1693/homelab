{{- if or .Release.IsInstall .Values.ledgerBootstrap.migrateExisting -}}
{{- $state := dict "phase" "idle" "actions" list -}}
{{- if .Values.ledgerBootstrap.migrateExisting -}}
  {{- $state = required "Reviewed migration state is required" .Values.ledgerBootstrap.state -}}
{{- end -}}
apiVersion: coordination.k8s.io/v1
kind: Lease
metadata:
  name: pi-recovery-lock
  namespace: {{ .Release.Namespace }}
  {{- if .Values.ledgerBootstrap.migrateExisting }}
  uid: {{ required "Reviewed migration UID is required" .Values.ledgerBootstrap.uid | quote }}
  resourceVersion: {{ required "Reviewed migration resourceVersion is required" .Values.ledgerBootstrap.resourceVersion | quote }}
  {{- end }}
  labels:
    app.kubernetes.io/name: pi-recovery
    app.kubernetes.io/part-of: node-recovery
    home-lab.io/project-slug: system
  annotations:
    helm.sh/resource-policy: keep
    home-lab.io/recovery-state: {{ $state | toJson | quote }}
{{- end }}
