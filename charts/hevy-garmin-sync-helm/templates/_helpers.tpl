{{- define "hgs.labels" -}}
app.kubernetes.io/name: hevy-garmin-sync
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{- define "hgs.selector" -}}
app.kubernetes.io/name: hevy-garmin-sync
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "hgs.secret" -}}
{{- .Values.existingSecret | default .Release.Name }}
{{- end }}

{{- define "hgs.claim" -}}
{{- .Values.persistence.existingClaim | default (printf "%s-data" .Release.Name) }}
{{- end }}
