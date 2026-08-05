param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "asia-south1",
    [string]$JobName = "ai-stock-screener",
    [string]$SchedulerName = "ai-stock-screener-daily",
    [string]$Schedule = "0 9 * * *",
    [string]$TimeZone = "Asia/Kolkata"
)

$ErrorActionPreference = "Stop"
$runnerAccountName = "stock-screener-runner"
$schedulerAccountName = "stock-screener-scheduler"
$runnerAccount = "$runnerAccountName@$ProjectId.iam.gserviceaccount.com"
$schedulerAccount = "$schedulerAccountName@$ProjectId.iam.gserviceaccount.com"
$secretNames = @(
    "stock-screener-email-enabled",
    "stock-screener-email-delivery-method",
    "stock-screener-email-sender",
    "stock-screener-email-receiver",
    "stock-screener-gmail-client-id",
    "stock-screener-gmail-client-secret",
    "stock-screener-gmail-refresh-token",
    "stock-screener-attach-csv",
    "stock-screener-attach-pdf"
)
$secretMappings = @(
    "EMAIL_ENABLED=stock-screener-email-enabled:latest",
    "EMAIL_DELIVERY_METHOD=stock-screener-email-delivery-method:latest",
    "EMAIL_SENDER=stock-screener-email-sender:latest",
    "EMAIL_RECEIVER=stock-screener-email-receiver:latest",
    "GMAIL_CLIENT_ID=stock-screener-gmail-client-id:latest",
    "GMAIL_CLIENT_SECRET=stock-screener-gmail-client-secret:latest",
    "GMAIL_REFRESH_TOKEN=stock-screener-gmail-refresh-token:latest",
    "ATTACH_CSV=stock-screener-attach-csv:latest",
    "ATTACH_PDF=stock-screener-attach-pdf:latest"
) -join ","

function Ensure-ServiceAccount {
    param(
        [string]$Name,
        [string]$DisplayName
    )

    & gcloud iam service-accounts describe "$Name@$ProjectId.iam.gserviceaccount.com" --project=$ProjectId 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & gcloud iam service-accounts create $Name --project=$ProjectId --display-name=$DisplayName
    }
}

& gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com gmail.googleapis.com --project=$ProjectId
Ensure-ServiceAccount $runnerAccountName "AI Stock Screener runner"
Ensure-ServiceAccount $schedulerAccountName "AI Stock Screener scheduler"

foreach ($secretName in $secretNames) {
    & gcloud secrets add-iam-policy-binding $secretName --project=$ProjectId --member="serviceAccount:$runnerAccount" --role="roles/secretmanager.secretAccessor"
}

& gcloud run jobs deploy $JobName --project=$ProjectId --region=$Region --source . --service-account=$runnerAccount --tasks=1 --max-retries=1 --task-timeout=2h --set-secrets=$secretMappings
& gcloud run jobs add-iam-policy-binding $JobName --project=$ProjectId --region=$Region --member="serviceAccount:$schedulerAccount" --role="roles/run.invoker"

$jobUri = "https://$Region-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$ProjectId/jobs/$JobName:run"
& gcloud scheduler jobs describe $SchedulerName --project=$ProjectId --location=$Region 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    & gcloud scheduler jobs update http $SchedulerName --project=$ProjectId --location=$Region --schedule=$Schedule --time-zone=$TimeZone --uri=$jobUri --http-method=POST --headers="Content-Type=application/json" --message-body="{}" --oauth-service-account-email=$schedulerAccount --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
}
else {
    & gcloud scheduler jobs create http $SchedulerName --project=$ProjectId --location=$Region --schedule=$Schedule --time-zone=$TimeZone --uri=$jobUri --http-method=POST --headers="Content-Type=application/json" --message-body="{}" --oauth-service-account-email=$schedulerAccount --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
}

Write-Host "Deployment complete. Test it with: gcloud run jobs execute $JobName --project=$ProjectId --region=$Region --wait"
